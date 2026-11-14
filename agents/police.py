"""Polizei-Dispatcher: Gemini-Agent, der Fahndung, Einheiten und Funk festlegt.

Zweck: Feature-Modul der Scheibe Polizei (Design.md, "Polizei-Dispatcher"). Ein
Request pro Zyklus (Function Calling im Modus ANY, mehrere parallele Calls). Die
Tool-Ergebnisse gehen nicht ans Modell zurück: der Server clampt die Calls und
schickt sie als Aktionen per WebSocket. Gedächtnis liegt serverseitig im Snapshot.
Use-Cases:
- Schießerei -> der Agent eskaliert die Fahndung, schickt Einheiten an echte Orte, funkt
- Gemini nicht erreichbar, zu langsam oder AGENTS_MODE=offline -> deterministischer Fallback
- Clamps schützen das Spiel vor unsinnigen Modellwerten (Level-Sprünge, zu viele Einheiten)
- Level nur in [Boden, Boden+1]; 5 Sterne nur bei >= 2 getöteten Polizisten oder Taunt bei 4
- Einheiten je Stufe nach UNIT_TABLE (foot, patrol, tank; swat zählt wie patrol)
- player_radio (plead/taunt) löst sofort einen Zyklus aus (Cooldown POLICE_RADIO_COOLDOWN_S),
  der Dispatcher antwortet immer per radio_message

Entwürfe (decide/fallback) sind Envelopes mit Roh-Argumenten; erst clamp() baut daraus
gültige Vertrags-Payloads (spawn_units.count = target_units - units_active).
"""

import asyncio
import itertools
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from google.genai import types

import config
import game_state
import gemini
import protocol
import runner
from hub import Hub
from protocol import AgentSnapshot, Envelope

log = logging.getLogger(__name__)

AGENT = "police"
TRIGGERS = {
    "shot_fired",
    "npc_killed",
    "vehicle_stolen",
    "zone_entered",
    "police_hit",
    "police_killed",
}
POLICE_UNIT_TYPES = ("foot", "patrol", "swat", "tank")
# Kontingent je Fahndungsstufe (gesamt max. 6). swat zählt wie patrol.
UNIT_TABLE: dict[int, dict[str, int]] = {
    0: {},
    1: {"foot": 1},
    2: {"foot": 1, "patrol": 1},
    3: {"foot": 2, "patrol": 2},
    4: {"foot": 2, "patrol": 4},
    5: {"foot": 2, "patrol": 3, "tank": 1},
}
FLOOR_MAX = 4  # Boden aus game_state, 5 nur durch den Agenten
PLEAD_MIN_CRIME_S = 20.0  # plead senkt nur, wenn das letzte Delikt länger her ist
RADIO_REPLY = {
    "plead": "Leitstelle an Täter: Abgelehnt. Bleiben Sie stehen, Hände sichtbar.",
    "plead_ok": "Leitstelle an Täter: Verstanden. Stehen bleiben, wir fahren runter.",
    "taunt": "Leitstelle an Täter: Große Worte. Weitere Streifen sind unterwegs.",
}
TACTICS = ("chase", "roadblock", "surround")
TOOL_ORDER = ("set_wanted_level", "spawn_units", "radio_message")

SYSTEM_PROMPT = """\
You are the Karlsruhe police dispatcher in a video game. Each message is a JSON \
situation report (snapshot) about one suspect, the player.
You only set parameters through your tools; the game drives the cars itself.
Rules:
- wanted_level 0-5. Shots and casualties justify escalation; one dead civilian is \
level 2-3, several deaths or killed officers level 4-5. Never change by more than 2 at once.
- extras.wanted.floor is the rule floor. You may only set level floor or floor+1 \
(never below floor). Level 5 only for sustained escalation: police_kills >= 2, or a \
taunt at level 4. Explain the level in reason.
- Units per level (total, by unit_type; foot = officer on foot, patrol = squad car, \
tank = armoured vehicle): 1: 1 foot. 2: 1 foot + 1 patrol. 3: 2 foot + 2 patrol. \
4: 2 foot + 4 patrol. 5: 2 foot + 3 patrol + 1 tank. Active units are in \
extras.wanted.units_by_type. Call spawn_units once per unit_type with count = units to add.
- Tactics: chase (pursue), roadblock (block the road ahead), surround (encircle). \
near_place_id must be an id from places, or omit it.
- extras.player_radio is the suspect talking to you on the radio. ALWAYS answer with \
radio_message addressed to the suspect (short, German). plead: you may lower the level by 1 \
only if extras.wanted.crime_s_ago > 20 and never below floor, else refuse. taunt: you may \
raise the level by 1 and add units (taunt at level 4 allows 5).
- radio_message: one short German police radio call (Polizeifunk jargon, max 15 words), \
e.g. "Alle Streifen: Schüsse am Marktplatz, Täter bewaffnet, Eigensicherung beachten." \
Name the real Karlsruhe place from places (suspect's zone or near_place_id) by its German \
local name, e.g. Marktplatz, Schlossplatz, Kronenplatz, Schloss. No game or AI talk.
- Every tool call needs a one-sentence reason.
Call set_wanted_level, spawn_units and radio_message in one response when the situation \
calls for it; skip spawn_units if enough units are active."""

TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="set_wanted_level",
            description="Set the suspect's wanted level (0-5).",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "minimum": 0, "maximum": 5},
                    "reason": {"type": "string", "description": "One sentence why."},
                },
                "required": ["level", "reason"],
            },
        ),
        types.FunctionDeclaration(
            name="spawn_units",
            description="Request police units of one unit_type. count = units to add.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "minimum": 1, "maximum": 6},
                    "unit_type": {"type": "string", "enum": list(POLICE_UNIT_TYPES)},
                    "tactic": {"type": "string", "enum": list(TACTICS)},
                    "near_place_id": {
                        "type": "string",
                        "description": "id from places; omit to deploy near the suspect.",
                    },
                    "reason": {"type": "string", "description": "One sentence why."},
                },
                "required": ["count", "unit_type", "tactic", "reason"],
            },
        ),
        types.FunctionDeclaration(
            name="radio_message",
            description="Broadcast one short police radio call (spoken aloud in game).",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "German police radio call, max 15 words, "
                        "naming a Karlsruhe place.",
                    },
                    "reason": {"type": "string", "description": "One sentence why."},
                },
                "required": ["text", "reason"],
            },
        ),
    ]
)

GEN_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[TOOLS],
    tool_config=types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode="ANY")
    ),
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    thinking_config=types.ThinkingConfig(thinking_level=config.GEMINI_THINKING_LEVEL),
)

RADIO_TEMPLATES = (
    "Alle Streifen: Schüsse bei {place}. Täter bewaffnet, Eigensicherung beachten.",
    "Leitstelle an alle: Täter zuletzt gesehen bei {place}. Fahndungsstufe {level}.",
    "Mit Sonderrechten nach {place}. Bewaffneter Täter, Passanten vor Ort.",
    "Alle Einheiten nach {place}. Absperrung einrichten, Sichtkontakt halten.",
    "Täter flüchtig ab {place}. {units} Streifen in Verfolgung, Kanal freihalten.",
)

MEMORY: deque[str] = deque(maxlen=5)
# Offener Funkspruch des Spielers für den nächsten Zyklus ({"tone", "text"}) und Cooldown
PENDING_RADIO: dict[str, Any] = {}
_radio_state: dict[str, float | None] = {"last": None}
RADIO_TASKS: set[asyncio.Task] = set()
_waves = itertools.count(1)
_templates = itertools.count(0)


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------
def _draft(type_: str, payload: dict[str, Any]) -> Envelope:
    """Entwurf einer Aktion (Roh-Argumente, noch nicht gegen den Vertrag geprüft)."""
    return Envelope(type=type_, ts=protocol.now_ms(), payload=payload)


def _floor(snapshot: AgentSnapshot) -> int:
    """Regel-Boden aus extras.wanted (game_state), sonst 0."""
    wanted = snapshot.extras.get("wanted") or {}
    try:
        return int(wanted.get("floor", 0))
    except (TypeError, ValueError):
        return 0


def _wanted(snapshot: AgentSnapshot) -> dict[str, Any]:
    """extras.wanted aus dem Snapshot (game_state), sonst leer."""
    wanted = snapshot.extras.get("wanted")
    return wanted if isinstance(wanted, dict) else {}


