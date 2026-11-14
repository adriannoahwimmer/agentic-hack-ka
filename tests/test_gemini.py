"""Tests der Spiel-Erweiterungen von gemini.generate(): Deadline, Versuche,
Fallback-Modell abschaltbar, Request-Budget, agenerate. Nie live.
"""

import pytest
from fastapi import HTTPException
from google.genai import types

import config
import gemini
from tests.fakes import api_error, text_response

MODEL = "primary-test"


def test_timeout_ms_sets_http_options_without_mutating_config(fake_gemini):
    fake = fake_gemini([text_response("ok")])
    original = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="low")
    )
    gemini.generate("x", MODEL, original, timeout_ms=1234)

    sent = fake.models.calls[0]["config"]
    assert sent.http_options.timeout == 1234
    assert (
        sent.thinking_config.thinking_level == original.thinking_config.thinking_level
    )
    assert original.http_options is None


def test_timeout_without_config_creates_one(fake_gemini):
    fake = fake_gemini([text_response("ok")])
    gemini.generate("x", MODEL, timeout_ms=500)
    assert fake.models.calls[0]["config"].http_options.timeout == 500


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
