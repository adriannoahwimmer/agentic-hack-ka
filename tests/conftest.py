"""Gemeinsame Fixtures. Tests rufen Gemini NIE live auf (Quota und Kosten)."""

import os

# Tests sind hermetisch: die lokale .env (echter Key, Modell-Overrides) nie laden.
# Muss vor `import main` stehen, weil config.py die .env beim Import lädt.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import pytest

import main
from tests.fakes import FakeClient


@pytest.fixture(autouse=True)
def block_live_gemini(monkeypatch):
    """Blockiert den echten Client: wer get_client nicht mockt, bekommt einen Fehler."""

    def _blocked(*args, **kwargs):
        raise RuntimeError("Live-Gemini-Aufruf in Tests verboten - get_client mocken")

    # Original merken: Tests ersetzen main.get_client evtl. per monkeypatch.
    real_get_client = main.get_client
    monkeypatch.setattr(main.genai, "Client", _blocked)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    real_get_client.cache_clear()
    yield
    real_get_client.cache_clear()


@pytest.fixture(autouse=True)
def backoff_sleeps(monkeypatch):
    """Backoff ohne echte Wartezeit. Liefert die Liste der angefragten Delays."""
    delays = []
    monkeypatch.setattr(main, "_sleep", delays.append)
    return delays


@pytest.fixture
def fake_gemini(monkeypatch):
    """fake_gemini([resp1, resp2, ...]) -> FakeClient; Antworten kommen der Reihe nach."""

    def _install(responses):
        client = FakeClient(responses)
        monkeypatch.setattr(main, "get_client", lambda: client)
        return client

    return _install
