#!/usr/bin/env bash
# Backpressure-Check: ruff check, ruff format --check, pytest -x -q und, falls
# frontend/node_modules existiert, der Frontend-Build (npm run build -> static/).
# Erfolg: je Stufe nur "✓ <stufe>". Fehler: "✗ <stufe>" + volle Ausgabe der Stufe.
# --hook: bei Erfolg still, bei Fehler alles auf stderr und Exit-Code 2 (Claude-Code-Stop-Hook).
set -u
cd "$(dirname "$0")/.."

if [ -x .venv/bin/python ]; then PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
else PY=python3; fi

HOOK=0
[ "${1:-}" = "--hook" ] && HOOK=1
failed=0
report=""

run_stage() {
  local name=$1; shift
  local tmp code
  tmp=$(mktemp)
  "$@" >"$tmp" 2>&1
  code=$?
  if [ "$code" -eq 0 ]; then
    [ "$HOOK" -eq 1 ] || echo "✓ $name"
  else
    failed=1
    local text
    text="✗ $name (exit $code)"$'\n'"$(cat "$tmp")"
    if [ "$HOOK" -eq 1 ]; then report+="$text"$'\n'; else printf '%s\n' "$text"; fi
  fi
  rm -f "$tmp"
}

run_stage "ruff check" "$PY" -m ruff check .
run_stage "ruff format" "$PY" -m ruff format --check .
run_stage "pytest" "$PY" -m pytest -x -q
if [ -d frontend/node_modules ]; then
  run_stage "frontend build" npm --prefix frontend run build
fi

if [ "$failed" -eq 1 ]; then
  if [ "$HOOK" -eq 1 ]; then printf '%s' "$report" >&2; exit 2; fi
  exit 1
fi
exit 0
