"""Tests für Retry, Fallback und 429-Handling in main.generate() und für config.py.

Zweck: sicherstellen, dass 5xx mit Backoff wiederholt und dann auf das
Fallback-Modell ausgewichen wird, 429 nie wiederholt wird und alle Werte aus
config.py per Env überschreibbar sind. Gemini wird nie live aufgerufen.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

import config
import main
from tests.fakes import api_error, call_response, text_response

client = TestClient(main.app)

CHAT = config.GEMINI_MODEL_CHAT
AGENT = config.GEMINI_MODEL_AGENT
FALLBACK = config.GEMINI_MODEL_FALLBACK
N = config.GEMINI_RETRY_ATTEMPTS


def test_fallback_differs_from_primary_models():
    """Ohne eigenes Fallback-Modell testen die Fallback-Tests unten nichts."""
    assert FALLBACK not in {CHAT, AGENT}


@pytest.mark.parametrize("path", ["/chat", "/agent"])
def test_thinking_level_is_sent(fake_gemini, path):
    """/chat und /agent schicken das thinking_level aus config.py mit."""
    fake = fake_gemini([text_response("ok")])
    assert client.get(path, params={"q": "x"}).status_code == 200
    level = fake.models.calls[0]["config"].thinking_config.thinking_level
    assert level.value.lower() == config.GEMINI_THINKING_LEVEL.lower()


@pytest.mark.parametrize("code", [500, 502, 503])
def test_5xx_is_retried_with_backoff(fake_gemini, backoff_sleeps, code):
    """Ein einzelner 5xx wird nach einer Backoff-Pause mit demselben Modell wiederholt."""
    fake = fake_gemini([api_error(code), text_response("Hallo!")])
    r = client.get("/chat", params={"q": "x"})

    assert r.status_code == 200
    assert r.json() == {"answer": "Hallo!", "model": CHAT}
    assert fake.called_models == [CHAT, CHAT]
    assert len(backoff_sleeps) == 1


def test_504_falls_back_without_same_model_retry(fake_gemini, backoff_sleeps):
    """504 (Deadline) geht ohne Backoff direkt zum Fallback-Modell."""
    fake = fake_gemini([api_error(504), text_response("Lite-Antwort")])
    r = client.get("/chat", params={"q": "x"})

    assert r.status_code == 200
    assert r.json() == {"answer": "Lite-Antwort", "model": FALLBACK}
    assert fake.called_models == [CHAT, FALLBACK]
    assert backoff_sleeps == []


def test_504_on_both_models_is_503(fake_gemini):
    """504 bei Primär- und Fallback-Modell: je ein Versuch, dann 503."""
    fake = fake_gemini([api_error(504, "Deadline expired"), api_error(504)])
    r = client.get("/chat", params={"q": "x"})

    assert r.status_code == 503
    assert fake.called_models == [CHAT, FALLBACK]


def test_503_exhausted_falls_back(fake_gemini, backoff_sleeps):
    """Nach GEMINI_RETRY_ATTEMPTS Fehlversuchen antwortet das Fallback-Modell."""
    fake = fake_gemini([api_error(503)] * N + [text_response("Lite-Antwort")])
    r = client.get("/chat", params={"q": "x"})

    assert r.status_code == 200
    assert r.json() == {"answer": "Lite-Antwort", "model": FALLBACK}
    assert fake.called_models == [CHAT] * N + [FALLBACK]
    # Backoff nur zwischen Versuchen desselben Modells, nicht vor dem Fallback
    assert len(backoff_sleeps) == N - 1


def test_all_models_overloaded_is_503(fake_gemini, backoff_sleeps):
    """Sind Primär- und Fallback-Modell überlastet, kommt 503 mit beiden Namen."""
    fake = fake_gemini([api_error(503, "overloaded")] * (2 * N))
    r = client.get("/chat", params={"q": "x"})

    assert r.status_code == 503
    detail = r.json()["detail"]
    assert CHAT in detail and FALLBACK in detail and "overloaded" in detail
    assert fake.called_models == [CHAT] * N + [FALLBACK] * N
    assert len(backoff_sleeps) == 2 * (N - 1)


def test_429_is_not_retried_and_hints_spend_cap(fake_gemini, backoff_sleeps):
    """429 geht sofort mit Spend-Cap-Hinweis an den Client, ohne Retry."""
    fake = fake_gemini([api_error(429, "Resource exhausted")])
    r = client.get("/chat", params={"q": "x"})

    assert r.status_code == 429
    detail = r.json()["detail"]
    assert "Spend-Cap erreicht? aistudio.google.com/spend" in detail
    assert "Resource exhausted" in detail
    assert fake.called_models == [CHAT]
    assert backoff_sleeps == []


def test_429_on_fallback_is_not_retried(fake_gemini):
    """Auch ein 429 vom Fallback-Modell wird nicht wiederholt."""
    fake = fake_gemini([api_error(503)] * N + [api_error(429)])
    r = client.get("/chat", params={"q": "x"})

    assert r.status_code == 429
    assert FALLBACK in r.json()["detail"]
    assert fake.called_models == [CHAT] * N + [FALLBACK]


def test_no_duplicate_attempts_when_model_is_fallback(fake_gemini, monkeypatch):
    """Ist das Primärmodell schon das Fallback-Modell, gibt es keine Extrarunde."""
    monkeypatch.setattr(config, "GEMINI_MODEL_CHAT", FALLBACK)
    fake = fake_gemini([api_error(503)] * N)
    r = client.get("/chat", params={"q": "x"})

    assert r.status_code == 503
    assert fake.called_models == [FALLBACK] * N


def test_agent_stays_on_fallback_after_switch(fake_gemini):
    """Nach dem Wechsel läuft der restliche Tool-Loop auf dem Fallback-Modell."""
    fake = fake_gemini(
        [api_error(503)] * N
        + [call_response(("calculator", {"expression": "2 + 2"})), text_response("4")]
    )
    r = client.get("/agent", params={"q": "2+2?"})

    assert r.status_code == 200
    assert r.json()["model"] == FALLBACK
    assert r.json()["answer"] == "4"
    # Zweiter Loop-Schritt startet direkt beim Fallback, nicht wieder beim Agent-Modell
    assert fake.called_models == [AGENT] * N + [FALLBACK, FALLBACK]


@pytest.mark.parametrize("attempt", range(5))
def test_backoff_delay_grows_with_jitter_and_cap(attempt):
    """Wartezeit liegt zwischen halber und voller Obergrenze, die sich verdoppelt."""
    ceiling = min(
        config.GEMINI_RETRY_MAX_DELAY, config.GEMINI_RETRY_BASE_DELAY * 2**attempt
    )
    for _ in range(20):
        assert ceiling / 2 <= main.backoff_delay(attempt) <= ceiling


ENV_OVERRIDES = {
    "GEMINI_MODEL_AGENT": ("agent-x", "agent-x"),
    "GEMINI_MODEL_CHAT": (" chat-x ", "chat-x"),
    "GEMINI_MODEL_FALLBACK": ("fallback-x", "fallback-x"),
    "GEMINI_THINKING_LEVEL": ("medium", "medium"),
    "MAX_AGENT_STEPS": ("3", 3),
    "GEMINI_TIMEOUT_MS": ("5000", 5000),
    "GEMINI_TRANSPORT_ATTEMPTS": ("0", 1),  # mindestens 1
    "GEMINI_RETRY_ATTEMPTS": ("5", 5),
    "GEMINI_RETRY_BASE_DELAY": ("0.5", 0.5),
    "GEMINI_RETRY_MAX_DELAY": ("4", 4.0),
}


def test_all_settings_overridable_via_env():
    """Jede Einstellung in config.py lässt sich per gleichnamiger Env-Var setzen."""
    try:
        with pytest.MonkeyPatch.context() as mp:
            for name, (raw, _) in ENV_OVERRIDES.items():
                mp.setenv(name, raw)
            reloaded = importlib.reload(config)
            actual = {name: getattr(reloaded, name) for name in ENV_OVERRIDES}
            assert actual == {name: want for name, (_, want) in ENV_OVERRIDES.items()}
    finally:
        importlib.reload(config)  # Env ist wiederhergestellt -> Originalwerte


def test_default_models_follow_latency_benchmark():
    """Ohne Env: schnellstes Modell für Agent und Chat, zweitschnellstes als Fallback."""
    names = ("GEMINI_MODEL_AGENT", "GEMINI_MODEL_CHAT", "GEMINI_MODEL_FALLBACK")
    try:
        with pytest.MonkeyPatch.context() as mp:
            for name in names:
                mp.delenv(name, raising=False)
            reloaded = importlib.reload(config)
            assert [getattr(reloaded, name) for name in names] == [
                "gemini-3.5-flash-lite",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            ]
    finally:
        importlib.reload(config)  # Env ist wiederhergestellt -> Originalwerte


def test_invalid_number_names_the_variable(monkeypatch):
    """Ein Tippfehler in einer Zahl-Variable nennt die Variable in der Meldung."""
    monkeypatch.setenv("GEMINI_TEST_NUMBER", "zehn")
    with pytest.raises(ValueError, match="GEMINI_TEST_NUMBER"):
        config._env_number("GEMINI_TEST_NUMBER", 1)


def test_empty_env_value_uses_default(monkeypatch):
    """Leere Werte (wie in .env.example) überschreiben den Default nicht."""
    monkeypatch.setenv("GEMINI_TEST_VAR", "  ")
    assert config._env("GEMINI_TEST_VAR", "default") == "default"
