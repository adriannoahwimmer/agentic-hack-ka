"""PowerShell-Skripte müssen reines ASCII sein.

Zweck: Windows PowerShell 5.1 liest .ps1 ohne BOM in der ANSI-Codepage. Nicht-ASCII
(z. B. Gedankenstriche) zerbricht dann das Parsen (setup-worktree.ps1, 2026-11-14).
"""

from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parent.parent / "scripts").glob("*.ps1"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_powershell_script_is_ascii(script):
    for no, line in enumerate(script.read_bytes().splitlines(), start=1):
        assert line.isascii(), f"{script.name}:{no} enthält Nicht-ASCII: {line!r}"
