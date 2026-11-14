"""Agent-Runner: wann ein Spiel-Agent entscheidet und was passiert, wenn er es nicht tut.

Zweck: Feature-Modul der Scheibe Polizei (Design.md, "Agent-Runner"). Bündelt
Trigger-Events, hält Mindestabstände ein, ruft decide() mit Deadline auf und greift
bei Timeout, Fehler, AGENTS_MODE=offline oder erschöpftem Budget auf den
geskripteten Fallback zurück. Danach clamp() und send_action().
Use-Cases:
- agents/police.py registriert den Dispatcher per register_agent(AgentSpec(...))
- Tests: Uhr und sleep injizierbar, run_cycle() direkt aufrufbar

Ablauf pro Zyklus: Trigger -> Sammelfenster AGENT_DEBOUNCE_S -> Mindestabstand
min_interval_s -> höchstens ein Call pro Agent -> decide (wait_for AGENT_DEADLINE_MS)
oder fallback -> clamp -> send_action. Ein Generationszähler verwirft Ergebnisse,
die nach einem Reset (Level 0 durch die Regeln) ankommen.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import BaseModel

import config
import gemini
import genai_log
import protocol
from hub import Hub
from protocol import AgentSnapshot, Envelope

log = logging.getLogger(__name__)

Decide = Callable[[AgentSnapshot], Awaitable[list[Envelope]]]
Fallback = Callable[[AgentSnapshot], list[Envelope]]
Clamp = Callable[[list[Envelope], AgentSnapshot], list[Envelope]]


@dataclass
class AgentSpec:
    """Beschreibung eines Spiel-Agenten für den Runner.

    - triggers: Event-Typen, die ein Sammelfenster öffnen
    - decide: async snapshot -> Entwürfe (ruft Gemini); fallback: snapshot -> Entwürfe
    - clamp: (Entwürfe, snapshot) -> gültige Aktionen (Envelopes mit Vertrags-Payload)
    - snapshot: baut den aktuellen Lagebericht
    - trigger_filter: optional (event, env) -> bool, z. B. zone_entered nur ab Level 1
    - on_sent: optional (gesendete Aktionen, source "agent"|"fallback"), z. B. Gedächtnis
    """

    name: str
    triggers: set[str]
    min_interval_s: float
    decide: Decide
    fallback: Fallback
    clamp: Clamp
    snapshot: Callable[[], AgentSnapshot]
    trigger_filter: Callable[[BaseModel, Envelope], bool] | None = None
    on_sent: Callable[[list[Envelope], str], None] | None = None


class AgentRunner:
    """Steuert die Zyklen eines Agenten. Ein Exemplar pro AgentSpec."""

    def __init__(
        self,
        hub: Hub,
        spec: AgentSpec,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Runner an Hub und Spec binden. clock/sleep für Tests ersetzbar."""
        self.hub = hub
        self.spec = spec
        self.clock = clock
        self.sleep = sleep
        self.generation = 0
        self.cycles = 0
        self.last_cycle_start: float | None = None
        self._window: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- Trigger
    def on_event(self, event: BaseModel, env: Envelope) -> None:
        """Hub-Handler: Trigger-Event öffnet ein Sammelfenster (wenn keins offen ist)."""
        if env.type not in self.spec.triggers:
            return
        if self.spec.trigger_filter is not None and not self.spec.trigger_filter(
            event, env
        ):
            return
        if self._window is not None and not self._window.done():
            return  # Fenster offen: das Event landet ohnehin im Snapshot
        self._window = asyncio.get_running_loop().create_task(self._window_then_cycle())

    async def _window_then_cycle(self) -> None:
        """Sammelfenster abwarten, Mindestabstand einhalten, dann einen Zyklus fahren."""
        try:
            await self.sleep(config.AGENT_DEBOUNCE_S)
            if self.last_cycle_start is not None:
                wait = self.spec.min_interval_s - (self.clock() - self.last_cycle_start)
                if wait > 0:
                    await self.sleep(wait)
            await self.run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Agent-Zyklus %s fehlgeschlagen", self.spec.name)

    def invalidate(self) -> None:
        """Laufende Entscheidungen verwerfen (Generationszähler hochzählen)."""
        self.generation += 1

    # ---------------------------------------------------------------- Zyklus
    async def run_cycle(self) -> list[Envelope]:
        """Ein Zyklus: decide oder fallback, clamp, senden. Gibt die gesendeten Aktionen zurück."""
        async with self._lock:  # höchstens ein Call pro Agent
            self.last_cycle_start = self.clock()
            self.cycles += 1
            generation = self.generation
            snapshot = self.spec.snapshot()
            drafts, source, why = await self._decide(snapshot)
            if generation != self.generation:
                log.info("Agent %s: Ergebnis verworfen (veraltet)", self.spec.name)
                return []
            actions = self.spec.clamp(drafts, snapshot)
            if source == "agent" and not actions:
                # Modell lieferte nichts Brauchbares: lieber der Fallback als Stille
                drafts, source, why = self.spec.fallback(snapshot), "fallback", "empty"
                actions = self.spec.clamp(drafts, snapshot)
            if source == "fallback":
                genai_log.log_fallback(
                    agent=self.spec.name,
                    actions=[{"tool": a.type, "args": a.payload} for a in actions],
                    reason=f"fallback ({why}): {_reason(actions)}"[:300],
                )
            sent = []
            for action in actions:
                try:
                    sent.append(await self.hub.send_action(action.type, action.payload))
                except protocol.ProtocolError:
                    log.exception(
                        "Agent %s: ungültige Aktion verworfen", self.spec.name
                    )
            if self.spec.on_sent is not None:
                try:
                    self.spec.on_sent(sent, source)
                except Exception:
                    log.exception("on_sent von %s fehlgeschlagen", self.spec.name)
            return sent

    async def _decide(self, snapshot: AgentSnapshot) -> tuple[list[Envelope], str, str]:
        """decide mit Deadline, sonst fallback. -> (Entwürfe, source, Grund)."""
        if not gemini.live_enabled():
            return self.spec.fallback(snapshot), "fallback", "offline"
        try:
            drafts = await asyncio.wait_for(
                self.spec.decide(snapshot), timeout=config.AGENT_DEADLINE_MS / 1000
            )
            return drafts, "agent", ""
        except asyncio.TimeoutError:
            why = "timeout"
        except HTTPException as e:
            why = f"http {e.status_code}"
        except Exception as e:  # jeder Agentenfehler -> Fallback
            log.exception("Agent %s: decide fehlgeschlagen", self.spec.name)
            why = type(e).__name__
        return self.spec.fallback(snapshot), "fallback", why

    async def stop(self) -> None:
        """Offenes Sammelfenster abbrechen."""
        if self._window is not None and not self._window.done():
            self._window.cancel()
            try:
                await self._window
            except asyncio.CancelledError:
                pass
        self._window = None


