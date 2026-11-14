"""Tests für die Wanted-Regeln: Boden, Abklingen, Level-/Einheiten-Clamp, player_radio.

Gemini wird nie live aufgerufen (fake_gemini, tests/fakes.py).
"""

import asyncio

import config
import game_state
import hub as hub_module
import protocol
import runner
from agents import police
from protocol import AgentSnapshot, Envelope, PlaceRef, SnapshotPlayer
from tests.fakes import call_response


class FakeClock:
    """Monotone Uhr, die der Test vorstellt."""

    def __init__(self) -> None:
        """Start bei t = 1000 s."""
        self.t = 1000.0

    def __call__(self) -> float:
        """Aktuelle Fake-Zeit."""
        return self.t


def _setup():
    """Hub + GameState mit Fake-Uhr, gesendete Aktionen in sent."""
    hub = hub_module.Hub()
    clock = FakeClock()
    state = game_state.GameState(clock=clock)
    state.attach(hub)
    sent: list[Envelope] = []
    hub.on_action("*", lambda model, env: sent.append(env))
    return hub, state, clock, sent


def _publish(hub, type_, **payload):
    """Ein Client-Event über den Hub schicken."""
    asyncio.run(hub.publish_event(protocol.make_event(type_, payload)))


SHOT = {"x": 0.0, "z": 0.0, "shots": 3, "weapon": "pistol"}
CIV = {"npc_kind": "civilian", "x": 0.0, "z": 0.0}


def _snap(level=1, floor=1, units=0, by_type=None, kills=0, crime_s=5.0, radio=None):
    """Snapshot mit extras.wanted (und optional player_radio)."""
    extras = {
        "wanted": {
            "level": level,
            "floor": floor,
            "crime_s_ago": crime_s,
            "police_kills": kills,
            "units_by_type": by_type or {},
        }
    }
    if radio:
        extras["player_radio"] = radio
    return AgentSnapshot(
        agent="police",
        t="2026-11-14T14:00:00Z",
        player=SnapshotPlayer(x=0.0, z=0.0, zone_id="marktplatz"),
        wanted_level=level,
        units_active=units,
        places=[PlaceRef(id="marktplatz", name="Marktplatz")],
        extras=extras,
    )


def _d(type_, **payload):
    """Entwurf einer Aktion."""
    return Envelope(type=type_, ts=0, payload=payload)


def _levels(actions):
    """Gesendete Level aus einer Aktionsliste."""
    return [a.payload["level"] for a in actions if a.type == "set_wanted_level"]


# ---------------------------------------------------------------- Boden
def test_floor_rules():
    hub, state, _clock, sent = _setup()
    _publish(hub, "shot_fired", **SHOT)
    assert state.floor() == 1 and state.wanted_level == 1
    _publish(hub, "vehicle_stolen", vehicle_id="c", vehicle_kind="civilian", x=0, z=0)
    assert state.floor() == 2 and state.wanted_level == 2
    _publish(hub, "police_hit", unit_id="f1")
    assert state.floor() == 3 and state.wanted_level == 3
    _publish(hub, "police_killed", unit_id="f1")
    assert state.floor() == 4 and state.wanted_level == 4
    _publish(hub, "police_killed", unit_id="f2")
    assert state.floor() == 4 and state.police_kills == 2  # Boden max 4
    assert all(e.payload["source"] == "rules" for e in sent)


def test_civilian_kills_raise_floor_within_60s():
    hub, state, clock, _sent = _setup()
    _publish(hub, "npc_killed", npc_id="p1", **CIV)
    assert state.floor() == 2
    clock.t += 10
    _publish(hub, "npc_killed", npc_id="p2", **CIV)
    assert state.floor() == 3
    clock.t += 61  # außerhalb des Fensters: zählt wie der erste
    _publish(hub, "npc_killed", npc_id="p3", **CIV)
    assert state.floor() == 3


def test_decay_lowers_level_and_floor_until_zero():
    hub, state, clock, _sent = _setup()
    _publish(hub, "police_hit", unit_id="f1")
    assert state.wanted_level == 3
    clock.t += config.WANTED_DECAY_S - 1
    assert asyncio.run(state.decay_tick()) is False
    clock.t += 1
    assert asyncio.run(state.decay_tick()) is True
    assert state.wanted_level == 2 and state.floor() == 2
    state.nearest_unit_m = 20.0  # Einheit klebt am Spieler: kein Abklingen
    clock.t += config.WANTED_DECAY_S
    assert asyncio.run(state.decay_tick()) is False
    state.nearest_unit_m = None
    for expected in (1, 0):
        clock.t += config.WANTED_DECAY_S
        assert asyncio.run(state.decay_tick()) is True
        assert state.wanted_level == expected
    assert state.floor() == 0 and state.police_kills == 0


