"""Hermetische Testumgebung: welche Umgebungsvariablen config.py liest, und Aufräumen.

Zweck: conftest.py entfernt diese Variablen vor dem Import von config, damit weder die
lokale .env noch die Shell eines Worktrees (z. B. DEBUG_ENDPOINTS=1) Tests beeinflusst.
Darf config selbst nicht importieren.
"""

import os
import re
from pathlib import Path

_CONFIG_SOURCE = (Path(__file__).resolve().parent.parent / "config.py").read_text(
    encoding="utf-8"
)

# Alle Namen aus _env("X", ...), _env_number("X", ...), _env_flag(...) usw. in config.py
CONFIG_ENV_VARS = frozenset(
    re.findall(r'_env\w*\(\s*"([A-Z][A-Z0-9_]*)"', _CONFIG_SOURCE)
) | {"GEMINI_API_KEY", "GOOGLE_API_KEY"}


def clear_config_env() -> None:
    """.env-Laden abschalten und jede von config.py gelesene Variable entfernen."""
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    for name in CONFIG_ENV_VARS:
        os.environ.pop(name, None)