def _reason(actions: list[Envelope]) -> str:
    """Begründungszeile aus den Aktionen (erste reason, sonst die Typen)."""
    for action in actions:
        reason = action.payload.get("reason")
        if reason:
            return str(reason)
    return ", ".join(a.type for a in actions) or "no action"


# ---------------------------------------------------------------- Modul-API
_HUB: Hub | None = None
RUNNERS: dict[str, AgentRunner] = {}


def register(hub: Hub) -> None:
    """Feature-Einstieg: Hub merken, Runner leeren, Level-0-Reset beobachten."""
    global _HUB
    _HUB = hub
    RUNNERS.clear()
    hub.on_action("set_wanted_level", _on_wanted)


def _on_wanted(model: protocol.SetWantedLevel, env: Envelope) -> None:
    """Level 0 durch die Regeln: laufende Entscheidungen aller Agenten verwerfen."""
    if model.level == 0 and model.source == "rules":
        for runner in RUNNERS.values():
            runner.invalidate()


def register_agent(spec: AgentSpec, hub: Hub | None = None) -> AgentRunner:
    """Agenten anmelden: Runner bauen und für seine Trigger-Events abonnieren."""
    hub = hub or _HUB
    if hub is None:
        raise RuntimeError("runner.register(hub) muss vor register_agent laufen")
    runner = AgentRunner(hub, spec)
    RUNNERS[spec.name] = runner
    for event_type in sorted(spec.triggers):
        hub.on_event(event_type, runner.on_event)
    return runner


async def shutdown() -> None:
    """Lifespan: offene Sammelfenster aller Runner abbrechen."""
    for runner in RUNNERS.values():
        await runner.stop()
