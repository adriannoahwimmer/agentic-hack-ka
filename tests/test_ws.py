"""Tests der WebSocket-Verbindung /ws und von POST /debug/action (ws.py) über die echte App.

Der Hub ist pro Test frisch (Fixture fresh_hub); die App läuft mit Lifespan
(TestClient als Context-Manager), damit agent_log aus Threads ankommt.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import genai_log
import main
import protocol

EXAMPLES = Path(__file__).resolve().parent.parent / "contract" / "examples"


def _example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def app_client(fresh_hub):
    """TestClient mit Lifespan (Hub gestartet) und frischem Hub."""
    with TestClient(main.app) as client:
        yield client


def _collect(hub, event_type):
    """Registriert einen Handler und gibt die Liste der empfangenen Events zurück."""
    seen = []
    hub.on_event(event_type, lambda event, env: seen.append(event))
    return seen


def test_valid_event_reaches_handler(app_client, fresh_hub):
    seen = _collect(fresh_hub, "shot_fired")
    with app_client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps(_example("shot_fired")))
        ws.send_text("sync")  # Antwort (error) heißt: das Event davor ist verarbeitet
        assert ws.receive_json()["payload"]["code"] == "invalid_message"
    assert [e.shots for e in seen] == [6]


def test_invalid_messages_get_error_and_connection_stays(app_client, fresh_hub):
    seen = _collect(fresh_hub, "zone_entered")
    with app_client.websocket_connect("/ws") as ws:
        ws.send_text("not json")
        assert ws.receive_json()["payload"]["code"] == "invalid_message"
        ws.send_text(json.dumps({"type": "teleport", "ts": 1, "payload": {}}))
        assert ws.receive_json()["payload"]["code"] == "unknown_type"
        ws.send_text(json.dumps(_example("zone_entered")))
        ws.send_text("sync")
        ws.receive_json()
    assert [e.zone_id for e in seen] == ["marktplatz"]


def test_rate_limit(app_client, fresh_hub, monkeypatch):
    monkeypatch.setattr(config, "WS_MAX_EVENTS_PER_S", 2)
    seen = _collect(fresh_hub, "zone_entered")
    with app_client.websocket_connect("/ws") as ws:
        for _ in range(4):
            ws.send_text(json.dumps(_example("zone_entered")))
        assert ws.receive_json()["payload"]["code"] == "rate_limited"
    assert len(seen) == 2


def test_state_is_sent_on_connect(app_client, fresh_hub):
    fresh_hub.on_connect(
        lambda: [
            protocol.make_action(
                "set_wanted_level", _example("set_wanted_level")["payload"]
            )
        ]
    )
    with app_client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "set_wanted_level"
    assert fresh_hub.client_count == 0  # nach dem Trennen entfernt


def test_debug_action_is_404_without_flag(app_client):
    r = app_client.post("/debug/action", json=_example("spawn_units"))
    assert r.status_code == 404


def test_debug_action_broadcasts(app_client, monkeypatch):
    monkeypatch.setattr(config, "DEBUG_ENDPOINTS", True)
    with app_client.websocket_connect("/ws") as ws:
        r = app_client.post("/debug/action", json=_example("spawn_units"))
        assert r.status_code == 200
        assert r.json()["clients"] == 1
        msg = ws.receive_json()
    assert msg["type"] == "spawn_units"
    assert msg["payload"] == _example("spawn_units")["payload"]


def test_debug_action_rejects_invalid(app_client, monkeypatch):
    monkeypatch.setattr(config, "DEBUG_ENDPOINTS", True)
    bad = _example("spawn_units")
    bad["payload"]["count"] = 99
    assert app_client.post("/debug/action", json=bad).status_code == 422


def test_genai_log_line_arrives_as_agent_log(app_client):
    with app_client.websocket_connect("/ws") as ws:
        genai_log.log_fallback(
            agent="police",
            actions=[
                {"tool": "spawn_units", "args": {"target_units": 2, "reason": "test"}}
            ],
        )
        msg = ws.receive_json()
    assert msg["type"] == "agent_log"
    assert msg["payload"]["agent"] == "police"
    assert msg["payload"]["reason"] == "test"
    assert "prompt" not in msg["payload"]
