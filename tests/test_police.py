"""Tests für agents/police.py: Clamps, parallele Calls, 1 Request pro Zyklus, E2E über WebSocket."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import config
import game_state
import hub as hub_module
import main
import runner
from agents import police
from protocol import AgentSnapshot, Envelope, PlaceRef, SnapshotPlayer
from tests.fakes import call_response, text_response


def _snap(level=1, units=0, floor=1, deaths=0, zone="marktplatz"):
    return AgentSnapshot(
        agent="police",
        t="2026-11-14T14:00:00Z",
        player=SnapshotPlayer(x=-35.0, z=506.0, zone_id=zone),
        wanted_level=level,
        units_active=units,
        counts_60s={"shot_fired": 2, "npc_killed": deaths, "vehicle_stolen": 0},
        places=[
            PlaceRef(id="marktplatz", name="Market Square"),
            PlaceRef(id="schloss", name="Karlsruhe Palace"),
        ],
        extras={"wanted": {"level": level, "floor": floor}},
    )


def _d(type_, **payload):
    return Envelope(type=type_, ts=0, payload=payload)


def _by_type(actions):
    return {a.type: a.payload for a in actions}


def test_clamp_level_step_and_floor():
    out = _by_type(
        police.clamp(
            [_d("set_wanted_level", level=5, reason="r", source="agent")],
            _snap(level=1),
        )
    )
    assert out["set_wanted_level"]["level"] == 2  # höchstens Boden + 1
    # Senken ohne plead wird verworfen
    assert (
        police.clamp(
            [_d("set_wanted_level", level=0, reason="r")], _snap(level=2, floor=1)
        )
        == []
    )
    assert (
        police.clamp([_d("set_wanted_level", level=1, reason="r")], _snap(level=1))
        == []
    )


def test_clamp_units_enums_places_and_radio():
    drafts = [
        _d(
            "spawn_units",
            target_units=9,
            unit_type="rocket",
            tactic="nuke",
            near_place_id="mars",
            reason="r",
        ),
        _d("radio_message", text="   ", reason="r"),
        _d("teleport", x=1),
    ]
    out = _by_type(police.clamp(drafts, _snap(level=4, floor=4, units=0)))
    assert out["spawn_units"]["count"] == 4  # patrol-Kontingent bei 4 Sternen
    assert (
        out["spawn_units"]["unit_type"] == "patrol"
        and out["spawn_units"]["tactic"] == "chase"
    )
    assert out["spawn_units"]["near_poi_id"] is None
    assert set(out) == {"spawn_units"}
    out = _by_type(
        police.clamp(
            [
                _d(
                    "spawn_units",
                    target_units=9,
                    unit_type="swat",
                    tactic="surround",
                    near_place_id="schloss",
                    reason="r",
                )
            ],
            _snap(level=4, floor=4, units=2),
        )
    )
    assert (
        out["spawn_units"]["count"] == 4
        and out["spawn_units"]["near_poi_id"] == "schloss"
    )
    assert (
        police.clamp(
            [
                _d(
                    "spawn_units",
                    target_units=2,
                    unit_type="patrol",
                    tactic="chase",
                    reason="r",
                )
            ],
            _snap(units=2),
        )
        == []
    )
    long_text = "Unit " * 100
    out = _by_type(
        police.clamp([_d("radio_message", text=long_text, reason="r")], _snap())
    )
    assert len(out["radio_message"]["text"]) <= config.RADIO_MAX_CHARS


def test_clamp_keeps_only_first_call_per_tool():
    drafts = [
        _d("radio_message", text="first", reason="r"),
        _d("radio_message", text="second", reason="r"),
    ]
    out = police.clamp(drafts, _snap())
    assert [a.payload["text"] for a in out] == ["first"]


def test_fallback_is_deterministic_and_valid():
    snap = _snap(level=1, floor=2, deaths=2)
    actions = police.clamp(police.fallback(snap), snap)
    out = _by_type(actions)
    assert out["set_wanted_level"] == {
        "level": 2,
        "source": "fallback",
        "reason": out["set_wanted_level"]["reason"],
    }
    spawns = {
        a.payload["unit_type"]: a.payload for a in actions if a.type == "spawn_units"
    }
    assert {k: v["count"] for k, v in spawns.items()} == {"foot": 1, "patrol": 1}
    assert spawns["patrol"]["near_poi_id"] == "marktplatz"
    assert "Market Square" in out["radio_message"]["text"]
    assert police.fallback(_snap(level=0, floor=0)) == []


def test_three_parallel_calls_give_three_actions_with_one_request(
    fake_gemini, monkeypatch
):
    monkeypatch.setattr(config, "AGENTS_MODE", "live")
    client = fake_gemini(
        [
            call_response(
                ("set_wanted_level", {"level": 3, "reason": "Two civilians down"}),
                (
                    "spawn_units",
                    {
                        "target_units": 3,
                        "unit_type": "patrol",
                        "tactic": "roadblock",
                        "near_place_id": "marktplatz",
                        "reason": "Block the square",
                    },
                ),
                (
                    "radio_message",
                    {
                        "text": "All units to Market Square, shots fired.",
                        "reason": "Inform units",
                    },
                ),
            )
        ]
    )
    drafts = asyncio.run(police.decide(_snap(level=1)))
    out = police.clamp(drafts, _snap(level=1))
    assert [a.type for a in out] == ["set_wanted_level", "spawn_units", "radio_message"]
    assert out[0].payload["source"] == "agent"
    assert len(client.models.calls) == 1
    cfg = client.models.calls[0]["config"]
    assert cfg.tool_config.function_calling_config.mode.value == "ANY"


def test_one_request_per_cycle_and_empty_answer_falls_back(
    fake_gemini, monkeypatch, genai_log_lines
):
    monkeypatch.setattr(config, "AGENTS_MODE", "live")
    client = fake_gemini([text_response("I cannot help")])
    hub = hub_module.Hub()
    sent = []
    hub.on_action("*", lambda m, env: sent.append(env.type))
    spec = police.spec()
    spec.snapshot = lambda: _snap(level=1)
    r = runner.AgentRunner(hub, spec)
    asyncio.run(r.run_cycle())
    assert len(client.models.calls) == 1
    assert sent == [
        "spawn_units",
        "radio_message",
    ]  # Level 1 bleibt, also kein set_wanted_level
    assert [line["kind"] for line in genai_log_lines()] == ["genai", "fallback"]


def test_offline_makes_zero_requests(fake_gemini):
    client = fake_gemini([])
    hub = hub_module.Hub()
    spec = police.spec()
    spec.snapshot = lambda: _snap(level=1, deaths=1)
    asyncio.run(runner.AgentRunner(hub, spec).run_cycle())
    assert client.models.calls == []


@pytest.fixture
def police_app(fresh_hub, monkeypatch):
    """App mit frischem Hub, auf dem Zustand, Runner und Dispatcher registriert sind."""
    monkeypatch.setattr(config, "AGENT_DEBOUNCE_S", 0)
    monkeypatch.setattr(runner, "RUNNERS", {})
    monkeypatch.setattr(game_state, "STATE", game_state.STATE)
    game_state.register(fresh_hub)
    runner.register(fresh_hub)
    police.register(fresh_hub)
    with TestClient(main.app) as client:
        yield client


def test_e2e_npc_killed_leads_to_level_units_and_radio(police_app):
    kill = {
        "type": "npc_killed",
        "ts": 1,
        "payload": {
            "npc_id": "ped-1",
            "npc_kind": "civilian",
            "x": -35.0,
            "z": 506.0,
            "zone_id": "marktplatz",
        },
    }
    with police_app.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "set_wanted_level"  # Sync beim Verbinden
        ws.send_text(json.dumps(kill))
        seen = []
        while not {"spawn_units", "radio_message"} <= {m["type"] for m in seen}:
            seen.append(ws.receive_json())
    levels = [
        (m["payload"]["level"], m["payload"]["source"])
        for m in seen
        if m["type"] == "set_wanted_level"
    ]
    assert levels == [(2, "rules")]  # Zivilist getötet: Boden 2 sofort
