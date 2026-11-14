# set-env-ports.ps1 - setzt PORT, VITE_PORT und BACKEND_URL in einer .env.
# Alte Werte dieser drei Schluessel werden ersetzt, alle anderen Zeilen bleiben.
# Aufruf (macht setup-worktree.ps1):
#   .\scripts\set-env-ports.ps1 -EnvFile ..\ka-polizei\.env -BackendPort 3001 -VitePort 5174
# Getestet in tests/test_setup_scripts.py.

param(
    [Parameter(Mandatory)][string]$EnvFile,
    [Parameter(Mandatory)][int]$BackendPort,
    [int]$VitePort = 5173
)
$ErrorActionPreference = 'Stop'

$path = (Resolve-Path -LiteralPath $EnvFile).Path

# @(...) erzwingt ein Array: Bei einer einzeiligen .env liefert Get-Content sonst
# einen String, und += haengt die Ports direkt an den Key an.
$lines = @(Get-Content -LiteralPath $path | Where-Object { $_ -notmatch '^(PORT|VITE_PORT|BACKEND_URL)=' })
$lines += "PORT=$BackendPort"
$lines += "VITE_PORT=$VitePort"
$lines += "BACKEND_URL=http://localhost:$BackendPort"

# Jede Zeile mit eigenem Zeilenumbruch, UTF-8 OHNE BOM. Set-Content -Encoding utf8
# schreibt in PowerShell 5.1 eine BOM; python-dotenv liest die erste Zeile dann als
# "<BOM>GEMINI_API_KEY" und findet den Key nicht.
[System.IO.File]::WriteAllLines($path, [string[]]$lines, (New-Object System.Text.UTF8Encoding $false))
