"""Tests der Spiel-Erweiterungen von gemini.generate(): Deadline, Versuche,
Fallback-Modell abschaltbar, Request-Budget, agenerate. Nie live.

Deadline: an Gemini geht nie weniger als GEMINI_MIN_SERVER_DEADLINE_MS (10 s, sonst 400);
die kürzere Spiel-Deadline setzt agenerate() lokal durch.
"""

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.genai import types

import config
import gemini
from tests.fakes import api_error, text_response

MODEL = "primary-test"


MIN_DEADLINE = config.GEMINI_MIN_SERVER_DEADLINE_MS


def test_minimum_server_deadline_is_10s():
    """Die API lehnt kürzere Deadlines mit 400 ab (Live-Check Polizei, 2026-11-14)."""
    assert MIN_DEADLINE == 10_000


@pytest.mark.parametrize(
    ("timeout_ms", "sent"),
    [(1234, MIN_DEADLINE), (6000, MIN_DEADLINE), (10_000, 10_000), (15_000, 15_000)],
)
def test_server_deadline_never_below_minimum(fake_gemini, timeout_ms, sent):
    fake = fake_gemini([text_response("ok")])
    original = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="low")
    )
    gemini.generate("x", MODEL, original, timeout_ms=timeout_ms)

    config_sent = fake.models.calls[0]["config"]
    assert config_sent.http_options.timeout == sent
    assert (
        config_sent.thinking_config.thinking_level
        == original.thinking_config.thinking_level
    )
    assert original.http_options is None


def test_timeout_without_config_creates_one(fake_gemini):
    fake = fake_gemini([text_response("ok")])
    gemini.generate("x", MODEL, timeout_ms=500)
    assert fake.models.calls[0]["config"].http_options.timeout == MIN_DEADLINE


def test_client_timeout_never_below_minimum(monkeypatch):
    """Auch die Client-Deadline (GEMINI_TIMEOUT_MS) geht nie unter das API-Minimum."""
    captured = {}
    monkeypatch.setattr(config, "GEMINI_TIMEOUT_MS", 5000)
    monkeypatch.setattr(
        gemini.genai, "Client", lambda **kwargs: captured.update(kwargs) or object()
    )
    gemini.get_client.cache_clear()
    gemini.get_client()
    assert captured["http_options"].timeout == MIN_DEADLINE


class _SlowModels:
    """Fake, das wie ein hängendes Modell erst nach `delay` Sekunden antwortet."""

    def __init__(self, delay):
        self.delay = delay
        self.configs = []

    def generate_content(self, *, model, contents, config=None):
        self.configs.append(config)
        time.sleep(self.delay)
        return text_response("zu spät")


@pytest.mark.anyio
async def test_agenerate_enforces_short_game_deadline_locally(monkeypatch):
    slow = _SlowModels(delay=0.6)
    monkeypatch.setattr(gemini, "get_client", lambda: SimpleNamespace(models=slow))

    started = time.perf_counter()
    with pytest.raises(HTTPException) as exc:
        await gemini.agenerate("x", MODEL, agent="police", timeout_ms=100)
    elapsed = time.perf_counter() - started

    assert exc.value.status_code == 504
    assert "100 ms" in exc.value.detail
    assert (
        elapsed < 0.5
    )  # Fallback greift nach der Spiel-Deadline, nicht nach dem Modell
    assert slow.configs[0].http_options.timeout == MIN_DEADLINE  # an Gemini: >= 10 s


@pytest.mark.anyio
async def test_agenerate_returns_when_model_is_fast_enough(monkeypatch):
    slow = _SlowModels(delay=0.0)
    monkeypatch.setattr(gemini, "get_client", lambda: SimpleNamespace(models=slow))
    response, model = await gemini.agenerate("x", MODEL, timeout_ms=2000)
    assert response.text == "zu spät"
    assert model == MODEL


def test_single_attempt_without_fallback_model(fake_gemini, backoff_sleeps):
    fake = fake_gemini([api_error(503)])
    with pytest.raises(HTTPException) as exc:
        gemini.generate("x", MODEL, attempts=1, use_fallback_model=False)
    assert exc.value.status_code == 503
    assert fake.called_models == [MODEL]
    assert backoff_sleeps == []


def test_504_without_fallback_model_stops(fake_gemini):
    fake = fake_gemini([api_error(504)])
    with pytest.raises(HTTPException):
        gemini.generate("x", MODEL, use_fallback_model=False)
    assert fake.called_models == [MODEL]


def test_budget_total_stops_before_request(fake_gemini, monkeypatch):
    monkeypatch.setattr(config, "GENAI_MAX_CALLS_TOTAL", 2)
    fake = fake_gemini([text_response("1"), text_response("2"), text_response("3")])
    gemini.generate("x", MODEL)
    gemini.generate("x", MODEL)
    with pytest.raises(HTTPException) as exc:
        gemini.generate("x", MODEL)
    assert exc.value.status_code == 503
    assert "GENAI_MAX_CALLS_TOTAL" in exc.value.detail
    assert len(fake.models.calls) == 2
    assert gemini.BUDGET.total == 2


def test_budget_per_minute(fake_gemini, monkeypatch):
    monkeypatch.setattr(config, "GENAI_MAX_CALLS_PER_MIN", 1)
    fake = fake_gemini([text_response("1"), text_response("2")])
    gemini.generate("x", MODEL)
    with pytest.raises(HTTPException, match="PER_MIN"):
        gemini.generate("x", MODEL)
    assert len(fake.models.calls) == 1


def test_budget_counts_every_attempt(fake_gemini):
    fake_gemini([api_error(503), text_response("ok")])
    gemini.generate("x", MODEL)
    assert gemini.BUDGET.total == 2


def test_transport_error_is_logged_and_reraised(fake_gemini, genai_log_lines):
    fake_gemini([TimeoutError("read timeout")])
    with pytest.raises(TimeoutError):
        gemini.generate("x", MODEL, agent="police")
    [line] = genai_log_lines()
    assert line["status"] == "error"
    assert line["error"]["code"] == "TimeoutError"
    assert line["agent"] == "police"


def test_live_enabled_follows_agents_mode(monkeypatch):
    assert gemini.live_enabled() is False  # Tests laufen offline (conftest)
    monkeypatch.setattr(config, "AGENTS_MODE", "live")
    assert gemini.live_enabled() is True


@pytest.mark.anyio
async def test_agenerate_runs_in_thread(fake_gemini):
    fake_gemini([text_response("async ok")])
    response, model = await gemini.agenerate("x", MODEL, agent="quest")
    assert response.text == "async ok"
    assert model == MODEL
