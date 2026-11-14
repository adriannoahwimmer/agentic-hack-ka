# Codesphere-Deployment

Quellen: docs.codesphere.com, Seiten `workspace-toolkit/deployment/configuring-ci-pipeline`,
`configuring-a-landscape`, `landscape-networking` und `environment-variables` (gelesen am 2026-11-13).
Auf Codesphere ist noch nichts deployt. Alles hier ist aus der Doku abgeleitet.

## ci.yml
- `schemaVersion: v0.5` (ci.yml:3). Die Top-Level-Stufen sind `prepare` und `run`. Eine separate Test-Stufe gibt es laut Doku nicht mehr. Tests können als Schritt in `prepare` laufen.
- **prepare** (ci.yml:5-10): legt das venv `.venv` im Projektordner an und führt `pip install -r requirements.txt` aus.
  - Grund für das venv: Nur `/home/user/app` wird zwischen dem Prepare-Pod und den Run-Pods persistiert.
  - Ein globales `pip install` oder `--user` landet woanders und fehlt beim Start.
- **run** (ci.yml:12-23): Service `api` startet `.venv/bin/uvicorn main:app --host 0.0.0.0 --port 3000`.
  - `network.ports: [3000]`
  - `healthEndpoint: http://localhost:3000/` (ci.yml:21)
- Port 3000 ist der Standardport für den Codesphere-Healthcheck. `GET /` (main.py:230-241) antwortet ohne Gemini-Aufruf.
- Ein Service allein ist automatisch das Gateway. Ein Router-Service ist nicht nötig.

## Umgebungsvariablen
- `GEMINI_API_KEY` im UI unter "Environment Variables" anlegen ("+ Add New Variable"). Der Wert wird danach maskiert angezeigt.
- Optional alle Variablen aus `.env.example` (Modelle, Thinking-Level, Limits, Timeouts, Retries). Leer lassen heißt Default aus `config.py`.
- `config.py` lädt eine `.env` nur, wenn sie existiert. Auf Codesphere gibt es keine, dort zählen allein die UI-Variablen.
- Alternative mit Vault-Secret: als Kommentar vorbereitet in ci.yml:24-27 (`${{ vault.GEMINI_API_KEY }}`).
- Änderungen auf Workspace-Ebene greifen erst in einem neu geöffneten Terminal.
- Nach dem Deploy prüfen, ob `GET /` `"gemini_key_configured": true` meldet.

## Manuelle Schritte im UI
1. Workspace aus dem GitHub-Repo `hackathon-starter` anlegen (privat, Codesphere braucht GitHub-Zugriff). Den genauen Ablauf beschreibt die gelesene Doku nicht.
2. Env-Variablen setzen (siehe oben).
3. Unter Deploy -> Landscape Config Editor prüfen, ob ci.yml geladen ist, Plan wählen, dann "Save Changes".
4. Im Execution Manager zuerst Prepare, dann Run starten.
5. Die Dev-Domain öffnen und `/` sowie `/docs` testen.

## Offene Punkte
- **Plan-ID**: `plan: 20` (ci.yml:18) stammt aus einem Doku-Beispiel und ist nicht verifiziert. `plan` ist laut Doku Pflicht. Die gültigen IDs zeigt das UI.
- **Python im Base-Image**: Die Doku sagt nicht, ob `python3` mit `venv`/`ensurepip` vorinstalliert ist. Falls Prepare an `python3 -m venv` scheitert, gibt es zwei Auswege:
  - Python per Nix holen: `nix-env -iA nixpkgs.python3`
  - auf `uv` umstellen, das ist das einzige Python-Beispiel in der Doku: `uv run uvicorn main:app --port 3000 --host 0.0.0.0`
- **Python-Version**: unbekannt. Der Code zielt deshalb auf 3.10+ (ruff `target-version`, pyproject.toml).
- Dass ci.yml im Repo-Root liegen muss, ist aus den Profilen `ci.<profil>.yml` abgeleitet und nicht explizit dokumentiert.
