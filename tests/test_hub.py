"""Tests des Event-/Action-Busses (hub.py): Reihenfolge, Validierung, Fehlerisolation,
Snapshot-Provider, Thread-Übergabe und Weiterleitung der GenAI-Logzeilen.
"""

import asyncio
import json
import threading

import pytest

import genai_log
import protocol
from hub import Hub

SHOT = {"x": 1.0, "z": 2.0, "shots": 3, "weapon": "pistol", "zone_id": "marktplatz"}
WANTED = {"level": 1, "source": "rules", "reason": "shots"}


class FakeSocket:
    """Client wie ein WebSocket: sammelt gesendete Nachrichten als dicts."""

    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


class DeadSocket:
    """Client, dessen Verbindung schon weg ist."""

    async def send_text(self, text):
        raise ConnectionError("weg")


async def _wait_for(predicate, timeout=1.0):
    """Wartet im Event-Loop, bis predicate() wahr ist."""
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Bedingung nicht erfüllt")


def test_unknown_types_are_rejected():
    hub = Hub()
    with pytest.raises(ValueError):
        hub.on_event("teleport", print)
    with pytest.raises(ValueError):
        hub.on_action("shot_fired", print)  # Event, keine Aktion


@pytest.mark.anyio
async def test_publish_event_order_and_isolation():
    hub = Hub()
    calls = []

    def first(event, env):
        calls.append(("first", event.shots))
        raise RuntimeError("kaputt")

    async def second(event, env):
        calls.append(("second", env.type))

    hub.on_event("shot_fired", first)
    hub.on_event("shot_fired", second)
    hub.on_event("*", lambda event, env: calls.append(("star", type(event).__name__)))
    hub.on_event("npc_killed", lambda event, env: calls.append(("wrong", None)))

    await hub.publish_event(protocol.make_event("shot_fired", SHOT))
    assert calls == [("first", 3), ("second", "shot_fired"), ("star", "ShotFired")]


@pytest.mark.anyio
async def test_send_action_validates_notifies_and_broadcasts():
    hub = Hub()
    alive, observed = FakeSocket(), []
    hub.add_client(alive)
    hub.add_client(DeadSocket())
    hub.on_action("set_wanted_level", lambda model, env: observed.append(model.level))

    env = await hub.send_action("set_wanted_level", WANTED)

    assert observed == [1]
    assert alive.sent == [env.model_dump()]
    assert hub.client_count == 1  # tote Verbindung entfernt


@pytest.mark.anyio
async def test_invalid_action_is_not_sent():
    hub = Hub()
    sock = FakeSocket()
    hub.add_client(sock)
    with pytest.raises(protocol.ProtocolError):
        await hub.send_action(
            "set_wanted_level", {"level": 99, "source": "rules", "reason": ""}
        )
    assert sock.sent == []


@pytest.mark.anyio
async def test_connect_messages_skip_failing_hooks():
    hub = Hub()
    hub.on_connect(lambda: [protocol.make_action("set_wanted_level", WANTED)])
    hub.on_connect(lambda: 1 / 0)

    async def async_hook():
        return []

    hub.on_connect(async_hook)
    messages = await hub.connect_messages()
    assert [m.type for m in messages] == ["set_wanted_level"]


def test_snapshot_providers():
    hub = Hub()
    hub.register_snapshot_provider("wanted", lambda: {"level": 2})
    hub.register_snapshot_provider("quest", lambda: None)
    hub.register_snapshot_provider("broken", lambda: 1 / 0)
    with pytest.raises(ValueError):
        hub.register_snapshot_provider("wanted", dict)
    assert hub.snapshot_extras() == {"wanted": {"level": 2}}


def test_send_action_threadsafe_without_loop():
    assert Hub().send_action_threadsafe("set_wanted_level", WANTED) is False


@pytest.mark.anyio
async def test_send_action_threadsafe_from_worker_thread():
    hub = Hub()
    sock = FakeSocket()
    hub.add_client(sock)
    hub.start(asyncio.get_running_loop())
    try:
        worker = threading.Thread(
            target=hub.send_action_threadsafe, args=("set_wanted_level", WANTED)
        )
        worker.start()
        worker.join()
        await _wait_for(lambda: sock.sent)
        assert sock.sent[0]["type"] == "set_wanted_level"
    finally:
        hub.stop()


@pytest.mark.anyio
async def test_start_forwards_genai_log_as_agent_log():
    hub = Hub()
    sock = FakeSocket()
    hub.add_client(sock)
    hub.start(asyncio.get_running_loop())
    genai_log.log_fallback(
        agent="police",
        actions=[{"tool": "set_wanted_level", "args": {"level": 1}}],
        reason="rules",
    )
    await _wait_for(lambda: sock.sent)
    msg = sock.sent[0]
    assert msg["type"] == "agent_log"
    assert msg["payload"]["kind"] == "fallback"
    assert "prompt" not in msg["payload"]

    hub.stop()
    genai_log.log_fallback(agent="police", actions=[], reason="after stop")
    await asyncio.sleep(0.05)
    assert len(sock.sent) == 1
