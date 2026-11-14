"""Quest-Wahrheit: aktive Quest, Prüfung per Spielerposition und Kills (Scheibe Quest).

Zweck: Der Server entscheidet, ob eine Quest erreicht und erfüllt ist, nicht der Client
und nicht das Modell. Der Quest-Agent (agents/quest.py) legt Quests nur über
QuestBook.create an; Ziele kommen ausschließlich aus data/pois.json.
Use-Cases:
- player_position im Radius des Ziel-POI -> quest_update target_reached (Client spawnt Gegner)
- npc_killed (quest_target, passende quest_id) -> remaining sinkt, bei 0 completed
- Reconnect: on_connect schickt die aktive Quest nach
- Polizei-Snapshot: Provider "quest" liefert {title, poi_id, status}
- fallback_quest: geskriptete Quest, wenn Gemini offline, zu langsam oder kaputt ist
"""

import itertools
import logging
import math
import random
from dataclasses import dataclass

import config
import protocol
from protocol import Envelope, NpcKilled, PlayerPosition, Poi, QuestUpdate, Target

log = logging.getLogger(__name__)

TITLE_TEMPLATES = (
    "Trouble at {name}",
    "Clean-up at {name}",
    "Hot Spot: {name}",
    "Unfinished Business at {name}",
)
OBJECTIVE_TEMPLATE = "Go to {name} and take out {n} rival smugglers"
# Behörden und Gerichte sind nie Quest-Ziel (Gegner sind immer eine Gang/Schmuggler-Crew,
# nie echte Personen, Beamte, Richter oder Institutionen).
NO_QUEST_POIS = frozenset({"verfassungsgericht", "bundesgerichtshof", "rathaus"})


class QuestError(ValueError):
    """Quest kann nicht angelegt werden (unbekannter POI, schon eine Quest aktiv)."""


@dataclass
class Quest:
    """Eine Quest mit Zustand. Wird nur vom QuestBook verändert."""

    quest_id: str
    title: str
    objective: str
    poi: Poi
    enemies: int
    status: str = "active"
    remaining: int = 0

    def update(self, spawn_targets: int = 0) -> QuestUpdate:
        """quest_update-Payload für den aktuellen Zustand."""
        return QuestUpdate(
            quest_id=self.quest_id,
            status=self.status,
            title=self.title,
            objective=self.objective,
            poi_id=self.poi.id,
            target=Target(x=self.poi.x, z=self.poi.z, radius=self.poi.radius),
            spawn_targets=spawn_targets,
            remaining=self.remaining,
        )


def _clip(text: str, limit: int) -> str:
    """Whitespace normalisieren und auf limit Zeichen kürzen."""
    return " ".join(str(text).split())[:limit]


def clamp_enemies(enemies) -> int:
    """Gegnerzahl auf 1..QUEST_MAX_TARGETS begrenzen (auch bei Müll vom Modell)."""
    try:
        n = int(enemies)
    except (TypeError, ValueError):
        n = 3
    return max(1, min(config.QUEST_MAX_TARGETS, n))


def mission_pois() -> list[Poi]:
    """Alle POIs mit Tag mission ohne Behörden (NO_QUEST_POIS): die einzigen erlaubten Quest-Ziele."""
    return [
        p
        for p in protocol.load_pois().pois
        if "mission" in p.tags and p.id not in NO_QUEST_POIS
    ]


