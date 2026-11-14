"""Tests für scripts/set-env-ports.ps1 (von setup-worktree.ps1 aufgerufen).

Zweck: Die Ports landen als eigene Zeilen in der Worktree-.env, auch wenn die .env
nur eine Zeile ohne Zeilenumbruch hat (früher hingen sie dann am API-Key), und die
Datei bekommt keine BOM (python-dotenv fand den Key sonst nicht).
Läuft nur, wo Windows PowerShell oder pwsh vorhanden ist.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "set-env-ports.ps1"
SHELL = shutil.which("powershell") or shutil.which("pwsh")
PORTS = ["PORT=3001", "VITE_PORT=5174", "BACKEND_URL=http://localhost:3001"]


def _run(env_file: Path) -> list[str]:
    """Skript auf env_file anwenden und die Zeilen der Ergebnisdatei liefern."""
    subprocess.run(
        [
            SHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-EnvFile",
            str(env_file),
            "-BackendPort",
            "3001",
            "-VitePort",
            "5174",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    raw = env_file.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM in .env"
    return raw.decode("utf-8").splitlines()


@pytest.mark.skipif(SHELL is None, reason="PowerShell nicht installiert")
@pytest.mark.parametrize(
    ("content", "expected_head"),
    [
        # einzeilig, ohne Zeilenumbruch am Ende (der Fehlerfall)
        ("GEMINI_API_KEY=dummy-key-value", ["GEMINI_API_KEY=dummy-key-value"]),
        # mehrzeilig, alte Ports werden ersetzt, Rest bleibt
        (
            "GEMINI_API_KEY=dummy-key-value\nPORT=9999\nAGENTS_MODE=offline\nVITE_PORT=1\n",
            ["GEMINI_API_KEY=dummy-key-value", "AGENTS_MODE=offline"],
        ),
    ],
    ids=["einzeilig", "mehrzeilig"],
)
def test_ports_on_own_lines_without_bom(tmp_path, content, expected_head):
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8", newline="")
    assert _run(env_file) == expected_head + PORTS
    assert dotenv_values(env_file)["GEMINI_API_KEY"] == "dummy-key-value"


def test_dotenv_with_utf8_sig_ignores_bom(tmp_path):
    """config.py lädt die .env mit utf-8-sig: eine alte BOM verschluckt den Key nicht."""
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"\xef\xbb\xbfGEMINI_API_KEY=dummy-key-value\nPORT=3001\n")
    assert "GEMINI_API_KEY" in dotenv_values(env_file, encoding="utf-8-sig")
    config_source = (SCRIPT.parent.parent / "config.py").read_text(encoding="utf-8")
    assert 'encoding="utf-8-sig"' in config_source
