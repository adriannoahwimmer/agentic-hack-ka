"""Tests für quests.py: Quest-Wahrheit per Position und Kills, Reconnect, Fallback-Quest."""

import asyncio
import random

import pytest

import config
import protocol
import quests
from hub import Hub


def _poi(poi_id="marktplatz"):
    return protocol.load_pois().get(poi_id)


class _Client:
    """Fake-WS-Client: sammelt gesendete Envelopes."""

    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(protocol.Envelope.model_validate_json(text))


def _setup():
    h, book, client = Hub(), quests.QuestBook(), _Client()
    quests.register(h, book)
    h.add_client(client)
    return h, book, client


def _publish(h, type_, payload):
    asyncio.run(h.publish_event(protocol.make_event(type_, payload)))


def _pos(x, z):
    return {"x": x, "z": z, "heading": 0, "speed": 1, "in_vehicle": False}


def test_create_clamps_enemies_and_validates_poi():
    book = quests.QuestBook()
    update = book.create("marktplatz", "T", "O", 99)
    assert update.status == "active"
    assert update.remaining == config.QUEST_MAX_TARGETS
    assert update.target.radius == _poi().radius


@pytest.mark.parametrize(
    "poi_id", ["nope", "schloss"]
)  # schloss hat keinen mission-Tag
def test_unknown_or_non_mission_poi_is_rejected(poi_id):
    with pytest.raises(quests.QuestError):
        quests.QuestBook().create(poi_id, "T", "O", 2)


def test_second_quest_is_rejected_while_active():
    book = quests.QuestBook()
    book.create("marktplatz", "T", "O", 2)
    with pytest.raises(quests.QuestError, match="still active"):
        book.create("kronenplatz", "T", "O", 2)


def test_position_outside_then_inside_radius():
    h, book, client = _setup()
    book.create("marktplatz", "T", "O", 3)
    poi = _poi()
    _publish(h, "player_position", _pos(poi.x + poi.radius + 5, poi.z))
    assert client.sent == []
    _publish(h, "player_position", _pos(poi.x + poi.radius - 1, poi.z))
    assert [e.payload["status"] for e in client.sent] == ["target_reached"]
    assert client.sent[0].payload["spawn_targets"] == 3
    assert client.sent[0].payload["remaining"] == 3
    # Erneute Position im Radius löst nichts mehr aus
    _publish(h, "player_position", _pos(poi.x, poi.z))
    assert len(client.sent) == 1


def test_kills_with_wrong_and_right_quest_id():
    h, book, client = _setup()
    qid = book.create("marktplatz", "T", "O", 2).quest_id
    poi = _poi()
    _publish(h, "player_position", _pos(poi.x, poi.z))
    client.sent.clear()
    kill = {"npc_id": "t1", "npc_kind": "quest_target", "x": poi.x, "z": poi.z}
    _publish(h, "npc_killed", {**kill, "quest_id": "q-999"})
    _publish(h, "npc_killed", {**kill, "npc_kind": "civilian", "quest_id": qid})
    assert client.sent == []
    _publish(h, "npc_killed", {**kill, "quest_id": qid})
    _publish(h, "npc_killed", {**kill, "npc_id": "t2", "quest_id": qid})
    statuses = [(e.payload["status"], e.payload["remaining"]) for e in client.sent]
    assert statuses == [("target_reached", 1), ("completed", 0)]
    assert client.sent[0].payload["spawn_targets"] == 0
    assert book.active is None and len(book.history) == 1


def test_reconnect_delivers_active_quest_with_remaining_targets():
    h, book, _ = _setup()
    assert asyncio.run(h.connect_messages()) == []
    book.create("marktplatz", "T", "O", 3)
    poi = _poi()
    _publish(h, "player_position", _pos(poi.x, poi.z))
    messages = asyncio.run(h.connect_messages())
    assert [m.type for m in messages] == ["quest_update"]
    assert messages[0].payload["spawn_targets"] == 3


def test_snapshot_provider():
    h, book, _ = _setup()
    assert "quest" not in h.snapshot_extras()
    book.create("marktplatz", "Pyramid Trouble", "O", 2)
    assert h.snapshot_extras()["quest"] == {
        "title": "Pyramid Trouble",
        "poi_id": "marktplatz",
        "status": "active",
    }


def test_fallback_quest_avoids_current_zone():
    rng = random.Random(1)
    for _ in range(30):
        args = quests.fallback_quest(zone_id="marktplatz", rng=rng)
        assert args["poi_id"] != "marktplatz"
        assert "mission" in _poi(args["poi_id"]).tags
        quests.QuestBook().create(**args)  # immer gültig
