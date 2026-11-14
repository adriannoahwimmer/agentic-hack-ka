"""Vertrag zwischen Browser, Server und Agenten als Pydantic-Modelle.

Zweck: einzige maschinenlesbare Quelle für alle Nachrichten von Fächerstadt Agents:
WebSocket-Envelope, Events (Client -> Server), Aktionen (Server -> Client),
POST /npc/talk, Agent-Snapshot, JSONL-Logzeile und POI-Datei.
Use-Cases:
- ws.py validiert eingehende Events (parse_client_message)
- hub.py und die Agenten bauen ausgehende Aktionen (make_action, make_radio_message)
- tests/test_protocol.py prüft jedes Beispiel in contract/examples/

Spezifikation mit Feldtabellen und Beispielen: Design.md, Abschnitt "Vertrag".
Felder nach Schritt 0 nur additiv ändern, nie umbenennen.
Events vom Client sind tolerant (unbekannte Felder werden ignoriert),
alles, was der Server baut, ist strikt (unbekannte Felder sind ein Fehler).
"""

import hashlib
import itertools
import time
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

import config

POIS_PATH = config.ROOT / "data" / "pois.json"
REASON_MAX_CHARS = 160  # Begründungszeile in Aktionen und Log (Format, kein Tuning)

# Weltkoordinate in Metern (x Ost, z Süd), siehe geo.py. Die Grenzen fangen Müll ab.
Coord = Annotated[float, Field(ge=-5000, le=5000)]
ZoneId = str | None
NpcKind = Literal["civilian", "police", "gang", "quest_target"]


class ProtocolError(ValueError):
    """Ungültige Nachricht: kaputtes JSON, unbekannter Typ oder falsches Payload."""


class _Strict(BaseModel):
    """Basis für alles, was der Server baut: unbekannte Felder sind ein Fehler."""

    model_config = ConfigDict(extra="forbid")


class _Tolerant(BaseModel):
    """Basis für Nachrichten vom Client: unbekannte Felder werden ignoriert."""

    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------
class Envelope(BaseModel):
    """Hülle jeder WebSocket-Nachricht: {type, ts (Unix-ms), payload}."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=40)
    ts: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Events: Client -> Server
# --------------------------------------------------------------------------
class PlayerPosition(_Tolerant):
    """Spielerposition, vom Client auf max. 2 Hz gedrosselt. Löst nie einen Agenten aus."""

    x: Coord
    z: Coord
    heading: float  # Radiant, Rotation um y (Three.js)
    speed: float = Field(ge=0, le=200)  # m/s
    in_vehicle: bool
    zone_id: ZoneId = None


class ShotFired(_Tolerant):
    """Schüsse des Spielers, vom Client pro 500 ms gebündelt."""

    x: Coord
    z: Coord
    shots: int = Field(ge=1, le=50)
    weapon: Literal["pistol", "smg"]
    zone_id: ZoneId = None


class NpcKilled(_Tolerant):
    """Ein Ziel wurde getötet. Nur core/combat im Client sendet das."""

    npc_id: str = Field(min_length=1, max_length=60)
    npc_kind: NpcKind
    x: Coord
    z: Coord
    zone_id: ZoneId = None
    quest_id: str | None = None


class VehicleStolen(_Tolerant):
    """Der Spieler ist in ein fremdes Fahrzeug eingestiegen."""

    vehicle_id: str = Field(min_length=1, max_length=60)
    vehicle_kind: Literal["civilian", "police"]
    x: Coord
    z: Coord
    zone_id: ZoneId = None


class ZoneEntered(_Tolerant):
    """Der Spieler betritt den Radius eines POI (zone_id = poi_id)."""

    zone_id: str = Field(min_length=1, max_length=60)
    previous_zone_id: ZoneId = None


EVENT_MODELS: dict[str, type[BaseModel]] = {
    "player_position": PlayerPosition,
    "shot_fired": ShotFired,
    "npc_killed": NpcKilled,
    "vehicle_stolen": VehicleStolen,
    "zone_entered": ZoneEntered,
}


# --------------------------------------------------------------------------
# Gemeinsame Bausteine
# --------------------------------------------------------------------------
class Source(_Strict):
    """Quelle aus Maps Grounding. Muss im UI direkt beim Text stehen."""

    title: str
    uri: str


class Target(_Strict):
    """Zielgebiet einer Quest in Weltkoordinaten."""

    x: Coord
    z: Coord
    radius: float = Field(gt=0, le=500)


class ToolCall(_Strict):
    """Ein Function-Call (oder eine geskriptete Fallback-Aktion) im Log."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class InlinePlaceholder(_Strict):
    """Platzhalter für Inline-Daten im Log: nie die Bytes selbst."""

    mime: str
    bytes: int = Field(ge=0)