def _player_radio(snapshot: AgentSnapshot) -> dict[str, Any] | None:
    """Offener Funkspruch des Spielers aus extras.player_radio, sonst None."""
    radio = snapshot.extras.get("player_radio")
    return radio if isinstance(radio, dict) and radio.get("tone") else None


def level_cap(snapshot: AgentSnapshot) -> int:
    """Höchstes erlaubtes Level: Boden+1, 5 nur bei >= 2 toten Polizisten oder Taunt bei 4."""
    floor = _floor(snapshot)
    radio = _player_radio(snapshot) or {}
    kills = _int(_wanted(snapshot).get("police_kills")) or 0
    escalation = kills >= 2 or (
        radio.get("tone") == "taunt" and snapshot.wanted_level >= FLOOR_MAX
    )
    top = config.WANTED_MAX if escalation else min(config.WANTED_MAX, FLOOR_MAX)
    return max(floor, min(top, floor + 1))


def unit_quota(level: int, unit_type: str, snapshot: AgentSnapshot) -> int:
    """Wie viele Einheiten dieses Typs noch dazukommen dürfen (UNIT_TABLE minus aktive)."""
    kind = "patrol" if unit_type == "swat" else unit_type
    table = UNIT_TABLE.get(max(0, min(level, max(UNIT_TABLE))), {})
    active = _wanted(snapshot).get("units_by_type") or {}
    if kind == "patrol":
        used = (_int(active.get("patrol")) or 0) + (_int(active.get("swat")) or 0)
    else:
        used = _int(active.get(kind)) or 0
    room = config.POLICE_MAX_UNITS - snapshot.units_active
    return max(0, min(table.get(kind, 0) - used, room))


def _place_name(snapshot: AgentSnapshot, place_id: str | None) -> str | None:
    """Name eines Ortes aus snapshot.places."""
    return next((p.name for p in snapshot.places if p.id == place_id), None)


