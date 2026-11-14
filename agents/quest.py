"""Quest-NPC als Gemini-Agent hinter POST /npc/talk (Scheibe Quest).

Zweck: Ein NPC (data/npcs.json) redet mit dem Spieler und vergibt per Function Calling
eine Quest zu einem echten Ort. Ziele kommen nur aus data/pois.json (mission-Tag),
die Wahrheit über Ankunft und Erfüllung liegt in quests.py.
Use-Cases:
- Spieler drückt E beim NPC -> Dialog mit Quest, Zielmarker per quest_update (WS)
- Gemini offline, zu langsam, Budget leer oder Fehler -> geskriptete Fallback-Quest, HTTP 200
- Agent-Log-Overlay zeigt jeden Schritt (genai_log über gemini.agenerate, Fallback per log_fallback)

Tool-Loop wie /agent in main.py: Modell-Turn unverändert in den Verlauf (Thought-Signatures),
Tool-Ergebnisse mit id zurück. assign_quest beendet den Loop, höchstens QUEST_MAX_STEPS
Requests, Gesamt-Deadline QUEST_DEADLINE_MS. Maps Grounding ist gestrichen (Q0: 429),
lookup_place liefert die Beschreibung aus pois.json.
"""

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from google.genai import types

import config
import gemini
import genai_log
import hub as hub_module
import protocol
import quests
from protocol import NpcTalkRequest, NpcTalkResponse, QuestUpdate, Source

log = logging.getLogger(__name__)

NPCS_PATH = config.ROOT / "data" / "npcs.json"
MEMORY_LINES = 6  # letzte Sätze pro NPC (Spieler und NPC)
AGENT_NAME = "quest"

router = APIRouter()


@dataclass(frozen=True)
class Npc:
    """Ein sprechender NPC aus data/npcs.json."""

    id: str
    name: str
    persona: str
    poi_id: str
    x: float
    z: float


@lru_cache(maxsize=1)
def load_npcs() -> dict[str, Npc]:
    """data/npcs.json laden (gecacht): id -> Npc."""
    raw = json.loads(NPCS_PATH.read_text(encoding="utf-8"))
    return {n["id"]: Npc(**n) for n in raw}


MEMORY: dict[str, deque[str]] = {}


def remember(npc_id: str, line: str) -> None:
    """Satz ins Gedächtnis des NPC (höchstens MEMORY_LINES)."""
    MEMORY.setdefault(npc_id, deque(maxlen=MEMORY_LINES)).append(line[:200])


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------
def lookup_place(place_id: str, reason: str = "") -> dict:
    """Tool: Infos zu einem mission-POI (Name, Beschreibung). Fehler als {"error": ...}."""
    poi = protocol.load_pois().get(str(place_id))
    if poi is None or "mission" not in poi.tags:
        valid = ", ".join(p.id for p in quests.mission_pois())
        return {"error": f"unknown place_id {place_id!r}; valid: {valid}"}
    return {
        "id": poi.id,
        "name": poi.name,
        "category": poi.category,
        "facts": poi.description,
    }


def assign_quest(
    book: quests.QuestBook,
    place_id: str,
    title: str,
    objective: str,
    enemies=3,
    npc_line: str = "",
    reason: str = "",
) -> dict:
    """Tool: Quest anlegen. Liefert {"quest": QuestUpdate} oder {"error": ...}."""
    try:
        return {"quest": book.create(place_id, title, objective, enemies)}
    except quests.QuestError as e:
        return {"error": str(e)}


def _place_list() -> str:
    """Kompakte Liste der erlaubten Ziele für den System-Prompt."""
    return "; ".join(f"{p.id} ({p.name})" for p in quests.mission_pois())