class ErrorInfo(_Strict):
    """Fehler eines GenAI-Calls: HTTP-Code oder Kürzel wie 'timeout', 'budget'."""

    code: int | str
    message: str


# --------------------------------------------------------------------------
# Aktionen: Server -> Client
# --------------------------------------------------------------------------
class SetWantedLevel(_Strict):
    """Neue Fahndungsstufe. Level 0 heißt: Client entfernt alle Polizei-Einheiten."""

    level: int = Field(ge=0, le=config.WANTED_MAX)
    source: Literal["rules", "agent", "fallback"]
    reason: str = Field(max_length=REASON_MAX_CHARS)


class SpawnUnits(_Strict):
    """Einheiten erzeugen. near_poi_id None = in Spielernähe (120-200 m entfernt)."""

    wave_id: str = Field(min_length=1, max_length=40)
    faction: Literal["police", "gang"]
    count: int = Field(ge=1, le=config.POLICE_MAX_UNITS)
    unit_type: Literal["patrol", "swat", "gang"]
    tactic: Literal["chase", "roadblock", "surround"]
    near_poi_id: str | None = None


class RadioMessage(_Strict):
    """Funkspruch. Nur über make_radio_message() bauen (setzt tts_key)."""

    id: str = Field(min_length=1, max_length=40)
    speaker: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=config.RADIO_MAX_CHARS)
    voice: str = Field(min_length=1, max_length=40)
    tts_key: str = Field(pattern=r"^[0-9a-f]{16}$")


class QuestUpdate(_Strict):
    """Quest-Status. Bei target_reached spawnt der Client spawn_targets Gegner."""

    quest_id: str = Field(min_length=1, max_length=40)
    status: Literal["active", "target_reached", "completed"]
    title: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=200)
    poi_id: str
    target: Target
    spawn_targets: int = Field(ge=0, le=config.QUEST_MAX_TARGETS)
    remaining: int = Field(ge=0, le=config.QUEST_MAX_TARGETS)


class LogOutput(_Strict):
    """Was das Modell (oder der Fallback) geliefert hat."""

    text: str | None = None
    calls: list[ToolCall] = Field(default_factory=list)
    inline: list[InlinePlaceholder] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class AgentLog(_Strict):
    """Eine Logzeile fürs Overlay: GenaiLogLine ohne prompt und config."""

    ts: str  # ISO 8601 UTC mit ms
    call_no: int | None = Field(default=None, ge=0)
    kind: Literal["genai", "fallback"]
    agent: str = Field(min_length=1, max_length=40)
    model: str | None = None
    status: Literal["ok", "error"]
    error: ErrorInfo | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    output: LogOutput = Field(default_factory=LogOutput)
    reason: str | None = None


class ErrorMessage(_Strict):
    """Antwort auf eine ungültige Client-Nachricht (Debug-Hilfe)."""

    code: Literal["invalid_message", "unknown_type", "rate_limited"]
    message: str = Field(max_length=500)


