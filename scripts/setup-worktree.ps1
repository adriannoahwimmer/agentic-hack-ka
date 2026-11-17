# setup-worktree.ps1 - legt einen Feature-Worktree fuer Faecherstadt Agents an.
# Aufruf im Hauptordner des Repos (z. B. C:\code\agentic-hack-ka):
#   .\scripts\setup-worktree.ps1 polizei  3001 5174
#   .\scripts\setup-worktree.ps1 quest    3002 5175
#   .\scripts\setup-worktree.ps1 welt     3003 5173   (Welt nutzt Vite 5173; 3000 bleibt fuer main frei)
# Erst ausfuehren, NACHDEM Schritt 0 (Design.md + protocol.py + Plan) auf main committet ist.

param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][int]$BackendPort,
    [int]$VitePort = 5173
)
$ErrorActionPreference = 'Stop'

$main = (git rev-parse --show-toplevel).Trim()
$wt   = Join-Path (Split-Path $main -Parent) "ka-$Name"
$branch = "feat/$Name"

# 1. Sauberer Stand pruefen
if (git -C $main status --porcelain) { throw "Hauptordner hat uncommittete Aenderungen - erst Schritt 0 committen." }

# 2. Worktree + Branch
if (Test-Path $wt) { Write-Host "Worktree $wt existiert schon - ueberspringe git worktree add." }
else { git -C $main worktree add $wt -b $branch }

# 3. .env kopieren und Ports setzen (Key bleibt nur lokal, .env ist gitignored)
$envSrc = Join-Path $main '.env'
$envDst = Join-Path $wt '.env'
if (-not (Test-Path $envSrc)) { throw ".env im Hauptordner fehlt." }
Copy-Item $envSrc $envDst -Force
# Ports setzen: Array-sicher (auch bei einzeiliger .env) und ohne BOM.
& (Join-Path $PSScriptRoot 'set-env-ports.ps1') -EnvFile $envDst -BackendPort $BackendPort -VitePort $VitePort

# 4. Python-venv
Push-Location $wt
try {
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
    # requirements-dev.txt = requirements.txt + ruff/pytest/httpx; ohne sie scheitert check.ps1 (Stop-Hook).
    if (Test-Path requirements-dev.txt) { & .\.venv\Scripts\python.exe -m pip install -q -r requirements-dev.txt }
    elseif (Test-Path requirements.txt) { & .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt }
    elseif (Test-Path pyproject.toml)   { & .\.venv\Scripts\python.exe -m pip install -q -e . }

    # 5. Frontend
    if (Test-Path frontend\package.json) {
        Push-Location frontend
        if (Test-Path package-lock.json) { npm ci } else { npm install }
        Pop-Location
    }

    # 6. Schnelltest
    if (Test-Path scripts\check.ps1) { & .\scripts\check.ps1 }
}
finally { Pop-Location }

Write-Host ""
Write-Host "Fertig: $wt  (Branch $branch, Backend :$BackendPort, Vite :$VitePort)"
Write-Host "Start Backend:  .\.venv\Scripts\uvicorn main:app --port $BackendPort --reload"
Write-Host "Start Vite:     cd frontend; npm run dev -- --port $VitePort"
code $wt