def _declarations() -> types.Tool:
    """Function-Declarations der beiden Tools (place_id als Enum der mission-POIs)."""
    ids = [p.id for p in quests.mission_pois()]
    reason = {
        "type": "string",
        "description": "One short sentence why you do this (shown in the agent log).",
    }
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="lookup_place",
                description="Look up facts about a mission place before giving a job there.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "place_id": {"type": "string", "enum": ids},
                        "reason": reason,
                    },
                    "required": ["place_id", "reason"],
                },
            ),
            types.FunctionDeclaration(
                name="assign_quest",
                description=(
                    "Give the player a job at a mission place. Ends the conversation turn. "
                    "npc_line is what you say to the player (max 2 sentences, in character, "
                    "mention one fact about the place)."
                ),
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "place_id": {"type": "string", "enum": ids},
                        "title": {"type": "string", "description": "Max 5 words."},
                        "objective": {
                            "type": "string",
                            "description": "Imperative, e.g. 'Go to X and take out 3 thugs'.",
                        },
                        "enemies": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": config.QUEST_MAX_TARGETS,
                        },
                        "npc_line": {"type": "string"},
                        "reason": reason,
                    },
                    "required": [
                        "place_id",
                        "title",
                        "objective",
                        "enemies",
                        "npc_line",
                        "reason",
                    ],
                },
            ),
        ]
    )


def agent_config(npc: Npc) -> types.GenerateContentConfig:
    """Config für den Quest-Agenten: Persona, erlaubte Orte, Tools, wenig Thinking."""
    system = (
        f"You are {npc.name}, an NPC in a GTA-style game set in Karlsruhe, Germany. "
        f"Persona: {npc.persona} "
        "Speak English, max 2 short sentences, stay in character, no real-world violence advice. "
        "When the player greets you or asks for work, call lookup_place for one place, "
        "then assign_quest there with 2-4 enemies. If a quest is already active, just "
        "remind the player of it in plain text. Only these places exist: "
        f"{_place_list()}."
    )
    return types.GenerateContentConfig(
        system_instruction=system,
        tools=[_declarations()],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(
            thinking_level=config.GEMINI_THINKING_LEVEL
        ),
    )


# --------------------------------------------------------------------------
# Agent und Fallback
# --------------------------------------------------------------------------
@dataclass
class TalkResult:
    """Ergebnis eines Gesprächs, bevor es zur HTTP-Antwort wird."""

    text: str
    quest: QuestUpdate | None
    model: str | None
    fallback: bool
    sources: list[Source]


def _user_prompt(npc: Npc, req: NpcTalkRequest, book: quests.QuestBook) -> str:
    """Kompakter Kontext als User-Content: Spielertext, Position, Quest, Gedächtnis."""
    ctx = {
        "player_says": req.player_text or "(walks up to you)",
        "player": None if req.x is None else {"x": req.x, "z": req.z},
        "active_quest": book.snapshot(),
        "memory": list(MEMORY.get(npc.id, [])),
    }
    return json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))


async def run_agent(
    npc: Npc, req: NpcTalkRequest, book: quests.QuestBook
) -> TalkResult | None:
    """Tool-Loop mit Gemini. None = kein brauchbares Ergebnis (dann Fallback)."""
    cfg = agent_config(npc)
    contents: list[types.Content] = [
        types.Content(
            role="user", parts=[types.Part(text=_user_prompt(npc, req, book))]
        )
    ]
    model = config.GEMINI_MODEL_QUEST
    for _ in range(config.QUEST_MAX_STEPS):
        response, model = await gemini.agenerate(
            contents,
            model,
            cfg,
            agent=AGENT_NAME,
            attempts=config.AGENT_ATTEMPTS,
            timeout_ms=config.AGENT_DEADLINE_MS,
            use_fallback_model=False,
        )
        calls = response.function_calls
        if not calls:
            text = (response.text or "").strip()
            if not text:
                return None
            return TalkResult(text[:600], book.current(), model, False, [])

        # Modell-Turn unverändert übernehmen (Thought-Signatures)
        contents.append(response.candidates[0].content)
        parts = []
        for call in calls:
            args = dict(call.args or {})
            if call.name == "assign_quest":
                result = assign_quest(book, **_known(args, assign_quest))
                if "quest" in result:
                    line = str(args.get("npc_line") or "").strip()
                    text = line or f"Get to it: {result['quest'].objective}."
                    return TalkResult(text[:600], result["quest"], model, False, [])
            elif call.name == "lookup_place":
                result = lookup_place(**_known(args, lookup_place))
            else:
                result = {"error": f"unknown tool {call.name}"}
            parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=call.id, name=call.name, response=result
                    )
                )
            )
        contents.append(types.Content(role="user", parts=parts))
    return None


