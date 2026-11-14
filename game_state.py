"""Spielzustand: Wahrheit über Fahndung, Einheiten, Spielerposition und jüngste Events.

Zweck: Feature-Modul der Scheibe Polizei (Design.md, "Spielzustand"). Hält, was der
Server über das Spiel weiß, setzt den Regel-Boden der Fahndung und baut die
Agent-Snapshots (protocol.AgentSnapshot).
Use-Cases:
- Verbrechen (shot_fired, npc_killed, vehicle_stolen) heben Level 0 sofort auf 1 (rules)
- Decay: nach WANTED_DECAY_S ohne Verbrechen sinkt das Level um 1
- Einheitenbilanz: spawn_units minus getötete Polizisten, bei Level 0 ist sie 0
- snapshot(agent, memory) für den Polizei-Dispatcher, Snapshot-Provider "wanted"
- Reload im Browser: on_connect schickt das aktuelle set_wanted_level
- GET /debug/state (nur DEBUG_ENDPOINTS=1)

Das Level ändert sich nur über ausgehende set_wanted_level-Aktionen (on_action),
egal ob von den Regeln, vom Agenten oder vom Fallback. So bleibt eine Quelle der Wahrheit.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
import protocol
from hub import Hub
from protocol import AgentSnapshot, Envelope

log = logging.getLogger(__name__)
router = APIRouter()

CRIME_LABELS = {
    "shot_fired": "Shots fired",
    "npc_killed": "Person killed",
    "vehicle_stolen": "Vehicle theft",
}
COUNTED_TYPES = ("shot_fired", "npc_killed", "vehicle_stolen")
# Tote dieser Arten heben die Fahndung nicht selbst (die Schüsse davor tun es).
NON_CRIME_KILLS = ("gang", "quest_target")
EVENT_BUFFER_MAX = 50
EVENT_BUFFER_S = 120.0
SNAPSHOT_EVENTS_MAX = 12
DECAY_TICK_S = 1.0


def _now_iso() -> str:
    """UTC-Zeit als ISO 8601 ohne Millisekunden, mit 'Z'."""
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _event_detail(event: BaseModel) -> dict[str, Any]:
    """Die für Agenten relevanten Felder eines Events (klein halten, Snapshot < 2 KB)."""
    if isinstance(event, protocol.ShotFired):
        return {"shots": event.shots, "weapon": event.weapon}
    if isinstance(event, protocol.NpcKilled):
        return {"npc_kind": event.npc_kind}
    if isinstance(event, protocol.VehicleStolen):
        return {"vehicle_kind": event.vehicle_kind}
    return {}


class GameState:
    """Zustand eines Spiels. Ein Exemplar pro Server (STATE); Tests bauen eigene."""

    def __init__(
        self, hub: Hub | None = None, clock: Callable[[], float] = time.monotonic
    ):
        """Leeren Zustand anlegen. clock: monotone Uhr in Sekunden (Tests: Fake-Uhr)."""
        self.hub = hub
        self.clock = clock
        self.wanted_level = 0
        self.last_crime: float | None = None
        self.last_decay: float | None = None
        self.units_active = 0
        self.player: protocol.PlayerPosition | None = None
        self.zone_id: str | None = None
        self.events: deque[tuple[float, str, str | None, dict[str, Any]]] = deque(
            maxlen=EVENT_BUFFER_MAX
        )
        self._decay_task: asyncio.Task | None = None

    # ---------------------------------------------------------------- Registrierung
    def attach(self, hub: Hub) -> None:
        """Am Hub anmelden: alle Events, Aktions-Beobachter, on_connect, Provider."""
        self.hub = hub
        hub.on_event("*", self.on_event)
        hub.on_action("set_wanted_level", self.on_wanted_action)
        hub.on_action("spawn_units", self.on_spawn_action)
        hub.on_connect(self.connect_messages)
        hub.register_snapshot_provider("wanted", self.wanted_extra)

    # ---------------------------------------------------------------- Events
    async def on_event(self, event: BaseModel, env: Envelope) -> None:
        """Event aufnehmen: Position/Zone merken, puffern, Regel-Boden anwenden."""
        now = self.clock()
        if isinstance(event, protocol.PlayerPosition):
            self.player = event
            self.zone_id = event.zone_id
            return
        zone = getattr(event, "zone_id", None)
        if isinstance(event, protocol.ZoneEntered):
            self.zone_id = event.zone_id
        self.events.append((now, env.type, zone, _event_detail(event)))
        self._prune(now)
        if isinstance(event, protocol.NpcKilled) and event.npc_kind == "police":
            self.units_active = max(0, self.units_active - 1)
        if self.is_crime(event):
            await self.record_crime(env.type)

    @staticmethod
    def is_crime(event: BaseModel) -> bool:
        """True für Events, die den Regel-Boden auslösen."""
        if isinstance(event, protocol.NpcKilled):
            return event.npc_kind not in NON_CRIME_KILLS
        return isinstance(event, protocol.ShotFired | protocol.VehicleStolen)

    async def record_crime(self, event_type: str) -> None:
        """Verbrechen merken; bei Level 0 sofort Level 1 setzen (source rules)."""
        self.last_crime = self.clock()
        if self.wanted_level == 0 and self.hub is not None:
            label = CRIME_LABELS.get(event_type, "Crime reported")
            await self.hub.send_action(
                "set_wanted_level",
                {
                    "level": 1,
                    "source": "rules",
                    "reason": f"{label}, wanted level raised",
                },
            )

    def _prune(self, now: float) -> None:
        """Events älter als EVENT_BUFFER_S verwerfen."""
        while self.events and now - self.events[0][0] > EVENT_BUFFER_S:
            self.events.popleft()

    # ---------------------------------------------------------------- Aktionen
    def on_wanted_action(self, model: protocol.SetWantedLevel, env: Envelope) -> None:
        """Beobachter: jede ausgehende Fahndungsstufe übernehmen. Level 0 räumt Einheiten."""
        self.wanted_level = model.level
        if model.level == 0:
            self.units_active = 0

    def on_spawn_action(self, model: protocol.SpawnUnits, env: Envelope) -> None:
        """Beobachter: gespawnte Polizei-Einheiten zählen."""
        if model.faction == "police":
            self.units_active = min(
                config.POLICE_MAX_UNITS, self.units_active + model.count
            )

    # ---------------------------------------------------------------- Abfragen
    def floor(self) -> int:
        """Regel-Boden: 1, solange das letzte Verbrechen < WANTED_DECAY_S her ist, sonst 0."""
        if self.last_crime is None:
            return 0
        return 1 if self.clock() - self.last_crime < config.WANTED_DECAY_S else 0

    def counts(self, window_s: float = 60.0) -> dict[str, int]:
        """Anzahl der Verbrechens-Events je Typ in den letzten window_s Sekunden."""
        now = self.clock()
        counts = dict.fromkeys(COUNTED_TYPES, 0)
        for t, type_, _zone, _detail in self.events:
            if type_ in counts and now - t <= window_s:
                counts[type_] += 1
        return counts

    def deaths(self, window_s: float = 60.0) -> int:
        """Getötete NPCs (alle Arten) in den letzten window_s Sekunden."""
        return self.counts(window_s)["npc_killed"]

    def wanted_extra(self) -> dict[str, Any]:
        """Snapshot-Provider "wanted": Level, Boden, Sekunden seit dem letzten Verbrechen."""
        since = (
            None
            if self.last_crime is None
            else round(self.clock() - self.last_crime, 1)
        )
        return {"level": self.wanted_level, "floor": self.floor(), "crime_s_ago": since}

    def snapshot(self, agent: str, memory: list[str] | None = None) -> AgentSnapshot:
        """Kompakter Lagebericht für einen Agenten (Ziel < 2 KB)."""
        now = self.clock()
        self._prune(now)
        player = None
        if self.player is not None:
            player = protocol.SnapshotPlayer(
                x=round(self.player.x, 1),
                z=round(self.player.z, 1),
                zone_id=self.zone_id,
                in_vehicle=self.player.in_vehicle,
                speed=round(self.player.speed, 1),
            )
        recent = [
            protocol.SnapshotEvent(
                type=type_,
                s_ago=round(max(0.0, now - t), 1),
                zone_id=zone,
                detail=detail,
            )
            for t, type_, zone, detail in list(self.events)[-SNAPSHOT_EVENTS_MAX:]
        ]
        hub_extras = self.hub.snapshot_extras() if self.hub is not None else {}
        return AgentSnapshot(
            agent=agent,
            t=_now_iso(),
            player=player,
            wanted_level=self.wanted_level,
            units_active=self.units_active,
            units_max=config.POLICE_MAX_UNITS,
            recent_events=recent,
            counts_60s=self.counts(60.0),
            memory=list(memory or [])[-5:],
            places=places(),
            extras=hub_extras,
        )

    def connect_messages(self) -> list[Envelope]:
        """on_connect: aktuelles Level an einen neuen Client (Reload synchronisiert)."""
        return [
            protocol.make_action(
                "set_wanted_level",
                {"level": self.wanted_level, "source": "rules", "reason": "State sync"},
            )
        ]

    def debug_state(self) -> dict[str, Any]:
        """Zustand als dict für GET /debug/state."""
        return {
            "wanted": self.wanted_extra(),
            "units_active": self.units_active,
            "zone_id": self.zone_id,
            "player": self.player.model_dump() if self.player else None,
            "counts_60s": self.counts(60.0),
            "events": len(self.events),
        }

    # ---------------------------------------------------------------- Decay
    async def decay_tick(self) -> bool:
        """Einmal prüfen: WANTED_DECAY_S ohne Verbrechen (und seit dem letzten Decay) -> -1."""
        if self.wanted_level <= 0 or self.hub is None:
            return False
        now = self.clock()
        ref = max(
            (t for t in (self.last_crime, self.last_decay) if t is not None),
            default=None,
        )
        if ref is None:  # Level ohne bekanntes Verbrechen: ab jetzt zählen
            self.last_decay = now
            return False
        if now - ref < config.WANTED_DECAY_S:
            return False
        self.last_decay = now
        level = self.wanted_level - 1
        await self.hub.send_action(
            "set_wanted_level",
            {
                "level": level,
                "source": "rules",
                "reason": f"No crimes for {config.WANTED_DECAY_S:.0f} s, wanted level drops",
            },
        )
        return True

    async def _decay_loop(self) -> None:
        """Hintergrund-Task: decay_tick jede Sekunde."""
        while True:
            await asyncio.sleep(DECAY_TICK_S)
            try:
                await self.decay_tick()
            except Exception:
                log.exception("Decay fehlgeschlagen")

    def start(self) -> None:
        """Decay-Task starten (im laufenden Event-Loop)."""
        if self._decay_task is None or self._decay_task.done():
            self._decay_task = asyncio.get_running_loop().create_task(
                self._decay_loop()
            )

    async def stop(self) -> None:
        """Decay-Task beenden."""
        if self._decay_task is not None:
            self._decay_task.cancel()
            try:
                await self._decay_task
            except asyncio.CancelledError:
                pass
            self._decay_task = None


def places() -> list[protocol.PlaceRef]:
    """Alle POIs als (id, name) für den Agenten."""
    try:
        return [
            protocol.PlaceRef(id=p.id, name=p.name) for p in protocol.load_pois().pois
        ]
    except (OSError, ValueError):
        log.exception("POIs nicht ladbar")
        return []


STATE: GameState = GameState()


def register(hub: Hub) -> None:
    """Feature-Einstieg: frischen Zustand anlegen und am Hub anmelden."""
    global STATE
    STATE = GameState(hub)
    STATE.attach(hub)


async def startup() -> None:
    """Lifespan: Decay-Task starten."""
    STATE.start()


async def shutdown() -> None:
    """Lifespan: Decay-Task stoppen."""
    await STATE.stop()


@router.get("/debug/state", include_in_schema=False)
def debug_state() -> dict:
    """Aktueller Spielzustand. 404 ohne DEBUG_ENDPOINTS=1."""
    if not config.DEBUG_ENDPOINTS:
        raise HTTPException(404, "Not Found")
    return STATE.debug_state()
