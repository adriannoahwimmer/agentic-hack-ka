"""Polizei-Dispatcher: Gemini-Agent, der Fahndung, Einheiten und Funk festlegt.

Zweck: Feature-Modul der Scheibe Polizei (Design.md, "Polizei-Dispatcher"). Ein
Request pro Zyklus (Function Calling im Modus ANY, mehrere parallele Calls). Die
Tool-Ergebnisse gehen nicht ans Modell zurück: der Server clampt die Calls und
schickt sie als Aktionen per WebSocket. Gedächtnis liegt serverseitig im Snapshot.
Use-Cases:
- Schießerei -> der Agent eskaliert die Fahndung, schickt Einheiten an echte Orte, funkt
- Gemini nicht erreichbar, zu langsam oder AGENTS_MODE=offline -> deterministischer Fallback
- Clamps schützen das Spiel vor unsinnigen Modellwerten (Level-Sprünge, zu viele Einheiten)

Entwürfe (decide/fallback) sind Envelopes mit Roh-Argumenten; erst clamp() baut daraus
gültige Vertrags-Payloads (spawn_units.count = target_units - units_active).
"""

import asyncio
import itertools
import logging
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
TRIGGERS = {"shot_fired", "npc_killed", "vehicle_stolen", "zone_entered"}
POLICE_UNIT_TYPES = ("patrol", "swat")
TACTICS = ("chase", "roadblock", "surround")
TOOL_ORDER = ("set_wanted_level", "spawn_units", "radio_message")

SYSTEM_PROMPT = """\
You are the Karlsruhe police dispatcher in a video game. Each message is a JSON \
situation report (snapshot) about one suspect, the player.
You only set parameters through your tools; the game drives the cars itself.
Rules:
- wanted_level 0-5. Shots and casualties justify escalation; one dead civilian is \
level 2-3, several deaths or killed officers level 4-5. Never change by more than 2 at once.
- spawn_units.target_units is the total number of active units you want (max units_max). \
Use patrol up to level 3, swat from level 4. Tactics: chase (pursue), roadblock (block \
the road ahead), surround (encircle). near_place_id must be an id from places, or omit it.
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
            description="Request police units. target_units is the desired TOTAL of active units.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "target_units": {"type": "integer", "minimum": 1, "maximum": 6},
                    "unit_type": {"type": "string", "enum": list(POLICE_UNIT_TYPES)},
                    "tactic": {"type": "string", "enum": list(TACTICS)},
                    "near_place_id": {
                        "type": "string",
                        "description": "id from places; omit to deploy near the suspect.",
                    },
                    "reason": {"type": "string", "description": "One sentence why."},
                },
                "required": ["target_units", "unit_type", "tactic", "reason"],
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

    Level = min(5, Boden + Tote der letzten 60 s), aber nie unter dem aktuellen Level
    (Deeskalation macht der Decay in game_state).
    """
    floor = _floor(snapshot)
    deaths = snapshot.counts_60s.get("npc_killed", 0)
    level = max(snapshot.wanted_level, min(config.WANTED_MAX, floor + deaths))
    # Schrittgrenze schon hier, damit Einheiten und Taktik zum gesendeten Level passen
    level = min(level, snapshot.wanted_level + config.WANTED_MAX_STEP)
    if level <= 0:
        return []
    zone = snapshot.player.zone_id if snapshot.player else None
    place = _place_name(snapshot, zone) or "Innenstadt Karlsruhe"
    tactic = "chase" if level <= 2 else ("roadblock" if level == 3 else "surround")
    template = RADIO_TEMPLATES[next(_templates) % len(RADIO_TEMPLATES)]
    return [
        _draft(
            "set_wanted_level",
            {
                "level": level,
                "source": "fallback",
                "reason": f"{deaths} casualties in 60 s, floor {floor}",
            },
        ),
        _draft(
            "spawn_units",
            {
                "target_units": level,
                "unit_type": "swat" if level >= 4 else "patrol",
                "tactic": tactic,
                "near_place_id": zone,
                "reason": f"Units up to wanted level {level}",
            },
        ),
        _draft(
            "radio_message",
            {
                "text": template.format(place=place, level=level, units=level),
                "reason": "Scripted dispatch call",
            },
        ),
    ]


def clamp(drafts: list[Envelope], snapshot: AgentSnapshot) -> list[Envelope]:
    """Entwürfe in gültige Aktionen verwandeln (Regeln in Design.md, "Polizei-Dispatcher").

    - pro Tool höchstens ein Call, unbekannte Tools ignorieren
    - Level in [Boden, WANTED_MAX], höchstens ±WANTED_MAX_STEP pro Zyklus, unverändert -> weg
    - count = min(target_units, POLICE_MAX_UNITS) - units_active, ≤ 0 -> weg
    - ungültige Enums -> patrol/chase, unbekannte near_place_id -> None
    - Funktext getrimmt auf RADIO_MAX_CHARS, leer -> weg
    """
    first: dict[str, dict[str, Any]] = {}
    for draft in drafts:
        if draft.type in TOOL_ORDER and draft.type not in first:
            first[draft.type] = draft.payload
    out: list[Envelope] = []
    current = snapshot.wanted_level
    level_after = current

    args = first.get("set_wanted_level")
    if args is not None:
        level = _int(args.get("level"))
        if level is not None:
            floor = _floor(snapshot)
            level = max(floor, min(config.WANTED_MAX, level))
            low = max(0, current - config.WANTED_MAX_STEP)
            level = max(floor, min(current + config.WANTED_MAX_STEP, max(low, level)))
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

    args = first.get("spawn_units")
    if args is not None and level_after > 0:
        target = _int(args.get("target_units")) or 0
        count = min(target, config.POLICE_MAX_UNITS) - snapshot.units_active
        if count > 0:
            unit_type = args.get("unit_type")
            tactic = args.get("tactic")
            place = args.get("near_place_id")
            out.append(
                protocol.make_action(
                    "spawn_units",
                    {
                        "wave_id": f"w-{next(_waves)}",
                        "faction": "police",
                        "count": count,
                        "unit_type": unit_type
                        if unit_type in POLICE_UNIT_TYPES
                        else "patrol",
                        "tactic": tactic if tactic in TACTICS else "chase",
                        "near_poi_id": place if _place_name(snapshot, place) else None,
                    },
                )
            )

    args = first.get("radio_message")
    if args is not None:
        text = " ".join(str(args.get("text") or "").split())[: config.RADIO_MAX_CHARS]
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


def snapshot() -> AgentSnapshot:
    """Aktueller Lagebericht mit dem Gedächtnis des Dispatchers."""
    return game_state.STATE.snapshot(AGENT, list(MEMORY))


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
    runner.register_agent(spec(), hub)


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
