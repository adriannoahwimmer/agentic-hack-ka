"""Tests für runner.py: Sammelfenster, Mindestabstand, Deadline, offline, veraltete Ergebnisse."""

import asyncio

import config
import hub as hub_module
import protocol
import runner
from protocol import AgentSnapshot


def _snapshot():
    return AgentSnapshot(agent="test", t="2026-11-14T14:00:00Z")


def _radio(text):
    return protocol.make_action("radio_message", protocol.make_radio_message(text))


def _spec(decide=None, **kw):
    async def _decide(snapshot):
        return [_radio("agent call")]

    return runner.AgentSpec(
        name="test",
        triggers={"shot_fired"},
        min_interval_s=kw.pop("min_interval_s", 0),
        decide=decide or _decide,
        fallback=lambda snapshot: [_radio("fallback call")],
        clamp=lambda drafts, snapshot: drafts,
        snapshot=_snapshot,
        **kw,
    )


def _runner(spec, **kw):
    hub = hub_module.Hub()
    sent = []
    hub.on_action("*", lambda model, env: sent.append(env))
    return runner.AgentRunner(hub, spec, **kw), sent


SHOT = protocol.make_event(
    "shot_fired", {"x": 0, "z": 0, "shots": 1, "weapon": "pistol"}
)


def test_debounce_bundles_ten_events_into_one_cycle(monkeypatch):
    monkeypatch.setattr(config, "AGENT_DEBOUNCE_S", 0.01)
    r, sent = _runner(_spec())

    async def scenario():
        for _ in range(10):
            r.on_event(None, SHOT)
        await r._window

    asyncio.run(scenario())
    assert r.cycles == 1
    assert [e.payload["text"] for e in sent] == ["fallback call"]  # offline


def test_min_interval_waits_since_last_cycle(monkeypatch):
    monkeypatch.setattr(config, "AGENT_DEBOUNCE_S", 5.0)
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    clock = [100.0]
    r, _sent = _runner(
        _spec(min_interval_s=8), clock=lambda: clock[0], sleep=fake_sleep
    )

    async def scenario():
        r.on_event(None, SHOT)
        await r._window
        clock[0] += 6  # 5 s Fenster + 1 s: 2 s fehlen zum Mindestabstand
        r.on_event(None, SHOT)
        await r._window

    asyncio.run(scenario())
    assert waits == [5.0, 5.0, 2.0]
    assert r.cycles == 2


def test_deadline_leads_to_fallback_and_is_logged(monkeypatch, genai_log_lines):
    monkeypatch.setattr(config, "AGENTS_MODE", "live")
    monkeypatch.setattr(config, "AGENT_DEADLINE_MS", 20)

    async def slow(snapshot):
        await asyncio.sleep(1)
        return [_radio("too late")]

    r, sent = _runner(_spec(decide=slow))
    asyncio.run(r.run_cycle())
    assert [e.payload["text"] for e in sent] == ["fallback call"]
    lines = genai_log_lines()
    assert [(line["kind"], line["agent"]) for line in lines] == [("fallback", "test")]
    assert "timeout" in lines[0]["reason"]


def test_offline_uses_fallback_without_calling_decide():
    async def forbidden(snapshot):
        raise AssertionError("decide darf offline nicht laufen")

    r, sent = _runner(_spec(decide=forbidden))
    asyncio.run(r.run_cycle())
    assert [e.payload["text"] for e in sent] == ["fallback call"]


def test_live_agent_result_is_sent(monkeypatch):
    monkeypatch.setattr(config, "AGENTS_MODE", "live")
    r, sent = _runner(_spec())
    asyncio.run(r.run_cycle())
    assert [e.payload["text"] for e in sent] == ["agent call"]


def test_late_result_after_reset_is_discarded(monkeypatch):
    monkeypatch.setattr(config, "AGENTS_MODE", "live")

    async def scenario():
        gate = asyncio.Event()

        async def waiting(snapshot):
            await gate.wait()
            return [_radio("stale")]

        r, sent = _runner(_spec(decide=waiting))
        task = asyncio.create_task(r.run_cycle())
        await asyncio.sleep(0)
        r.invalidate()  # z. B. Level 0 durch die Regeln
        gate.set()
        return await task, sent

    result, sent = asyncio.run(scenario())
    assert result == [] and sent == []


def test_rules_level_zero_invalidates_registered_runners(monkeypatch):
    hub = hub_module.Hub()
    monkeypatch.setattr(runner, "RUNNERS", {})
    runner.register(hub)
    r = runner.register_agent(_spec(), hub)
    before = r.generation
    asyncio.run(
        hub.send_action(
            "set_wanted_level", {"level": 0, "source": "rules", "reason": "decay"}
        )
    )
    assert r.generation == before + 1
