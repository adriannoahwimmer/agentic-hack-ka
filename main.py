"""Hackathon-Starter: FastAPI + Gemini mit einfachem Tool-Calling-Agenten.

Zweck: Gemini-Client mit Retry/Fallback (generate), Beispiel-Tools und die
Starter-Endpoints. Use-Cases: Healthcheck für Codesphere (GET /), Debuggen von
Modell und Key (/chat), Tool-Loop ausprobieren (/agent).

Start lokal:  uvicorn main:app --reload --port 3000
Modelle, Limits, Timeouts und Retries stehen in config.py. Der API-Key kommt
ausschließlich aus der Umgebungsvariable GEMINI_API_KEY (lokal aus der .env).
"""

import ast
import logging
import operator
import os
import random
import time
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from google import genai
from google.genai import errors, types

import config

log = logging.getLogger(__name__)
_sleep = time.sleep  # Tests ersetzen das, damit Backoff nicht wirklich wartet

app = FastAPI(title="Hackathon Starter")


# --------------------------------------------------------------------------
# Gemini-Client (lazy, damit der Healthcheck auch ohne API-Key antwortet)
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Gecachter Gemini-Client. Wirft, wenn GEMINI_API_KEY fehlt."""
    # api_key explizit, damit ein evtl. gesetztes GOOGLE_API_KEY nicht gewinnt.
    # SDK-Retries nur für Transportfehler (Timeout, Verbindungsabbruch) und 408.
    # 5xx, Fallback-Modell und 429 behandelt generate() selbst.
    return genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
        http_options=types.HttpOptions(
            timeout=config.GEMINI_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(
                attempts=config.GEMINI_TRANSPORT_ATTEMPTS,
                initial_delay=2.0,
                max_delay=8.0,
                http_status_codes=[408],
            ),
        ),
    )


def backoff_delay(attempt: int) -> float:
    """Wartezeit nach dem Fehlversuch Nr. `attempt` (ab 0): exponentiell, mit Jitter."""
    ceiling = min(
        config.GEMINI_RETRY_MAX_DELAY, config.GEMINI_RETRY_BASE_DELAY * 2**attempt
    )
    return ceiling * random.uniform(0.5, 1.0)


def generate(
    contents, model: str, gen_config: types.GenerateContentConfig | None = None
) -> tuple[types.GenerateContentResponse, str]:
    """Ruft Gemini auf und gibt (Antwort, tatsächlich genutztes Modell) zurück.

    - 500/502/503: bis zu GEMINI_RETRY_ATTEMPTS Versuche mit Backoff, danach
      dasselbe mit GEMINI_MODEL_FALLBACK. Sind beide überlastet: HTTP 503.
    - 504 (Deadline überschritten): ohne Retry direkt zum Fallback-Modell.
    - 429: sofort HTTP 429 mit Spend-Cap-Hinweis. Kein Retry, kein Fallback.
    - Andere Gemini-Fehler (400, 403, 404 ...): HTTP 502.
    """
    try:
        client = get_client()
    except Exception as e:  # noqa: BLE001 - jede Client-Init-Panne -> 500 statt Crash
        raise HTTPException(
            500, f"Gemini-Client nicht verfügbar (GEMINI_API_KEY gesetzt?): {e}"
        )

    models = [model]
    if config.GEMINI_MODEL_FALLBACK != model:
        models.append(config.GEMINI_MODEL_FALLBACK)

    last_error: errors.APIError | None = None
    for current in models:
        if current != model:
            log.warning("Gemini: %s überlastet, weiche auf %s aus", model, current)
        for attempt in range(config.GEMINI_RETRY_ATTEMPTS):
            if attempt:
                _sleep(backoff_delay(attempt - 1))
            try:
                response = client.models.generate_content(
                    model=current, contents=contents, config=gen_config
                )
                return response, current
            except errors.APIError as e:
                if e.code == 429:
                    raise HTTPException(
                        429,
                        f"Gemini 429 bei {current}: {config.SPEND_CAP_HINT} ({e.message})",
                    ) from e
                if e.code not in config.RETRYABLE_STATUS:
                    raise HTTPException(
                        502, f"Gemini-Fehler {e.code} bei {current}: {e.message}"
                    ) from e
                last_error = e
                log.warning(
                    "Gemini %s bei %s (Versuch %d/%d): %s",
                    e.code,
                    current,
                    attempt + 1,
                    config.GEMINI_RETRY_ATTEMPTS,
                    e.message,
                )
                if e.code in config.FALLBACK_IMMEDIATELY_STATUS:
                    break  # gleiche Deadline am gleichen Modell hilft nicht

    raise HTTPException(
        503,
        f"Gemini überlastet ({' -> '.join(models)}), "
        f"zuletzt {last_error.code}: {last_error.message}",
    )


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
    }


@app.get("/chat")
def chat(q: str):
    """Einzelne Frage an das Chat-Modell (NPC-Dialoge), ohne Tools."""
    response, model = generate(q, config.GEMINI_MODEL_CHAT, CHAT_CONFIG)
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
        response, model = generate(contents, model, AGENT_CONFIG)
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
