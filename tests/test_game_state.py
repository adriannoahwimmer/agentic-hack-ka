"""Tests für game_state.py: Regel-Boden, Decay mit Fake-Uhr, Einheitenbilanz, Snapshot-Größe."""

import asyncio

import config
import game_state
import hub as hub_module
import protocol


class FakeClock:
    """Monotone Uhr, die der Test vorstellt."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _setup():
    hub = hub_module.Hub()
    clock = FakeClock()
    state = game_state.GameState(clock=clock)
    state.attach(hub)
    sent = []
    hub.on_action("*", lambda model, env: sent.append(env))
    return hub, state, clock, sent


def _publish(hub, type_, **payload):
    env = protocol.make_event(type_, payload)
    asyncio.run(hub.publish_event(env))


SHOT = {"x": 0.0, "z": 0.0, "shots": 3, "weapon": "pistol", "zone_id": "marktplatz"}


def test_crime_raises_level_0_to_1_immediately():
    hub, state, _clock, sent = _setup()
    _publish(hub, "shot_fired", **SHOT)
    assert state.wanted_level == 1
    assert [(e.type, e.payload["level"], e.payload["source"]) for e in sent] == [
        ("set_wanted_level", 1, "rules")
    ]
    _publish(hub, "shot_fired", **SHOT)  # Level >= 1: nur last_crime, keine neue Aktion
    assert len(sent) == 1


def test_quest_target_kill_is_no_crime_but_counts():
    hub, state, _clock, sent = _setup()
    kill = {"npc_id": "q1", "npc_kind": "quest_target", "x": 0.0, "z": 0.0}
    _publish(hub, "npc_killed", **kill)
    assert state.wanted_level == 0 and sent == []
    assert state.counts()["npc_killed"] == 1


def test_decay_drops_one_level_per_window_and_clears_units():
    hub, state, clock, sent = _setup()
    _publish(
        hub, "vehicle_stolen", vehicle_id="c1", vehicle_kind="civilian", x=0.0, z=0.0
    )
    asyncio.run(
        hub.send_action(
            "spawn_units",
            {
                "wave_id": "w-1",
                "faction": "police",
                "count": 2,
                "unit_type": "patrol",
                "tactic": "chase",
            },
        )
    )
    asyncio.run(
        hub.send_action(
            "set_wanted_level", {"level": 2, "source": "agent", "reason": "x"}
        )
    )
    assert state.units_active == 2
    clock.t += config.WANTED_DECAY_S - 1
    assert asyncio.run(state.decay_tick()) is False
    assert state.floor() == 1
    clock.t += 1
    assert asyncio.run(state.decay_tick()) is True
    assert state.wanted_level == 1 and state.floor() == 0
    assert asyncio.run(state.decay_tick()) is False  # neues Fenster ab dem Decay
    clock.t += config.WANTED_DECAY_S
    assert asyncio.run(state.decay_tick()) is True
    assert state.wanted_level == 0 and state.units_active == 0
    assert sent[-1].payload["source"] == "rules"


def test_unit_balance_counts_spawns_minus_killed_police():
    hub, state, _clock, _sent = _setup()
    _publish(hub, "shot_fired", **SHOT)
    asyncio.run(
        hub.send_action(
            "spawn_units",
            {
                "wave_id": "w-1",
                "faction": "police",
                "count": 3,
                "unit_type": "patrol",
                "tactic": "chase",
            },
        )
    )
    _publish(hub, "npc_killed", npc_id="cop-1", npc_kind="police", x=0.0, z=0.0)
    assert state.units_active == 2


def test_snapshot_is_small_and_has_extras_and_places():
    hub, state, _clock, _sent = _setup()
    _publish(
        hub,
        "player_position",
        x=-35.0,
        z=506.0,
        heading=0.0,
        speed=1.2,
        in_vehicle=False,
        zone_id="marktplatz",
    )
    for i in range(60):
        _publish(hub, "shot_fired", **{**SHOT, "shots": 1 + i % 50})
        _publish(
            hub,
            "npc_killed",
            npc_id=f"ped-{i}",
            npc_kind="civilian",
            x=0.0,
            z=0.0,
            zone_id="marktplatz",
        )
    snap = state.snapshot("police", [f"line {i}" for i in range(8)])
    text = snap.to_prompt()
    assert len(text.encode()) < 2048, len(text)
    assert len(snap.recent_events) == 12 and len(snap.memory) == 5
    assert snap.extras["wanted"]["floor"] == 1
    assert any(p.id == "marktplatz" for p in snap.places)
    assert snap.player.zone_id == "marktplatz"


def test_connect_message_syncs_level():
    hub, _state, _clock, _sent = _setup()
    _publish(hub, "shot_fired", **SHOT)
    messages = asyncio.run(hub.connect_messages())
    assert [(m.type, m.payload["level"]) for m in messages] == [("set_wanted_level", 1)]
