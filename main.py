"""FastAPI-App von Fächerstadt Agents: Healthcheck, Starter-Endpoints, Spiel und Feature-Loader.

Zweck: setzt die App zusammen. Gemini-Zugriff liegt in gemini.py, der Event-/Action-Bus
in hub.py, die WebSocket-Verbindung in ws.py. Feature-Module (Spielzustand, Agenten,
TTS ...) werden über FEATURE_MODULES geladen; Feature-Scheiben ändern diese Datei nicht.
Use-Cases: Healthcheck für Codesphere (GET /), Debuggen von Modell und Key (/chat),
Tool-Loop ausprobieren (/agent), Spiel unter /play/ (Build aus frontend/ nach static/).

Start lokal:  uvicorn main:app --reload --port 3000
Modelle, Limits, Timeouts und Retries stehen in config.py. Der API-Key kommt
ausschließlich aus der Umgebungsvariable GEMINI_API_KEY (lokal aus der .env).
"""

import ast
import asyncio
import importlib
import logging
import operator
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from google.genai import types

import config
import gemini
import hub as hub_module
import ws

log = logging.getLogger(__name__)

# Feature-Module in Handler-Reihenfolge: erst Zustand, dann Agenten (Design.md, "Vertrag").
# Jedes exportiert register(hub) und optional router, startup(), shutdown().
# Fehlt ein Modul, wird es übersprungen.
FEATURE_MODULES = (
    "game_state",
    "quests",
    "runner",
    "maps_facts",
    "tts",
    "agents.police",
    "agents.gang",
    "agents.quest",
)
STATIC_DIR = config.ROOT / "static"


# --------------------------------------------------------------------------
# Feature-Loader und Lebenszyklus
# --------------------------------------------------------------------------
def load_features(
    app: FastAPI, hub: hub_module.Hub, names: tuple[str, ...] = FEATURE_MODULES
) -> list[str]:
    """Vorhandene Feature-Module laden: register(hub), Router einhängen, Hooks merken.

    Fehlt ein Modul selbst, wird es übersprungen. Fehlt etwas, das ein Modul
    importiert, bricht der Start ab (kein stilles Verschlucken von Bugs).
    """
    hooks = app.state.feature_hooks
    loaded = []
    for name in names:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name == name or name.startswith(f"{e.name}."):
                log.info("Feature %s nicht vorhanden, übersprungen", name)
                continue
            raise
        if hasattr(module, "register"):
            module.register(hub)
        if getattr(module, "router", None) is not None:
            app.include_router(module.router)
        for kind in ("startup", "shutdown"):
            if callable(getattr(module, kind, None)):
                hooks[kind].append(getattr(module, kind))
        loaded.append(name)
    log.info("Features geladen: %s", ", ".join(loaded) or "keine")
    return loaded


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Hub an den Event-Loop binden, Feature-Hooks starten und beim Ende stoppen."""
    hub = hub_module.HUB
    hub.start(asyncio.get_running_loop())
    for hook in app.state.feature_hooks["startup"]:
        await hook()
    try:
        yield
    finally:
        for hook in reversed(app.state.feature_hooks["shutdown"]):
            await hook()
        hub.stop()


def mount_static(app: FastAPI, directory: Path = STATIC_DIR) -> bool:
    """Spiel-Build unter /play/ ausliefern, falls vorhanden. GET / bleibt der Healthcheck."""
    if not (directory / "index.html").is_file():
        log.info("Kein Spiel-Build in %s (npm --prefix frontend run build)", directory)
        return False
    app.mount("/play", StaticFiles(directory=directory, html=True), name="play")
    return True


app = FastAPI(title="Fächerstadt Agents", lifespan=lifespan)
app.state.feature_hooks = {"startup": [], "shutdown": []}
app.include_router(ws.router)


# --------------------------------------------------------------------------
# Tools für den Starter-Agenten (/agent)
# --------------------------------------------------------------------------
def get_time() -> dict:
    """Aktuelle Zeit in UTC und Serverzeit."""
    return {
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "server_local": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node):
    """Arithmetischen AST-Knoten auswerten (nur Zahlen und Grundrechenarten)."""
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponent zu groß (max. 100)")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Erlaubt sind nur Zahlen, + - * / // % ** und Klammern")


def calculator(expression: str) -> dict:
    """Sicherer Rechner ohne eval()."""
    try:
        return {
            "expression": expression,
            "result": _eval(ast.parse(expression, mode="eval").body),
        }
    except Exception as e:  # noqa: BLE001 - Tool-Grenze: Fehler geht als Ergebnis ans Modell
        return {"expression": expression, "error": str(e)}


# Name -> Python-Funktion. Neue Tools: Funktion schreiben, hier eintragen,
# und unten in TOOL_DECLARATIONS beschreiben.
TOOLS = {"get_time": get_time, "calculator": calculator}

TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="get_time",
            description="Liefert das aktuelle Datum und die aktuelle Uhrzeit (UTC und Serverzeit).",
        ),
        types.FunctionDeclaration(
            name="calculator",
            description="Berechnet einen arithmetischen Ausdruck exakt. Für jede Rechnung verwenden.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Python-artiger Ausdruck, z. B. '(17 * 23) / 4 + 2**8'",
                    }
                },
                "required": ["expression"],
            },
        ),
    ]
)

THINKING = types.ThinkingConfig(thinking_level=config.GEMINI_THINKING_LEVEL)

CHAT_CONFIG = types.GenerateContentConfig(thinking_config=THINKING)

AGENT_CONFIG = types.GenerateContentConfig(
    system_instruction=(
        "Du bist ein hilfreicher Agent. Nutze die verfügbaren Tools, wenn sie helfen: "
        "get_time für Datum/Uhrzeit, calculator für jede Rechnung. Antworte knapp."
    ),
    tools=[TOOL_DECLARATIONS],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    thinking_config=THINKING,
)


def run_tool(name: str, args: dict) -> dict:
    """Tool aus TOOLS ausführen. Fehler gehen als {"error": ...} ans Modell zurück."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"Unbekanntes Tool: {name}"}
    try:
        return fn(**args)
    except Exception as e:  # noqa: BLE001 - Tool-Grenze, z. B. falsche Argumente vom Modell
        return {"error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/")
