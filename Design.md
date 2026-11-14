# Design

Lebendes Design-Dokument. Jedes Feature bekommt unter "Features" einen eigenen Abschnitt, der bei jeder Änderung nachgezogen wird (Regel in CLAUDE.md).

## Architektur

```
Browser                                Server (Codesphere, 0.0.0.0:3000)
  Three.js   Rendering                   FastAPI (main.py)
  Rapier     Physik          WebSocket     Agenten:
  OSM-Stadt  vorgebacken   <----------->     Polizei-Dispatcher
  Agent-Log-Overlay                          Gang-Boss
                                             Quest-NPC
                                               |
                                               | google-genai
                                               v
                                             Gemini API
```

### Frontend
- Three.js für das Rendering, Rapier für die Physik. Beides läuft im Browser.
- Das Agent-Log-Overlay zeigt die GenAI-Calls der Agenten live an (Format siehe "Querschnitt").

### Backend
- FastAPI. Der Spielverkehr läuft über WebSocket.
- HTTP-Endpoints: `GET /` (Healthcheck, ruft Gemini nie auf), `/chat` und `/agent` aus dem Starter zum Debuggen.

### Agenten
- Polizei-Dispatcher, Gang-Boss, Quest-NPC. Jeder Agent bekommt eine eigene Datei und einen eigenen Abschnitt unter "Features".
- Modell und Limits je Agent kommen aus `config.py`.

### Karte (OpenStreetMap, vorgebacken)
- OSM-Daten werden vorab in statische Assets umgewandelt und mit dem Frontend ausgeliefert. Zur Laufzeit gibt es keine OSM-Abfragen.
- Die Lizenz (ODbL) verlangt den Hinweis "© OpenStreetMap-Mitwirkende" im Spiel.

### Querschnitt
- Konfiguration: Modellnamen, Agent-Limits, Timeouts und Retries nur in `config.py`, per Env-Var überschreibbar.
- Logging: jeder GenAI-Call als eine JSON-Zeile (Zeitstempel, Agent, Modell, Prompt, Config, Output). Inline-Daten nur als Platzhalter. Quelle für das Agent-Log-Overlay.
- Secrets: nur aus der Umgebung, nie in Code oder Logs. Das Repo ist public.
- Fehler: 429 heißt Spend-Cap und wird nicht wiederholt. Bei 503 wird auf das Fallback-Modell ausgewichen.

## Features

Vorlage für einen neuen Abschnitt:

```markdown
### <Feature>
- Zweck:
- Use-Cases:
- Dateien:
- Schnittstellen (HTTP, WebSocket-Nachrichten):
- Agent und Modell (Schlüssel in config.py):
- Offene Punkte:
```

### Polizei-Dispatcher
_noch leer_

### Gang-Boss
_noch leer_

### Quest-NPC
_noch leer_

### OSM-Stadt
_noch leer_

### Agent-Log-Overlay
_noch leer_

### Starter-Endpoints `/chat` und `/agent`
- Zweck: Gemini-Setup (Key, Modelle, Retry und Fallback) ohne Spiel-Frontend prüfen und den Tool-Loop debuggen.
- Use-Cases:
  - Smoke-Test nach Key- oder Modellwechsel
  - sehen, ob der Fallback gegriffen hat (Feld `model`)
  - neue Tools im Loop ausprobieren
- Dateien:
  - `main.py`: `generate`, `chat`, `agent`, Beispiel-Tools `get_time` und `calculator`
  - `config.py`
  - Tests: `tests/test_api.py`, `tests/test_gemini_retry.py`
- Schnittstellen (HTTP, keine WebSocket-Nachrichten):
  - `GET /`: `{status, models: {agent, chat, fallback}, gemini_key_configured}`. Ruft Gemini nie auf.
  - `GET /chat?q=...`: `{answer, model}`
  - `GET /agent?q=...`: `{answer, model, steps: [{tool, args, result}]}`
  - Fehler:
    - 429 mit Spend-Cap-Hinweis
    - 503, wenn auch das Fallback-Modell überlastet ist
    - 502 bei anderen Gemini-Fehlern
    - 500 ohne Key oder beim Schrittlimit
- Agent und Modell (Schlüssel in config.py):
  - `GEMINI_MODEL_AGENT` und `GEMINI_MODEL_CHAT`: beide `gemini-3.5-flash-lite` (schnellstes Modell der Latenz-Messung vom 2026-11-14)
  - `GEMINI_MODEL_FALLBACK`: `gemini-3.1-flash-lite` (zweitschnellstes)
  - `GEMINI_THINKING_LEVEL`: `low`
  - Limits: `MAX_AGENT_STEPS`, `GEMINI_TIMEOUT_MS` (15 s, deckt den langsamen Fallback ab), `GEMINI_RETRY_*`
  - Details in `agent_docs/gemini_api.md`
- Aufruf aus dem Spiel (Messung vom 2026-11-14 mit Polizei-Function-Call, Agent p90 0,86 s):
  - Die Latenz ist kein Engpass. Allein von ihr her ginge ein Debounce von 1,5 s. Verbindlich sind die Budget-Werte aus dem Plan: `AGENT_DEBOUNCE_S` ≥ 5 s, `POLICE_MIN_INTERVAL_S` 8 s.
  - `AGENT_DEADLINE_MS` 6 s reicht dem Agent-Modell. Das Fallback-Modell (5 bis 12,5 s) schafft das meist nicht. Dann greift der geskriptete Fallback.
  - Pro Agent höchstens ein Request gleichzeitig. Neue Snapshots währenddessen zusammenfassen, der neueste zählt.
  - Mengen (z. B. fehlende Einheiten) rechnet das Spiel und schickt sie im Snapshot mit oder begrenzt sie im Clamp. Das Modell lag dabei in 3 von 5 Calls daneben.
- Offene Punkte:
  - Hydrogen war beim Smoke-Test am 2026-11-14 sehr langsam (30 bis 90 s pro Schritt). Deshalb ist Flash-Lite Default. Hydrogen oder Carbon nur per Env und mit höherem Timeout.
  - Der Fallback mitten im Tool-Loop (3.5-flash-lite-Signatures an 3.1-flash-lite) ist nicht live getestet.
  - `gemini-3.1-flash-lite` lieferte in der Messung 2 von 6 Mal 503. Als Fallback reicht das, als Primärmodell nicht.
  - Mit Polizei-Function-Call braucht `gemini-3.1-flash-lite` 5 bis 12,5 s (1 von 5 Calls: 504). Antwortet der Fallback, sollte das Spiel deshalb lokal nach den festen Fahndungsregeln reagieren.
  - Die Decisions API (`gemini-decision-1`) funktioniert mit dem Key. Für geschlossene Agent-Entscheidungen ist sie ein Kandidat, eingebaut ist sie noch nicht (`agent_docs/gemini_api.md`).
  - GenAI-Calls werden noch nicht als JSON Lines geloggt (Querschnittsregel, Quelle für das Agent-Log-Overlay).
