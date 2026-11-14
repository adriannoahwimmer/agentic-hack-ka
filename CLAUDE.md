# CLAUDE.md

FastAPI-Service mit Gemini (google-genai) und Tool-Calling-Agenten als Backend für ein Browser-Spiel, deploybar auf Codesphere. Architektur und Features stehen in `Design.md`.

## Warum
Starter für einen Agentic-AI-Hackathon (Gemini + Codesphere): Neue Tools und Endpoints sollen schnell dazukommen, ohne dass die Infrastruktur neu gebaut werden muss.

## Projektkarte
- `main.py`: App mit Gemini-Client, Agent-Loop und den Endpoints `/`, `/chat`, `/agent`
- `config.py`: Modellnamen, Agent-Limits, Timeouts, Retries (einzige Quelle dafür)
- `Design.md`: Architektur und ein Abschnitt pro Feature
- `tests/`: pytest mit Fake-Gemini (`tests/fakes.py`), ruft Gemini nie live auf
- `scripts/check.ps1`, `scripts/check.sh`: ruff check, ruff format --check, pytest
- `ci.yml`: Codesphere-Pipeline (prepare + run)
- `.claude/skills/`: Google-Skills `gemini-api-dev` und `gemini-live-api-dev`
- `docs/research/`, `docs/plans/`: Artefakte von /research_codebase und /create_plan
- Stack: Python 3.10+, FastAPI, uvicorn, google-genai; ruff und pytest in `requirements-dev.txt`

## Arbeitsweise
- Starten: `.venv\Scripts\uvicorn main:app --reload --port 3000` (Swagger unter /docs)
- Verifizieren: `scripts\check.ps1` (bash: `scripts/check.sh`). Muss grün sein und läuft auch als Stop-Hook.
- Das Repo wird public. Secrets (`GEMINI_API_KEY` u. a.) nur aus der Umgebung lesen, nie in Code, Tests, Logs oder Commits.

<important if="du baust ein Feature oder schreibst neuen Code">
- Eine Datei pro Feature. Jede Datei beginnt mit einem Kopfkommentar: Zweck und Use-Cases.
- Docstrings für jedes Modul, jede Klasse und jede Funktion (im Frontend JSDoc).
- Das Feature in `Design.md` im eigenen Abschnitt dokumentieren und bei Änderungen nachziehen.
</important>

<important if="du schreibst oder änderst Code, der Gemini aufruft (Agenten, Tools, Live API)">
- Zuerst den Skill `gemini-api-dev` laden, für die Live API `gemini-live-api-dev`. Modelle und SDK nicht aus dem Gedächtnis nehmen. Was der Hackathon-Key wirklich kann, zeigt `client.models.list()`.
- Modellnamen und Agent-Limits (Schritte, Timeouts, Retries) nur in `config.py`, per Env-Var überschreibbar. Nie im Feature-Code hartkodieren.
- Jeden GenAI-Call als eine JSON-Zeile loggen (JSON Lines): Zeitstempel, Agent, Modell, Prompt, Config, Output. Inline-Daten (Bilder, Audio, Bytes) nur als Platzhalter mit MIME-Typ und Größe. Das Agent-Log-Overlay im Spiel liest dieses Format. Log-Dateien nach `logs/` (gitignored).
- Keine Keys, Tokens oder Auth-Header ins Log.
- Retries nur bei 5xx, nie bei 429 (Tier-3-Account: 429 heißt Spend-Cap erreicht). Bei 503 auf das Fallback-Modell aus `config.py` ausweichen.
- Zum Testen nicht live aufrufen. Jeder Agent-Schritt ist ein bezahlter Request.
- Den Modell-Turn unverändert in den Verlauf übernehmen (Thought-Signatures) und Tool-Ergebnisse mit `id` zurückgeben (siehe `agent()` in main.py).
- Neues Tool: Funktion schreiben, in `TOOLS` eintragen, in `TOOL_DECLARATIONS` deklarieren. Fehler als `{"error": ...}` zurückgeben, nicht werfen.
</important>

<important if="du fügst Python-Abhängigkeiten hinzu oder änderst sie">
- Laufzeit-Pakete gehören nach `requirements.txt` (wird auf Codesphere installiert), Dev-Tools nur nach `requirements-dev.txt`.
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
