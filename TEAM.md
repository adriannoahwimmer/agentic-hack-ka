# Team-Workflow

## Setup
```powershell
git clone https://github.com/adriannoahwimmer/agentic-hack-ka.git
cd agentic-hack-ka
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt   # = requirements.txt + ruff/pytest für den Check
copy .env.example .env                              # danach eigenen GEMINI_API_KEY eintragen
```
Starten: `.venv\Scripts\uvicorn main:app --reload --port 3000` (bash: `.venv/bin/...`, `cp` statt `copy`).

## Gemini-Keys
- Jeder nutzt seinen **eigenen** Hackathon-Key in der eigenen `.env`.
- Keys nie teilen, nie committen, nicht in Chat, Logs oder Screenshots. `.env` ist gitignored.

## Branches und PRs
- Jeder arbeitet auf einem eigenen Branch: `feat/<scheibe>`.
- Kein direkter Push auf `main`. Gemergt wird nur per Pull Request.
- Vor jedem Push muss `scripts\check.ps1` grün sein (bash: `scripts/check.sh`).

## Tests
- Gemini in Tests immer mocken: Fixture `fake_gemini` und Builder aus `tests/fakes.py`.
  Jeder Live-Call zieht vom Request-Limit ab und riskiert die Missbrauchsgrenze des Keys.

## Zeitplan
- **Deadline 19:00.** Ab 18:00 nur noch Bugfixes, keine neuen Features.
