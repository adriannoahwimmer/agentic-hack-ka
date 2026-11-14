"""Wächter: Tests laufen mit den Defaults aus config.py, egal was in .env oder Shell steht.

Zweck: Ein Worktree mit DEBUG_ENDPOINTS=1, AGENTS_MODE=live oder kleinem Budget in
der Umgebung darf keinen Test kippen (2026-11-14: 24 Tests hingen daran).
conftest.py entfernt deshalb alle Variablen, die config.py liest, vor dem Import.
"""

import os

import config
from tests.hermetic import CONFIG_ENV_VARS


def test_config_env_vars_are_detected():
    """Die Namensliste kommt aus config.py; sie muss die Spielschlüssel enthalten."""
    expected = {
        "DEBUG_ENDPOINTS",
        "AGENTS_MODE",
        "GENAI_MAX_CALLS_TOTAL",
        "GENAI_MAX_CALLS_PER_MIN",
        "WS_MAX_EVENTS_PER_S",
        "GEMINI_MODEL_AGENT",
        "GEMINI_RETRY_ATTEMPTS",
        "WANTED_MAX",
        "TTS_VOICE",
        "GEMINI_API_KEY",
    }
    assert expected <= CONFIG_ENV_VARS


def test_no_config_env_var_leaks_into_tests():
    leaked = sorted(name for name in CONFIG_ENV_VARS if name in os.environ)
    assert leaked == []


def test_defaults_are_active():
    assert config.DEBUG_ENDPOINTS is False
    assert config.AGENTS_MODE == "offline"
    assert config.GENAI_MAX_CALLS_TOTAL == 400
    assert config.WS_MAX_EVENTS_PER_S == 20
