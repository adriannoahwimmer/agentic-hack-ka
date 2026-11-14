"""Vertragstests: protocol.py gegen contract/examples/ und data/pois.json.

Zweck: Jede Nachricht aus Design.md ("Vertrag") hat ein Beispiel, das gegen das
Pydantic-Modell validiert. Grenzen (Level, Anzahl, Textlänge) werden erzwungen.
"""

import json
from pathlib import Path

import pytest

import config
import protocol as p

EXAMPLES = Path(__file__).resolve().parent.parent / "contract" / "examples"

# Beispiele ohne Envelope -> Modell
PLAIN_EXAMPLES = {
    "npc_talk_request": p.NpcTalkRequest,
    "npc_talk_response": p.NpcTalkResponse,
    "snapshot_police": p.AgentSnapshot,
    "genai_log_line": p.GenaiLogLine,
}


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def _example_names() -> list[str]:
    return sorted(f.stem for f in EXAMPLES.glob("*.json"))


@pytest.mark.parametrize("name", _example_names())
def test_example_validates(name):
    data = _load(name)
    if name in PLAIN_EXAMPLES:
        PLAIN_EXAMPLES[name].model_validate(data)
        return
    env = p.Envelope.model_validate(data)
    assert env.type == name
    if name in p.EVENT_MODELS:
        p.parse_client_message(json.dumps(data))
    else:
        p.make_action(env.type, env.payload)


def test_every_message_type_has_example():
    expected = set(p.EVENT_MODELS) | set(p.ACTION_MODELS) | set(PLAIN_EXAMPLES)
    assert expected == set(_example_names())


def test_parse_client_message_returns_typed_event():
    env, event = p.parse_client_message(json.dumps(_load("shot_fired")))
    assert env.type == "shot_fired"
    assert isinstance(event, p.ShotFired)
    assert event.shots == 6


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("not json", "invalid_message"),
        ('{"type": "teleport", "ts": 1, "payload": {}}', "unknown_type"),
        ('{"type": "set_wanted_level", "ts": 1, "payload": {}}', "unknown_type"),
        ('{"type": "shot_fired", "ts": 1, "payload": {"x": 0}}', "invalid_message"),
        (
            json.dumps(
                {
                    "type": "shot_fired",
                    "ts": 1,
                    "payload": {"x": 0, "z": 0, "shots": 99, "weapon": "pistol"},
                }
            ),
            "invalid_message",
        ),
    ],
)
def test_parse_client_message_rejects(raw, fragment):
    with pytest.raises(p.ProtocolError, match=fragment):
        p.parse_client_message(raw)


def test_client_events_ignore_unknown_fields():
    data = _load("zone_entered")
    data["payload"]["extra_from_newer_client"] = 1
    _, event = p.parse_client_message(json.dumps(data))
    assert event.zone_id == "marktplatz"


def test_server_actions_reject_unknown_fields():
    payload = _load("set_wanted_level")["payload"] | {"stars": 2}
    with pytest.raises(p.ProtocolError):
        p.make_action("set_wanted_level", payload)


@pytest.mark.parametrize(
    ("type_", "change"),
    [
        ("set_wanted_level", {"level": config.WANTED_MAX + 1}),
        ("set_wanted_level", {"level": -1}),
        ("spawn_units", {"count": config.POLICE_MAX_UNITS + 1}),
        ("spawn_units", {"count": 0}),
        ("spawn_units", {"tactic": "nuke"}),
        ("quest_update", {"remaining": config.QUEST_MAX_TARGETS + 1}),
    ],
)
def test_action_bounds(type_, change):
    payload = _load(type_)["payload"] | change
    with pytest.raises(p.ProtocolError):
        p.make_action(type_, payload)


def test_make_action_accepts_model_and_sets_ts():
    env = p.make_action(
        "set_wanted_level", p.SetWantedLevel(level=1, source="rules", reason="shots")
    )
    assert env.payload == {"level": 1, "source": "rules", "reason": "shots"}
    assert env.ts > 1_700_000_000_000


def test_radio_example_key_matches_text():
    payload = _load("radio_message")["payload"]
    assert payload["tts_key"] == p.tts_key(payload["text"], payload["voice"])


def test_make_radio_message_is_deterministic_and_truncates():
    long_text = "Unit   two,\nrespond. " + "x" * 500
    a = p.make_radio_message(long_text)
    b = p.make_radio_message(long_text)
    assert a.tts_key == b.tts_key
    assert a.id != b.id
    assert len(a.text) == config.RADIO_MAX_CHARS
    assert a.text.startswith("Unit two, respond.")
    assert a.voice == config.TTS_VOICE
    assert (
        p.make_radio_message("hi", voice="Kore").tts_key
        != p.make_radio_message("hi").tts_key
    )


def test_log_line_to_agent_log_drops_prompt_and_config():
    line = p.GenaiLogLine.model_validate(_load("genai_log_line"))
    log = line.to_agent_log()
    assert "prompt" not in log.model_dump()
    assert log.output.calls[0].tool == "set_wanted_level"
    assert log == p.AgentLog.model_validate(_load("agent_log")["payload"])


def test_snapshot_prompt_is_compact():
    snap = p.AgentSnapshot.model_validate(_load("snapshot_police"))
    assert len(snap.to_prompt().encode()) < 2048


def test_pois_file_is_valid():
    pois = p.load_pois()
    assert len(pois.pois) >= 8
    assert sum("mission" in poi.tags for poi in pois.pois) >= 4
    assert any("npc_spot" in poi.tags for poi in pois.pois)
    assert pois.get("marktplatz").name == "Market Square"
    assert pois.get("nope") is None


def test_poi_file_rejects_duplicate_ids():
    data = json.loads(p.POIS_PATH.read_text(encoding="utf-8"))
    data["pois"].append(data["pois"][0])
    with pytest.raises(ValueError, match="eindeutig"):
        p.PoiFile.model_validate(data)
