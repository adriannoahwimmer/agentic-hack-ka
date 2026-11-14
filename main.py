"""Hackathon-Starter: FastAPI + Gemini mit einfachem Tool-Calling-Agenten.

Start lokal:  uvicorn main:app --reload --port 3000
Der API-Key kommt ausschließlich aus der Umgebungsvariable GEMINI_API_KEY.
"""

import ast
import operator
import os
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from google import genai
from google.genai import errors, types

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
MAX_AGENT_STEPS = 8

app = FastAPI(title="Hackathon Starter")


# --------------------------------------------------------------------------
# Gemini-Client (lazy, damit der Healthcheck auch ohne API-Key antwortet)
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    # Liest GEMINI_API_KEY aus der Umgebung. Retries nur bei Server-Überlast (5xx);
    # 429 (Quota) bewusst NICHT, sonst verbrennen Retries das Tageskontingent.
    return genai.Client(
        http_options=types.HttpOptions(
            timeout=60_000,  # ms
            retry_options=types.HttpRetryOptions(
                attempts=3,
                initial_delay=2.0,
                max_delay=8.0,
                http_status_codes=[500, 502, 503, 504],
            ),
        )
    )


def generate(contents, config: types.GenerateContentConfig | None = None):
    try:
        client = get_client()
    except Exception as e:  # noqa: BLE001 - jede Client-Init-Panne -> 500 statt Crash
        raise HTTPException(
            500, f"Gemini-Client nicht verfügbar (GEMINI_API_KEY gesetzt?): {e}"
        )
    try:
        return client.models.generate_content(
            model=MODEL, contents=contents, config=config
        )
    except errors.APIError as e:
        raise HTTPException(502, f"Gemini-Fehler {e.code}: {e.message}")


# --------------------------------------------------------------------------
# Tools für den Agenten
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

AGENT_CONFIG = types.GenerateContentConfig(
    system_instruction=(
        "Du bist ein hilfreicher Agent. Nutze die verfügbaren Tools, wenn sie helfen: "
        "get_time für Datum/Uhrzeit, calculator für jede Rechnung. Antworte knapp."
    ),
    tools=[TOOL_DECLARATIONS],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)


def run_tool(name: str, args: dict) -> dict:
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
    return {
        "status": "ok",
        "model": MODEL,
        "gemini_key_configured": bool(os.environ.get("GEMINI_API_KEY")),
    }


@app.get("/chat")
def chat(q: str):
    response = generate(q)
    return {"answer": response.text}


@app.get("/agent")
def agent(q: str):
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=q)])
    ]
    steps = []

    for _ in range(MAX_AGENT_STEPS):
        response = generate(contents, AGENT_CONFIG)
        calls = response.function_calls
        if not calls:
            return {"answer": response.text, "steps": steps}

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
        500, f"Agent hat das Limit von {MAX_AGENT_STEPS} Schritten erreicht: {steps}"
    )