ACTION_MODELS: dict[str, type[BaseModel]] = {
    "set_wanted_level": SetWantedLevel,
    "spawn_units": SpawnUnits,
    "radio_message": RadioMessage,
    "quest_update": QuestUpdate,
    "agent_log": AgentLog,
    "error": ErrorMessage,
}


# --------------------------------------------------------------------------
# JSONL-Log (logs/genai.jsonl)
# --------------------------------------------------------------------------
class LogConfig(_Strict):
    """Zusammenfassung der GenerateContentConfig, ohne Secrets."""

    tools: list[str] = Field(default_factory=list)
    tool_mode: str | None = None
    thinking_level: str | None = None
    system_instruction_chars: int = Field(default=0, ge=0)
    response_modalities: list[str] | None = None


class GenaiLogLine(AgentLog):
    """Eine Zeile in logs/genai.jsonl: pro GenAI-Request und pro Fallback-Entscheidung."""

    prompt: str | None = None  # gekürzt auf GENAI_LOG_MAX_PROMPT_CHARS
    config: LogConfig | None = None

    def to_agent_log(self) -> AgentLog:
        """Fassung fürs Overlay (WS agent_log): ohne prompt und config."""
        return AgentLog.model_validate(self.model_dump(exclude={"prompt", "config"}))


# --------------------------------------------------------------------------
# HTTP: POST /npc/talk
# --------------------------------------------------------------------------
class NpcTalkRequest(_Tolerant):
    """Spieler spricht einen NPC an. Leerer player_text = NPC grüßt."""

    npc_id: str = Field(min_length=1, max_length=40)
    player_text: str = Field(default="", max_length=200)
    x: Coord | None = None
    z: Coord | None = None


class NpcTalkResponse(_Strict):
    """Antwort des NPC. Immer 200, auch im Fallback (fallback=True)."""

    npc_id: str
    text: str = Field(min_length=1, max_length=600)
    quest: QuestUpdate | None = None
    sources: list[Source] = Field(default_factory=list)
    model: str | None = None
    fallback: bool


# --------------------------------------------------------------------------
# Snapshot für Agenten
# --------------------------------------------------------------------------
class SnapshotPlayer(_Strict):
    """Spielerzustand im Snapshot."""

    x: Coord
    z: Coord
    zone_id: ZoneId = None
    in_vehicle: bool = False
    speed: float = Field(default=0, ge=0)


class SnapshotEvent(_Strict):
    """Ein jüngeres Event im Snapshot, relativ zur Snapshot-Zeit."""

    type: str
    s_ago: float = Field(ge=0)
    zone_id: ZoneId = None
    detail: dict[str, Any] = Field(default_factory=dict)


class PlaceRef(_Strict):
    """POI-Verweis (id, Name) für den Agenten."""

    id: str
    name: str


class AgentSnapshot(_Strict):
    """Kompakter Lagebericht, der als User-Content an einen Agenten geht (Ziel < 2 KB)."""

    agent: str
    t: str  # ISO 8601 UTC
    player: SnapshotPlayer | None = None
    wanted_level: int = Field(default=0, ge=0, le=config.WANTED_MAX)
    units_active: int = Field(default=0, ge=0)
    units_max: int = Field(default=config.POLICE_MAX_UNITS, ge=0)
    recent_events: list[SnapshotEvent] = Field(default_factory=list, max_length=12)
    counts_60s: dict[str, int] = Field(default_factory=dict)
    memory: list[str] = Field(default_factory=list, max_length=5)
    places: list[PlaceRef] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)

    def to_prompt(self) -> str:
        """Kompaktes JSON für den Prompt (ohne None-Felder)."""
        return self.model_dump_json(exclude_none=True)


# --------------------------------------------------------------------------
# POI-Datei (data/pois.json)
# --------------------------------------------------------------------------
class Origin(_Strict):
    """Ursprung der lokalen Koordinaten (Schloss)."""

    lat: float
    lon: float