def _int(value: Any) -> int | None:
    """Ganzzahl aus Modellwert (int, float, "3"), sonst None."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# decide (Gemini), fallback, clamp
# --------------------------------------------------------------------------
async def decide(snapshot: AgentSnapshot) -> list[Envelope]:
    """Ein Gemini-Request: Snapshot rein, Function-Calls raus (als Entwürfe)."""
    response, _model = await gemini.agenerate(
        snapshot.to_prompt(),
        config.GEMINI_MODEL_POLICE,
        GEN_CONFIG,
        agent=AGENT,
        attempts=config.AGENT_ATTEMPTS,
        timeout_ms=config.AGENT_DEADLINE_MS,
        use_fallback_model=False,
    )
    drafts = []
    for call in response.function_calls or []:
        args = dict(call.args or {})
        if call.name == "set_wanted_level":
            args["source"] = "agent"
        drafts.append(_draft(call.name or "?", args))
    return drafts


def fallback(snapshot: AgentSnapshot) -> list[Envelope]:
    """Deterministische Entscheidung ohne LLM: Level, Einheiten bis Level, Funk aus Vorlage.

    Level = max(aktuelles Level, Boden), bei Taunt +1 (bis level_cap). Einheiten je
    unit_type nach UNIT_TABLE. Auf plead: kein Effekt, Standardantwort (Deeskalation macht
    der Decay in game_state).
    """
    floor = _floor(snapshot)
    radio = _player_radio(snapshot)
    level = max(snapshot.wanted_level, floor)
    if radio and radio.get("tone") == "taunt":
        level += 1
    level = min(level, level_cap(snapshot) if radio else max(level, floor))
    if level <= 0 and not radio:
        return []
    zone = snapshot.player.zone_id if snapshot.player else None
    place = _place_name(snapshot, zone) or "Innenstadt Karlsruhe"
    tactic = "chase" if level <= 2 else ("roadblock" if level == 3 else "surround")
    template = RADIO_TEMPLATES[next(_templates) % len(RADIO_TEMPLATES)]
    drafts = [
        _draft(
            "set_wanted_level",
            {
                "level": level,
                "source": "fallback",
                "reason": f"Rule floor {floor}, units per wanted table",
            },
        )
    ]
    for unit_type, n in UNIT_TABLE.get(min(level, max(UNIT_TABLE)), {}).items():
        drafts.append(
            _draft(
                "spawn_units",
                {
                    "count": n,
                    "unit_type": unit_type,
                    "tactic": tactic,
                    "near_place_id": zone,
                    "reason": f"Units for wanted level {level}",
                },
            )
        )
    text = (
        RADIO_REPLY["taunt" if radio["tone"] == "taunt" else "plead"]
        if radio
        else template.format(place=place, level=level, units=level)
    )
    drafts.append(
        _draft("radio_message", {"text": text, "reason": "Scripted dispatch call"})
    )
    return drafts


def clamp(drafts: list[Envelope], snapshot: AgentSnapshot) -> list[Envelope]:
    """Entwürfe in gültige Aktionen verwandeln (Regeln in Design.md, "Polizei-Dispatcher").

    - set_wanted_level/radio_message: höchstens ein Call; spawn_units: einer je unit_type
    - Level in [Boden, level_cap], höchstens ±WANTED_MAX_STEP pro Zyklus, unverändert -> weg
    - Senkung nur auf plead: um 1, letztes Delikt > PLEAD_MIN_CRIME_S her, nie unter Boden
    - count je unit_type höchstens UNIT_TABLE[Level] minus aktive Einheiten dieses Typs
    - ungültige Enums -> patrol/chase, unbekannte near_place_id -> None
    - Funktext getrimmt auf RADIO_MAX_CHARS, leer -> weg; auf player_radio immer eine Antwort
    """
    first: dict[str, dict[str, Any]] = {}
    spawns: list[dict[str, Any]] = []
    for draft in drafts:
        if draft.type == "spawn_units":
            spawns.append(draft.payload)
        elif draft.type in TOOL_ORDER and draft.type not in first:
            first[draft.type] = draft.payload
    out: list[Envelope] = []
    current = snapshot.wanted_level
    level_after = current
    radio_in = _player_radio(snapshot)
    wanted = _wanted(snapshot)

    args = first.get("set_wanted_level")
    if args is not None:
        level = _int(args.get("level"))
        if level is not None:
            floor = _floor(snapshot)
            level = max(floor, min(level_cap(snapshot), level))
            low = max(0, current - config.WANTED_MAX_STEP)
            level = max(floor, min(current + config.WANTED_MAX_STEP, max(low, level)))
            if level < current:
                since = wanted.get("crime_s_ago")
                plead_ok = (
                    radio_in is not None
                    and radio_in.get("tone") == "plead"
                    and (since is None or float(since) > PLEAD_MIN_CRIME_S)
                )
                level = max(level, current - 1) if plead_ok else current
            if level != current:
                level_after = level
                source = (
                    args.get("source")
                    if args.get("source") in ("agent", "fallback")
                    else "agent"
                )
                out.append(
                    protocol.make_action(
                        "set_wanted_level",
                        {
                            "level": level,
                            "source": source,
                            "reason": str(args.get("reason") or "Dispatcher decision")[
                                : protocol.REASON_MAX_CHARS
                            ],
                        },
                    )
                )

    seen: set[str] = set()
    granted: dict[str, int] = {}
    for args in spawns if level_after > 0 else []:
        unit_type = args.get("unit_type")
        unit_type = unit_type if unit_type in POLICE_UNIT_TYPES else "patrol"
        kind = "patrol" if unit_type == "swat" else unit_type
        if kind in seen:
            continue
        seen.add(kind)
        wanted_n = _int(args.get("count"))
        if wanted_n is None:  # Altform: target_units = gewünschte Gesamtzahl
            wanted_n = (_int(args.get("target_units")) or 0) - snapshot.units_active
        room = config.POLICE_MAX_UNITS - snapshot.units_active - sum(granted.values())
        quota = min(unit_quota(level_after, kind, snapshot), room)
        count = min(wanted_n, quota)
        if count <= 0:
            continue
        granted[kind] = count
        tactic = args.get("tactic")
        place = args.get("near_place_id")
        out.append(
            protocol.make_action(
                "spawn_units",
                {
                    "wave_id": f"w-{next(_waves)}",
                    "faction": "police",
                    "count": count,
                    "unit_type": unit_type,
                    "tactic": tactic if tactic in TACTICS else "chase",
                    "near_poi_id": place if _place_name(snapshot, place) else None,
                },
            )
        )

    args = first.get("radio_message") or {}
    text = " ".join(str(args.get("text") or "").split())[: config.RADIO_MAX_CHARS]
    if (
        not text and radio_in is not None
    ):  # auf player_radio antwortet die Leitstelle immer
        lowered = level_after < current
        key = "taunt" if radio_in.get("tone") == "taunt" else "plead"
        text = RADIO_REPLY["plead_ok" if lowered else key]
    if text:
        radio = protocol.make_radio_message(text)
        out.append(protocol.make_action("radio_message", radio))
    return out


def remember(sent: list[Envelope], source: str) -> None:
    """Gedächtnis: eine Zeile pro Zyklus (höchstens 5), z. B. '14:02:40 level 2 (agent), +2 patrol chase'."""
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    parts = []
    for env in sent:
        p = env.payload
        if env.type == "set_wanted_level":
            parts.append(f"level {p['level']}")
        elif env.type == "spawn_units":
            parts.append(f"+{p['count']} {p['unit_type']} {p['tactic']}")
        elif env.type == "radio_message":
            parts.append("radio")
    MEMORY.append(f"{stamp} {source}: {', '.join(parts) or 'no change'}")
    PENDING_RADIO.clear()


def snapshot() -> AgentSnapshot:
    """Aktueller Lagebericht mit dem Gedächtnis des Dispatchers."""
    snap = game_state.STATE.snapshot(AGENT, list(MEMORY))
    if PENDING_RADIO:
        snap.extras["player_radio"] = dict(PENDING_RADIO)
    return snap


def radio_allowed(now: float) -> bool:
    """Cooldown für player_radio: True und Zeit merken, wenn die Sperre abgelaufen ist."""
    last = _radio_state["last"]
    if last is not None and now - last < config.POLICE_RADIO_COOLDOWN_S:
        return False
    _radio_state["last"] = now
    return True


def make_radio_handler(agent_runner: runner.AgentRunner, clock=time.monotonic):
    """Hub-Handler für player_radio: sofort ein Zyklus (ohne Debounce), sonst ignorieren."""

    async def on_player_radio(event: protocol.PlayerRadio, env: Envelope) -> None:
        """Funkspruch merken und den Dispatcher sofort entscheiden lassen."""
        if not radio_allowed(clock()):
            return
        PENDING_RADIO.clear()
        PENDING_RADIO.update({"tone": event.tone, "text": event.text[:120]})
        # eigener Task, damit der WebSocket-Empfang nicht auf Gemini wartet
        task = asyncio.get_running_loop().create_task(agent_runner.run_cycle())
        RADIO_TASKS.add(task)
        task.add_done_callback(RADIO_TASKS.discard)

    return on_player_radio


def trigger_filter(event, env: Envelope) -> bool:
    """zone_entered löst nur ab Level 1 einen Zyklus aus."""
    return env.type != "zone_entered" or game_state.STATE.wanted_level >= 1


def spec() -> runner.AgentSpec:
    """AgentSpec des Dispatchers (Werte aus config.py zur Registrierungszeit)."""
    return runner.AgentSpec(
        name=AGENT,
        triggers=set(TRIGGERS),
        min_interval_s=config.POLICE_MIN_INTERVAL_S,
        decide=decide,
        fallback=fallback,
        clamp=clamp,
        snapshot=snapshot,
        trigger_filter=trigger_filter,
        on_sent=remember,
    )


def register(hub: Hub) -> None:
    """Feature-Einstieg: Gedächtnis leeren, Dispatcher beim Runner anmelden."""
    MEMORY.clear()
    PENDING_RADIO.clear()
    _radio_state["last"] = None
    agent_runner = runner.register_agent(spec(), hub)
    hub.on_event("player_radio", make_radio_handler(agent_runner))


async def startup() -> None:
    """Lifespan: im Live-Modus den Gemini-Client vorwärmen (kalt ca. 3 s, kein Request).

    Sonst fällt die Client-Erzeugung in den ersten Zyklus und frisst dessen Deadline.
    """
    if not gemini.live_enabled():
        return
    try:
        await asyncio.to_thread(gemini.get_client)
    except Exception:  # ohne Client greift ohnehin der Fallback
        log.exception("Gemini-Client nicht vorwärmbar")
