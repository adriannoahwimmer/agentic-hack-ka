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


def _env(name: str, default: str) -> str:
    """Wert der Umgebungsvariable. Nicht gesetzt oder leer -> default."""
    return os.environ.get(name, "").strip() or default


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