# ---------------------------------------------------------------- Clamps
def test_level_clamp_floor_plus_one_and_five_only_on_escalation():
    up = [_d("set_wanted_level", level=5, reason="r", source="agent")]
    assert _levels(police.clamp(up, _snap(level=2, floor=2))) == [3]
    assert _levels(police.clamp(up, _snap(level=4, floor=4))) == []  # 4 bleibt
    assert _levels(police.clamp(up, _snap(level=4, floor=4, kills=2))) == [5]
    taunt = {"tone": "taunt", "text": "Fangt mich doch"}
    assert _levels(police.clamp(up, _snap(level=4, floor=4, radio=taunt))) == [5]
    down = [_d("set_wanted_level", level=0, reason="r")]
    assert _levels(police.clamp(down, _snap(level=3, floor=2))) == []


def test_unit_clamp_per_type_against_table_and_active():
    drafts = [
        _d("spawn_units", count=6, unit_type="foot", tactic="chase", reason="r"),
        _d("spawn_units", count=6, unit_type="swat", tactic="surround", reason="r"),
        _d("spawn_units", count=1, unit_type="tank", tactic="chase", reason="r"),
    ]
    out = police.clamp(drafts, _snap(level=3, floor=3, units=1, by_type={"foot": 1}))
    got = {a.payload["unit_type"]: a.payload["count"] for a in out}
    assert got == {"foot": 1, "swat": 2}  # kein Panzer unter 5 Sternen
    out = police.clamp(drafts, _snap(level=5, floor=4, kills=2))
    got = {a.payload["unit_type"]: a.payload["count"] for a in out}
    assert got == {"foot": 2, "swat": 3, "tank": 1}
    assert sum(got.values()) <= config.POLICE_MAX_UNITS


def test_fallback_follows_unit_table():
    snap = _snap(level=4, floor=4)
    out = police.clamp(police.fallback(snap), snap)
    got = {
        a.payload["unit_type"]: a.payload["count"]
        for a in out
        if a.type == "spawn_units"
    }
    assert got == {"foot": 2, "patrol": 4}


# ---------------------------------------------------------------- player_radio
def test_plead_rejected_when_crime_recent_but_radio_always_answered():
    radio = {"tone": "plead", "text": "Bitte nicht schießen"}
    down = [_d("set_wanted_level", level=1, reason="Suspect surrenders")]
    out = police.clamp(down, _snap(level=2, floor=1, crime_s=5.0, radio=radio))
    assert _levels(out) == []
    assert [a.type for a in out] == ["radio_message"]  # serverseitig ergänzt
    out = police.clamp(down, _snap(level=2, floor=1, crime_s=25.0, radio=radio))
    assert _levels(out) == [1]
    assert out[-1].type == "radio_message"
    out = police.clamp(
        [_d("set_wanted_level", level=0, reason="r")],
        _snap(level=2, floor=2, crime_s=25.0, radio=radio),
    )
    assert _levels(out) == []  # nie unter den Boden


def test_fallback_plead_no_effect_taunt_plus_one():
    plead = _snap(level=2, floor=2, crime_s=30.0, radio={"tone": "plead", "text": ""})
    out = police.clamp(police.fallback(plead), plead)
    assert _levels(out) == [] and out[-1].type == "radio_message"
    taunt = _snap(level=2, floor=2, radio={"tone": "taunt", "text": "Lahm!"})
    out = police.clamp(police.fallback(taunt), taunt)
    assert _levels(out) == [3] and out[-1].type == "radio_message"


def test_player_radio_agent_call_with_mock_adds_missing_radio(fake_gemini, monkeypatch):
    monkeypatch.setattr(config, "AGENTS_MODE", "live")
    client = fake_gemini(
        [call_response(("set_wanted_level", {"level": 3, "reason": "Taunt"}))]
    )
    snap = _snap(level=2, floor=2, radio={"tone": "taunt", "text": "Kommt doch"})
    spec = police.spec()
    spec.snapshot = lambda: snap
    hub = hub_module.Hub()
    sent: list[str] = []
    hub.on_action("*", lambda m, env: sent.append(env.type))
    asyncio.run(runner.AgentRunner(hub, spec).run_cycle())
    assert len(client.models.calls) == 1
    assert sent == ["set_wanted_level", "radio_message"]


def test_player_radio_triggers_cycle_with_cooldown(monkeypatch):
    monkeypatch.setattr(police, "PENDING_RADIO", {})
    monkeypatch.setattr(police, "_radio_state", {"last": None})
    clock = FakeClock()
    cycles: list[dict] = []

    class FakeRunner:
        """Zählt Zyklen und merkt sich den offenen Funkspruch."""

        async def run_cycle(self):
            """Einen Zyklus simulieren."""
            cycles.append(dict(police.PENDING_RADIO))
            return []

    handler = police.make_radio_handler(FakeRunner(), clock=clock)
    event = protocol.PlayerRadio(tone="taunt", text="Ihr kriegt mich nie")

    async def fire():
        """Handler aufrufen und offene Zyklus-Tasks abwarten."""
        await handler(event, Envelope(type="player_radio", ts=0))
        await asyncio.gather(*police.RADIO_TASKS)

    asyncio.run(fire())
    clock.t += config.POLICE_RADIO_COOLDOWN_S - 1
    asyncio.run(fire())  # innerhalb des Cooldowns: ignoriert
    assert len(cycles) == 1 and cycles[0]["tone"] == "taunt"
    clock.t += 1
    asyncio.run(fire())
    assert len(cycles) == 2
