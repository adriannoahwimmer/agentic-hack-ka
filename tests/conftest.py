"""Gemeinsame Fixtures. Tests rufen Gemini NIE live auf (Quota und Kosten).

Autouse: echter Client blockiert, Backoff ohne Warten, GenAI-Log in tmp_path,
Budget frisch, AGENTS_MODE=offline, keine Log-Listener aus anderen Tests.
"""

import os

# Tests sind hermetisch: die lokale .env (echter Key, Modell-Overrides) nie laden.
# Muss vor `import main` stehen, weil config.py die .env beim Import lädt.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import pytest

import config
import gemini
import genai_log
import hub
import main  # noqa: F401 - App einmal importieren (lädt Features wie im Betrieb)
from tests.fakes import FakeClient


@pytest.fixture(autouse=True)
def block_live_gemini(monkeypatch):
    """Blockiert den echten Client: wer get_client nicht mockt, bekommt einen Fehler."""

    def _blocked(*args, **kwargs):
        raise RuntimeError("Live-Gemini-Aufruf in Tests verboten - get_client mocken")

    # Original merken: Tests ersetzen gemini.get_client evtl. per monkeypatch.
    real_get_client = gemini.get_client
    monkeypatch.setattr(gemini.genai, "Client", _blocked)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    real_get_client.cache_clear()
    yield
    real_get_client.cache_clear()


@pytest.fixture(autouse=True)
def backoff_sleeps(monkeypatch):
    """Backoff ohne echte Wartezeit. Liefert die Liste der angefragten Delays."""
    delays = []
    monkeypatch.setattr(gemini, "_sleep", delays.append)
    return delays


@pytest.fixture(scope="session")
def _genai_log_dir(tmp_path_factory):
    """Ein temporäres Verzeichnis für alle Test-Logs (tmp_path pro Test ist auf Windows teuer)."""
    return tmp_path_factory.mktemp("genai_logs")


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, request, _genai_log_dir):
    """GenAI-Log in eine eigene Datei pro Test, frisches Budget, offline, keine Log-Listener."""
    log_name = f"{abs(hash(request.node.nodeid)):x}-{id(request)}.jsonl"
    monkeypatch.setattr(config, "GENAI_LOG_PATH", _genai_log_dir / log_name)
    monkeypatch.setattr(config, "AGENTS_MODE", "offline")
    gemini.BUDGET.reset()
    genai_log.clear_listeners()
    yield
    genai_log.clear_listeners()


@pytest.fixture
def genai_log_lines():
    """Liest die in diesem Test geschriebenen JSONL-Zeilen (Liste von dicts)."""
    import json

    def _read():
        path = config.GENAI_LOG_PATH
        if not path.exists():
            return []
        return [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]

    return _read


@pytest.fixture
def fresh_hub(monkeypatch):
    """Eigener Hub für diesen Test; ws.py und main.lifespan nutzen ihn automatisch."""
    h = hub.Hub()
    monkeypatch.setattr(hub, "HUB", h)
    yield h
    h.stop()


@pytest.fixture
def fake_gemini(monkeypatch):
    """fake_gemini([resp1, resp2, ...]) -> FakeClient; Antworten kommen der Reihe nach."""

    def _install(responses):
        client = FakeClient(responses)
        monkeypatch.setattr(gemini, "get_client", lambda: client)
        return client

    return _install