class QuestBook:
    """Eine aktive Quest plus Historie. Ein Exemplar pro Server (BOOK); Tests bauen eigene."""

    def __init__(self) -> None:
        """Leeres Buch ohne aktive Quest."""
        self.active: Quest | None = None
        self.history: list[Quest] = []
        self._ids = itertools.count(1)

    def create(self, poi_id: str, title: str, objective: str, enemies) -> QuestUpdate:
        """Quest zu einem mission-POI anlegen. Wirft QuestError bei ungültiger Anfrage."""
        if self.active is not None:
            raise QuestError(
                f"quest {self.active.quest_id} is still active: {self.active.objective}"
            )
        poi = protocol.load_pois().get(str(poi_id))
        if poi is None or "mission" not in poi.tags or poi.id in NO_QUEST_POIS:
            valid = ", ".join(p.id for p in mission_pois())
            raise QuestError(f"unknown place_id {poi_id!r}; valid: {valid}")
        n = clamp_enemies(enemies)
        quest = Quest(
            quest_id=f"q-{next(self._ids)}",
            title=_clip(title, 80) or TITLE_TEMPLATES[0].format(name=poi.name),
            objective=_clip(objective, 200)
            or OBJECTIVE_TEMPLATE.format(name=poi.name, n=n),
            poi=poi,
            enemies=n,
            remaining=n,
        )
        self.active = quest
        return quest.update()

    def current(self) -> QuestUpdate | None:
        """Aktive Quest als quest_update (für Reconnect: Gegner neu spawnen)."""
        q = self.active
        if q is None:
            return None
        spawn = q.remaining if q.status == "target_reached" else 0
        return q.update(spawn_targets=spawn)

    def on_position(self, x: float, z: float) -> QuestUpdate | None:
        """Spielerposition prüfen. Im Radius: target_reached mit allen Gegnern."""
        q = self.active
        if q is None or q.status != "active":
            return None
        if math.hypot(x - q.poi.x, z - q.poi.z) > q.poi.radius:
            return None
        q.status = "target_reached"
        q.remaining = q.enemies
        return q.update(spawn_targets=q.enemies)

    def on_kill(self, npc_kind: str, quest_id: str | None) -> QuestUpdate | None:
        """Kill zählen, wenn er ein Quest-Ziel der aktiven Quest war. Bei 0: completed."""
        q = self.active
        if q is None or npc_kind != "quest_target" or quest_id != q.quest_id:
            return None
        q.remaining = max(0, q.remaining - 1)
        if q.remaining == 0:
            q.status = "completed"
            self.history.append(q)
            self.active = None
        return q.update()

    def snapshot(self) -> dict | None:
        """Extra für Agent-Snapshots: {title, poi_id, status} oder None."""
        q = self.active
        if q is None:
            return None
        return {"title": q.title, "poi_id": q.poi.id, "status": q.status}


BOOK = QuestBook()


def fallback_quest(
    npc_poi_id: str | None = None,
    zone_id: str | None = None,
    rng: random.Random | None = None,
) -> dict:
    """Geskriptete Quest: zufälliger mission-POI außerhalb der aktuellen Zone.

    Liefert die Argumente für QuestBook.create (poi_id, title, objective, enemies).
    """
    rng = rng or random
    pois = mission_pois()
    choices = [p for p in pois if p.id not in (zone_id, npc_poi_id)] or pois
    poi = rng.choice(choices)
    n = clamp_enemies(rng.randint(2, 3))
    return {
        "poi_id": poi.id,
        "title": rng.choice(TITLE_TEMPLATES).format(name=poi.name),
        "objective": OBJECTIVE_TEMPLATE.format(name=poi.name, n=n),
        "enemies": n,
    }


def register(hub, book: QuestBook | None = None) -> None:
    """Handler am Hub anmelden: Position, Kills, Reconnect und Snapshot-Provider."""
    book = book or BOOK

    async def _send(update: QuestUpdate | None) -> None:
        """Statuswechsel als quest_update an alle Clients."""
        if update is not None:
            log.info("Quest %s: %s", update.quest_id, update.status)
            await hub.send_action("quest_update", update)

    async def on_position(event: PlayerPosition, _env: Envelope) -> None:
        """player_position: Ankunft am Ziel prüfen."""
        await _send(book.on_position(event.x, event.z))

    async def on_kill(event: NpcKilled, _env: Envelope) -> None:
        """npc_killed: Quest-Ziel abhaken."""
        await _send(book.on_kill(event.npc_kind, event.quest_id))

    def on_connect() -> list[Envelope]:
        """Neuer Client bekommt die aktive Quest."""
        update = book.current()
        return [] if update is None else [protocol.make_action("quest_update", update)]

    hub.on_event("player_position", on_position)
    hub.on_event("npc_killed", on_kill)
    hub.on_connect(on_connect)
    hub.register_snapshot_provider("quest", book.snapshot)
