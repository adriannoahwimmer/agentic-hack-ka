# CLAUDE.md

FastAPI-Service mit Gemini (google-genai) und einem einfachen Tool-Calling-Agenten, deploybar auf Codesphere.

## Warum
Starter für einen Agentic-AI-Hackathon (Gemini + Codesphere): Neue Tools und Endpoints sollen schnell dazukommen, ohne dass die Infrastruktur neu gebaut werden muss.

## Projektkarte
- `main.py`: gesamte App mit Gemini-Client, Tools und den Endpoints `/`, `/chat`, `/agent`
- `tests/`: pytest mit Fake-Gemini (`tests/fakes.py`), ruft Gemini nie live auf
- `scripts/check.ps1`, `scripts/check.sh`: ruff check, ruff format --check, pytest
- `ci.yml`: Codesphere-Pipeline (prepare + run)
- `docs/research/`, `docs/plans/`: Artefakte von /research_codebase und /create_plan
- Stack: Python 3.10+, FastAPI, uvicorn, google-genai; ruff und pytest in `requirements-dev.txt`

## Arbeitsweise
- Starten: `.venv\Scripts\uvicorn main:app --reload --port 3000` (Swagger unter /docs)
- Verifizieren: `scripts\check.ps1` (bash: `scripts/check.sh`). Muss grün sein und läuft auch als Stop-Hook.
- Modell nur über die Umgebungsvariable `GEMINI_MODEL` wechseln (Default in main.py:17).
- API-Keys (`GEMINI_API_KEY`) nur aus der Umgebung lesen. Nie in Dateien, Tests oder Commits schreiben.

<important if="du fügst Python-Abhängigkeiten hinzu oder änderst sie">
- Laufzeit-Pakete gehören nach `requirements.txt` (wird auf Codesphere installiert), Dev-Tools nur nach `requirements-dev.txt`.
</important>

<important if="du änderst Gemini-Aufrufe, den Agent-Loop oder Tools in main.py">
- Free Tier: ca. 20 Requests/Tag pro Modell, und jeder Agent-Schritt ist ein Request. Zum Testen nicht live aufrufen.
- Retries nur bei 5xx, nie bei 429 (main.py:33-38).
- Den Modell-Turn unverändert in den Verlauf übernehmen (Thought-Signatures) und Tool-Ergebnisse mit `id` zurückgeben (main.py:185-199).
- Neues Tool: Funktion schreiben, in `TOOLS` (main.py:108) eintragen, in `TOOL_DECLARATIONS` (main.py:110) deklarieren. Fehler als `{"error": ...}` zurückgeben, nicht werfen.
</important>

<important if="du schreibst oder änderst Tests">
- Gemini nie live aufrufen: die Fixture `fake_gemini` (tests/conftest.py) und die Builder aus tests/fakes.py nutzen. Eine autouse-Fixture blockiert den echten Client.
</important>

<important if="du deployst auf Codesphere oder änderst ci.yml">
- Die App lauscht auf `0.0.0.0:3000`. `GET /` ist der Healthcheck und darf Gemini nicht aufrufen.
- Abhängigkeiten gehören in die `.venv` im Projektordner, denn nur `/home/user/app` wird persistiert.
- Den Key im Codesphere-UI unter "Environment Variables" setzen, nicht in ci.yml.
</important>

## Weitere Doku (bei Bedarf lesen)
- `agent_docs/gemini_api.md`: SDK, Tool-Loop, Retry-Logik, Quota, Mocking
- `agent_docs/codesphere_deploy.md`: ci.yml, Env-Vars, UI-Schritte, offene Punkte (Plan-ID, Python im Image)
