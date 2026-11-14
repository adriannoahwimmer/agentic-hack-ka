"""Zentrale Konfiguration: Modelle, Agent-Limits, Timeouts und Retries.

Zweck: einzige Quelle für diese Werte (Regel in CLAUDE.md). Jeder Wert ist per
gleichnamiger Umgebungsvariable überschreibbar.
Use-Cases: Modell je Agent wechseln, ohne Code zu ändern; Limits für Demo oder
Deploy anpassen; Tests prüfen die Defaults.

Lokal kommen die Variablen aus der .env im Projektordner (Vorlage: .env.example),
auf Codesphere aus den "Environment Variables" im UI. Bereits gesetzte
Umgebungsvariablen haben Vorrang vor der .env. Den API-Key liest nur
main.get_client(), er wird hier nicht gespeichert.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# override=False: echte Umgebung schlägt .env. Fehlt die Datei, passiert nichts.
# Tests schalten das per PYTHON_DOTENV_DISABLED ab (tests/conftest.py).
load_dotenv(Path(__file__).with_name(".env"))


ROOT = Path(__file__).resolve().parent


def _env(name: str, default: str) -> str:
    """Wert der Umgebungsvariable. Nicht gesetzt oder leer -> default."""
    return os.environ.get(name, "").strip() or default


def _env_flag(name: str, default: bool) -> bool:
    """Schalter aus der Umgebung: 1/true/yes/on -> True, 0/false/no/off -> False."""
    raw = _env(name, "").lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name}={raw!r} ist kein gültiger Schalter (1/0)")


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    """Wert aus einer festen Auswahl. Ungültig -> ValueError mit Namen."""
    value = _env(name, default).lower()
    if value not in choices:
        raise ValueError(f"{name}={value!r}, erlaubt: {', '.join(choices)}")
    return value


def _env_path(name: str, default: str) -> Path:
    """Pfad aus der Umgebung. Relative Pfade gelten ab dem Projektordner."""
    path = Path(_env(name, default))
    return path if path.is_absolute() else ROOT / path


def _env_number(name: str, default: float, cast: type = int):
    """Zahl aus der Umgebung (cast: int oder float). Ungültig -> ValueError mit Namen."""
    raw = _env(name, "")
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} ist keine gültige Zahl") from None


# --- Modelle -----------------------------------------------------------------
# Defaults nach Latenz-Messung vom 2026-11-14 (agent_docs/gemini_api.md, "Latenz"):
# 3.5-flash-lite war am schnellsten und fehlerfrei, 3.1-flash-lite am zweitschnellsten.
# gemini-3.8-flash lief in 504/503, gemini-2.5-flash-lite ist für den Key 404.
# Mehr Reasoning nur per Env, z. B. GEMINI_MODEL_AGENT=gemini-4-hydrogen oder
# gemini-4-carbon, und dann GEMINI_TIMEOUT_MS anheben.
GEMINI_MODEL_AGENT = _env("GEMINI_MODEL_AGENT", "gemini-3.5-flash-lite")  # /agent
GEMINI_MODEL_CHAT = _env("GEMINI_MODEL_CHAT", "gemini-3.5-flash-lite")  # /chat
GEMINI_MODEL_FALLBACK = _env("GEMINI_MODEL_FALLBACK", "gemini-3.1-flash-lite")

# Für /agent und /chat (auch beim Fallback). low | medium | high.
# low hält die Latenz fürs Spiel klein.
GEMINI_THINKING_LEVEL = _env("GEMINI_THINKING_LEVEL", "low")

# --- Agent-Limits ------------------------------------------------------------
MAX_AGENT_STEPS = max(1, _env_number("MAX_AGENT_STEPS", 8))  # Requests pro /agent

# --- Timeouts ----------------------------------------------------------------
# Pro Request, gilt für Agent- und Fallback-Modell. Messung vom 2026-11-14
# (Polizei-Function-Call): 3.5-flash-lite p90 0,86 s, 3.1-flash-lite bis 12,5 s.
# 15 s deckt den Fallback ab und halbiert die Wartezeit bei hängendem Primärmodell.
# Hydrogen und Carbon brauchen deutlich mehr.
GEMINI_TIMEOUT_MS = _env_number("GEMINI_TIMEOUT_MS", 15_000)
# SDK-Versuche bei Transportfehlern (Timeout, Verbindungsabbruch, 408), inkl. des ersten
GEMINI_TRANSPORT_ATTEMPTS = max(1, _env_number("GEMINI_TRANSPORT_ATTEMPTS", 2))

# --- Retries bei 5xx (main.generate) -----------------------------------------
# Versuche pro Modell (inkl. des ersten). Die Wartezeit verdoppelt sich ab
# BASE_DELAY (mit Jitter) bis höchstens MAX_DELAY. Danach kommt das Fallback-Modell.
GEMINI_RETRY_ATTEMPTS = max(1, _env_number("GEMINI_RETRY_ATTEMPTS", 3))
GEMINI_RETRY_BASE_DELAY = _env_number("GEMINI_RETRY_BASE_DELAY", 2.0, float)  # s
GEMINI_RETRY_MAX_DELAY = _env_number("GEMINI_RETRY_MAX_DELAY", 8.0, float)  # s
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
# 504 = Deadline überschritten. Das SDK schickt GEMINI_TIMEOUT_MS als X-Server-Timeout
# mit; derselbe Request am selben Modell läuft wieder hinein -> sofort zum Fallback.
FALLBACK_IMMEDIATELY_STATUS = frozenset({504})

# 429 wird nie wiederholt. Bei Tier 3 ist meist das Spend-Cap des Projekts erreicht.
SPEND_CAP_HINT = "Spend-Cap erreicht? aistudio.google.com/spend"


# =============================================================================
# Spiel (Fächerstadt Agents). Vertrag: Design.md, Abschnitt "Vertrag".
# Scheiben ändern nur Defaults in ihrem eigenen Block, keine neuen Schlüssel
# außerhalb ihres Blocks (Plan docs/plans/2026-11-14-faecherstadt.md).
# =============================================================================

# --- Kern: Modus, Budget, Log, WebSocket (Schritt 0) --------------------------
# offline: Agenten nutzen nur ihre geskripteten Fallbacks, kein Gemini-Request.
# Default offline, damit kein Prozess aus Versehen Requests verbraucht.
AGENTS_MODE = _env_choice("AGENTS_MODE", "offline", ("live", "offline"))
# Hartes Request-Budget pro Serverprozess (alle GenAI-Calls). Danach Fallbacks.
GENAI_MAX_CALLS_PER_MIN = max(1, _env_number("GENAI_MAX_CALLS_PER_MIN", 30))
GENAI_MAX_CALLS_TOTAL = max(0, _env_number("GENAI_MAX_CALLS_TOTAL", 400))
GENAI_LOG_PATH = _env_path("GENAI_LOG_PATH", "logs/genai.jsonl")
GENAI_LOG_MAX_PROMPT_CHARS = max(100, _env_number("GENAI_LOG_MAX_PROMPT_CHARS", 4000))
WS_MAX_EVENTS_PER_S = max(1, _env_number("WS_MAX_EVENTS_PER_S", 20))  # pro Client
DEBUG_ENDPOINTS = _env_flag("DEBUG_ENDPOINTS", False)  # POST /debug/action u. a.

# --- Modelle je Agent ---------------------------------------------------------
GEMINI_MODEL_POLICE = _env("GEMINI_MODEL_POLICE", GEMINI_MODEL_AGENT)
GEMINI_MODEL_GANG = _env("GEMINI_MODEL_GANG", GEMINI_MODEL_AGENT)
GEMINI_MODEL_QUEST = _env("GEMINI_MODEL_QUEST", GEMINI_MODEL_AGENT)
# Maps Grounding: laut Doku (2026-11-14) für 3.5-flash-lite unterstützt, nur Englisch.
GEMINI_MODEL_MAPS = _env("GEMINI_MODEL_MAPS", "gemini-3.5-flash-lite")
# TTS: nicht in models.list() gelistet, Live-Check in Scheibe 3 (Plan, Q0).
GEMINI_MODEL_TTS = _env("GEMINI_MODEL_TTS", "gemini-3.8-flash-lite-tts")
TTS_VOICE = _env("TTS_VOICE", "Orus")  # Prebuilt-Stimme für den Polizeifunk ("Firm")

# --- Agent-Runner (Scheibe 2: Polizei) ----------------------------------------
# Sammelfenster nach dem ersten Trigger-Event. Regel: mindestens 5 s.
AGENT_DEBOUNCE_S = max(5.0, _env_number("AGENT_DEBOUNCE_S", 5.0, float))
POLICE_MIN_INTERVAL_S = max(1.0, _env_number("POLICE_MIN_INTERVAL_S", 8.0, float))
GANG_MIN_INTERVAL_S = max(1.0, _env_number("GANG_MIN_INTERVAL_S", 15.0, float))
# Deadline pro Agent-Zyklus, danach greift der Fallback. Im Spiel kein Backoff.
AGENT_DEADLINE_MS = max(500, _env_number("AGENT_DEADLINE_MS", 6000))
AGENT_ATTEMPTS = max(1, _env_number("AGENT_ATTEMPTS", 1))  # Versuche pro Modell

# --- Fahndung und Clamps (Scheibe 2: Polizei) ---------------------------------
WANTED_MAX = max(1, _env_number("WANTED_MAX", 5))  # Level 0..WANTED_MAX
WANTED_MAX_STEP = max(1, _env_number("WANTED_MAX_STEP", 2))  # max. Änderung pro Zyklus
WANTED_DECAY_S = max(1.0, _env_number("WANTED_DECAY_S", 30.0, float))  # ohne Verbrechen
POLICE_MAX_UNITS = max(1, _env_number("POLICE_MAX_UNITS", 6))  # gleichzeitig aktiv
RADIO_MAX_CHARS = max(20, _env_number("RADIO_MAX_CHARS", 160))

# --- Quest und Maps (Scheibe 3: Quest) ----------------------------------------
QUEST_MAX_STEPS = max(1, _env_number("QUEST_MAX_STEPS", 3))  # Requests pro Gespräch
QUEST_DEADLINE_MS = max(500, _env_number("QUEST_DEADLINE_MS", 8000))
QUEST_MAX_TARGETS = max(1, _env_number("QUEST_MAX_TARGETS", 5))  # Gegner pro Quest
MAPS_CACHE_PATH = _env_path("MAPS_CACHE_PATH", "cache/maps_facts.json")

# --- TTS (Scheibe 3: Quest) ---------------------------------------------------
TTS_DEADLINE_MS = max(500, _env_number("TTS_DEADLINE_MS", 8000))
TTS_CACHE_DIR = _env_path("TTS_CACHE_DIR", "cache/tts")