class Poi(_Strict):
    """Vorgebackener Ort. Quest-Ziele kommen nur von hier (Regel 4)."""

    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=1, max_length=60)
    category: str
    lat: float
    lon: float
    x: Coord
    z: Coord
    radius: float = Field(gt=0, le=500)
    osm_ref: str = Field(pattern=r"^(node|way|relation)/\d+$")
    tags: list[Literal["mission", "gang_turf", "npc_spot", "crowded"]] = Field(
        default_factory=list
    )
    description: str = Field(max_length=300)


class PoiFile(_Strict):
    """Inhalt von data/pois.json."""

    version: Literal[1]
    origin: Origin
    pois: list[Poi] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self):
        """POI-IDs müssen eindeutig sein."""
        ids = [p.id for p in self.pois]
        if len(ids) != len(set(ids)):
            raise ValueError("POI-IDs sind nicht eindeutig")
        return self

    def get(self, poi_id: str) -> Poi | None:
        """POI zur ID oder None."""
        return next((p for p in self.pois if p.id == poi_id), None)


@lru_cache(maxsize=4)
def load_pois(path: str | Path = POIS_PATH) -> PoiFile:
    """data/pois.json laden und validieren (gecacht)."""
    return PoiFile.model_validate_json(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------
def now_ms() -> int:
    """Aktuelle Unix-Zeit in Millisekunden (Envelope.ts)."""
    return int(time.time() * 1000)


def parse_client_message(text: str | bytes) -> tuple[Envelope, BaseModel]:
    """Rohe WS-Nachricht -> (Envelope, validiertes Event). Wirft ProtocolError."""
    try:
        env = Envelope.model_validate_json(text)
    except ValidationError as e:
        raise ProtocolError(f"invalid_message: {e.errors(include_url=False)}") from e
    model = EVENT_MODELS.get(env.type)
    if model is None:
        raise ProtocolError(f"unknown_type: {env.type}")
    try:
        return env, model.model_validate(env.payload)
    except ValidationError as e:
        raise ProtocolError(f"invalid_message: {e.errors(include_url=False)}") from e


def _validated(models: dict[str, type[BaseModel]], type_: str, payload) -> BaseModel:
    model = models.get(type_)
    if model is None:
        raise ProtocolError(f"unknown_type: {type_}")
    if isinstance(payload, model):
        return payload
    data = payload.model_dump() if isinstance(payload, BaseModel) else payload
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ProtocolError(f"invalid_message: {e.errors(include_url=False)}") from e


def make_action(type_: str, payload: BaseModel | dict) -> Envelope:
    """Aktion (Server -> Client) validieren und in eine Envelope packen."""
    model = _validated(ACTION_MODELS, type_, payload)
    return Envelope(type=type_, ts=now_ms(), payload=model.model_dump(mode="json"))


def make_event(type_: str, payload: BaseModel | dict) -> Envelope:
    """Event (Client -> Server) bauen. Für Tests und Debug-Werkzeuge."""
    model = _validated(EVENT_MODELS, type_, payload)
    return Envelope(type=type_, ts=now_ms(), payload=model.model_dump(mode="json"))


def tts_key(text: str, voice: str) -> str:
    """Cache-Schlüssel für TTS: sha256(voice|text), 16 Hex-Zeichen."""
    return hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()[:16]


_radio_ids = itertools.count(1)


def make_radio_message(
    text: str, speaker: str = "Dispatch", voice: str | None = None
) -> RadioMessage:
    """Funkspruch bauen: kürzt auf RADIO_MAX_CHARS, setzt id und tts_key."""
    voice = voice or config.TTS_VOICE
    text = " ".join(text.split())[: config.RADIO_MAX_CHARS]
    return RadioMessage(
        id=f"r-{next(_radio_ids)}",
        speaker=speaker,
        text=text,
        voice=voice,
        tts_key=tts_key(text, voice),
    )