def health():
    """Healthcheck für Codesphere. Ruft Gemini nie auf."""
    return {
        "status": "ok",
        "models": {
            "agent": config.GEMINI_MODEL_AGENT,
            "chat": config.GEMINI_MODEL_CHAT,
            "fallback": config.GEMINI_MODEL_FALLBACK,
        },
        "gemini_key_configured": bool(os.environ.get("GEMINI_API_KEY")),
        "agents_mode": config.AGENTS_MODE,
        "genai_calls": gemini.BUDGET.total,
    }


@app.get("/chat")
def chat(q: str):
    """Einzelne Frage an das Chat-Modell, ohne Tools."""
    response, model = gemini.generate(
        q, config.GEMINI_MODEL_CHAT, CHAT_CONFIG, agent="chat"
    )
    return {"answer": response.text, "model": model}


@app.get("/agent")
def agent(q: str):
    """Tool-Loop mit dem Agent-Modell. Antwort enthält jeden Tool-Schritt."""
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=q)])
    ]
    steps = []
    model = config.GEMINI_MODEL_AGENT

    for _ in range(config.MAX_AGENT_STEPS):
        # Nach einem Fallback bleibt der Loop beim Fallback-Modell, damit nicht
        # zwei Modelle abwechselnd die Thought-Signatures des anderen bekommen.
        response, model = gemini.generate(
            contents, model, AGENT_CONFIG, agent="starter"
        )
        calls = response.function_calls
        if not calls:
            return {"answer": response.text, "model": model, "steps": steps}

        # Antwort des Modells (inkl. Thought-Signatures) unverändert in den Verlauf übernehmen
        contents.append(response.candidates[0].content)

        result_parts = []
        for call in calls:
            args = dict(call.args or {})
            result = run_tool(call.name, args)
            steps.append({"tool": call.name, "args": args, "result": result})
            result_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=call.id, name=call.name, response=result
                    )
                )
            )
        contents.append(types.Content(role="user", parts=result_parts))

    raise HTTPException(
        500,
        f"Agent hat das Limit von {config.MAX_AGENT_STEPS} Schritten erreicht: {steps}",
    )


# Features zuletzt laden (sie dürfen main nicht importieren), Spiel-Build als letzter Mount.
load_features(app, hub_module.HUB)
mount_static(app)