def _known(args: dict, fn) -> dict:
    """Nur Argumente, die die Tool-Funktion kennt (Modell darf keine erfinden)."""
    names = fn.__code__.co_varnames[: fn.__code__.co_argcount]
    return {k: v for k, v in args.items() if k in names and k != "book"}


def fallback_talk(
    npc: Npc, req: NpcTalkRequest, book: quests.QuestBook, why: str
) -> TalkResult:
    """Geskriptete Antwort: aktive Quest erinnern oder Fallback-Quest vergeben."""
    current = book.current()
    if current is not None:
        text = f"You still owe me one. {current.objective}."
        genai_log.log_fallback(agent=AGENT_NAME, actions=[], reason=why)
        return TalkResult(text, current, None, True, [])
    zone = None
    if req.x is not None and req.z is not None:
        zone = next(
            (
                p.id
                for p in protocol.load_pois().pois
                if (p.x - req.x) ** 2 + (p.z - req.z) ** 2 <= p.radius**2
            ),
            None,
        )
    args = quests.fallback_quest(npc_poi_id=npc.poi_id, zone_id=zone)
    update = book.create(**args)
    poi = protocol.load_pois().get(update.poi_id)
    text = (
        f"Got a job for you at {poi.name}. {poi.description} "
        f"Some thugs moved in there, take out {update.remaining} of them."
    )
    genai_log.log_fallback(
        agent=AGENT_NAME,
        actions=[{"tool": "assign_quest", "args": {**args, "reason": why}}],
        reason=why,
    )
    return TalkResult(text[:600], update, None, True, [])


async def talk(
    npc: Npc, req: NpcTalkRequest, book: quests.QuestBook | None = None
) -> TalkResult:
    """Gespräch führen: live mit Deadline, sonst oder bei jedem Fehler der Fallback."""
    book = book or quests.BOOK
    result = None
    why = "offline mode"
    if gemini.live_enabled():
        try:
            result = await asyncio.wait_for(
                run_agent(npc, req, book), config.QUEST_DEADLINE_MS / 1000
            )
            why = "agent gave no usable answer"
        except asyncio.TimeoutError:
            why = f"deadline {config.QUEST_DEADLINE_MS} ms"
        except HTTPException as e:
            why = f"gemini error {e.status_code}"
        except Exception as e:  # Spiel wartet nie, jeder Fehler -> Fallback
            log.exception("Quest-Agent fehlgeschlagen")
            why = f"agent crashed: {type(e).__name__}"
    if result is None:
        result = fallback_talk(npc, req, book, why)
    return result


@router.post("/npc/talk", response_model=NpcTalkResponse)
async def npc_talk(req: NpcTalkRequest) -> NpcTalkResponse:
    """NPC ansprechen. Immer 200 (auch im Fallback), 404 bei unbekanntem NPC."""
    npc = load_npcs().get(req.npc_id)
    if npc is None:
        raise HTTPException(404, f"unknown npc_id {req.npc_id!r}")
    book = quests.BOOK
    had_quest = book.active is not None
    result = await talk(npc, req, book)
    if req.player_text:
        remember(npc.id, f"Player: {req.player_text}")
    remember(npc.id, f"{npc.name}: {result.text}")
    if result.quest is not None and not had_quest:
        await hub_module.HUB.send_action("quest_update", result.quest)
    return NpcTalkResponse(
        npc_id=npc.id,
        text=result.text,
        quest=result.quest,
        sources=result.sources,
        model=result.model,
        fallback=result.fallback,
    )
