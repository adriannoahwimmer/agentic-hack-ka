# Fächerstadt Agents: Gesamtarchitektur und Umsetzungsplan

Stand: 2026-11-14, ca. 12:30. Hackathon {Tech: Europe} Agentic AI Hack Karlsruhe. Merge-Freeze 16:30, ab 18:00 nur Bugfixes, Abgabe 19:00.

## Überblick

Fächerstadt Agents ist eine Browser-3D-Open-World rund ums Karlsruher Schloss, gebaut aus echten OpenStreetMap-Daten (Low-Poly). Man kann schießen, fahren und wird gefahndet. Der Twist: Polizei-Dispatcher und Quest-NPC sind Gemini-Agenten, die per Function Calling entscheiden. Das Spiel wartet nie auf sie. Ein Agent-Log-Overlay zeigt jeden Tool-Call live.

Der Demo-Pfad, der am Ende durchlaufen muss:
1. NPC gibt eine Quest zu einem echten Ort (POI, Fakten per Maps Grounding).
2. Hinfahren.
3. Schießerei mit Quest-Gegnern.
4. Die Fahndung steigt (Regel-Boden sofort, dann eskaliert der Agent).
5. Polizeifunk per TTS.
6. Der Dispatcher schickt Einheiten.
7. Die Quest ist erfüllt (der Server prüft das).

Spielsprache ist **Englisch**: Dialoge, Funk, HUD und README. Plan, Design.md und Code-Kommentare bleiben Deutsch (Projektkonvention).

## Ist-Stand (geprüft)

- **Backend:** Es gibt nur den Starter.
  - `main.py:64-124`: `generate()` mit Retry bei 5xx, Fallback-Modell, 429 ohne Retry und 504 direkt zum Fallback.
  - `main.py:251-288`: manueller Tool-Loop (Modell-Turn unverändert, `FunctionResponse` mit `id`).
  - Es gibt kein WebSocket, keine Agenten, kein `game_state` und kein Frontend.
- **Konfiguration:** `config.py` ist die einzige Quelle, jeder Wert ist per Env überschreibbar (`_env`, `_env_number`, config.py:24-37). Die Defaults kommen aus der Latenzmessung:
  - Agent und Chat: `gemini-3.5-flash-lite` mit 0,5 bis 0,8 s Median.
  - Fallback: `gemini-3.1-flash-lite` (config.py:46-48).
- **Logging:** fehlt. JSONL-Logging der GenAI-Calls ist noch offen (Design.md:101).
- **Tests:**
  - Die Tests patchen `main.get_client`, `main._sleep` und `main.genai.Client` (tests/conftest.py:16-48).
  - Die Builder `text_response`, `call_response` und `api_error` stehen in tests/fakes.py.
  - Laufen das Frontend oder die Agenten aus `main.py` heraus, entsteht ein Importzyklus. Deshalb wird `generate()` in Schritt 0b nach `gemini.py` verschoben.
- **Infrastruktur:**
  - Abhängigkeiten: `websockets` ist lokal installiert (über google-genai), FastAPI 0.162.7, Pydantic 2.14.3, uvicorn 0.54.0, Node 24.19.0 und npm 11.17.0.
  - Verfügbare Modelle (`models.list()`, 2026-11-14 um 12:20): **Kein TTS-Modell ist gelistet.** Gelistet sind u. a. `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.8-flash`, `gemini-4-hydrogen` und `gemini-4-carbon`. Auch `gemini-decision-1` war nicht gelistet und trotzdem aufrufbar. TTS braucht also einen Live-Check (Phase 3, Schritt 1).
- **SDK:**
  - In google-genai 3.3.0 hat `GenerateContentConfig` ein Feld `http_options` (types.py:6616). Ein Timeout pro Request ist damit möglich.
  - `types.Tool(google_maps=types.GoogleMaps())` funktioniert mit `generate_content` gegen die Gemini API. Beleg: SDK-Test `test_google_maps_with_enable_widget` in `google/genai/tests/models/test_generate_content_tools.py:649`.
  - Für TTS gibt es `response_modalities` und `speech_config` (types.py:6781, 6792).
- **Doku (gelesen 2026-11-14):**
  - Maps Grounding:
    - unterstützt 3.5- und 3.1-flash-lite
    - nur englische Prompts und Antworten
    - Quellen müssen direkt beim Text stehen: „Google Maps“ unverändert, Link, `translate="no"`
    - 5.000 freie Requests pro Monat
  - Die Kombination von Built-in-Tools und Function Calling ist im Preview. Wir kombinieren deshalb nicht.
  - TTS:
    - `gemini-3.8-flash-lite-tts` (schnell) und `gemini-3.8-flash-tts`
    - Deutsch und Englisch
    - Unary-Ausgabe ist WAV mit 24 kHz, mono, 16 bit
    - 30 Stimmen, u. a. Kore und Orus („Firm“) sowie Charon („Informative“)
    - 8.192 Input-Tokens
- **Overpass:** Von dieser Maschine war Overpass aus der Sandbox nicht erreichbar (HTTP 000). Phase 1 nutzt bei Bedarf Mirrors (siehe Risiken).
- **Altlast:** `test.py` im Repo-Root ruft Gemini live auf (`gemini-3.8-flash`) und wird in Phase 4 gelöscht.
- **Referenzspiel des Kollegen:** liegt nicht im Repo. Scheibe 1 baut ohne Vorlage. Der Vergleich steht am Ende dieses Plans.

## Gewünschter Endzustand

- `.venv\Scripts\uvicorn main:app --port 3000` liefert:
  - `GET /`: Healthcheck, unverändert JSON, ohne Gemini-Call
  - `/play/`: das gebaute Spiel aus `static/`
  - `/ws`: WebSocket
  - `POST /npc/talk`
  - `GET /tts/{key}.wav`
- Mit `AGENTS_MODE=live` läuft der Demo-Pfad komplett durch. Das Overlay zeigt die Calls von `police`, `quest`, `maps` und `tts` mit Tool, Argumenten, Begründung, Latenz und Modell.
- Mit `AGENTS_MODE=offline` läuft derselbe Pfad ohne einen einzigen Gemini-Request. Statt der Agenten greifen die geskripteten Fallbacks, im Overlay mit `FALLBACK`-Badge.
- `scripts\check.ps1` ist grün: ruff, Format, pytest und Frontend-Build.
- Für die Abgabe:
  - README (EN) beschreibt Setup und alle APIs, Frameworks und Tools.
  - Der gitleaks-Scan ist sauber.
  - Das öffentliche Repo enthält den finalen Build in `static/`.
  - Das 2-Minuten-Video ist aufgenommen.

## Was wir NICHT machen

- Kein Multiplayer und keine getrennten Sessions. Es gibt einen globalen Spielzustand pro Serverprozess, mehrere Tabs teilen ihn.
- Kein Spielertod und kein Respawn. Der Spieler ist unverwundbar, Treffer gegen ihn sind nur Effekt.
- Keine Wegfindung über den Straßengraphen. Polizei und Gegner verfolgen den Spieler direkt und gleiten an Gebäuden entlang.
- Kein LLM-Call pro Frame, Schuss oder Positionsupdate, nur gebündelt pro Event-Fenster.
- Keine OSM- oder Overpass-Abfragen zur Laufzeit.
- Keine Live API, keine Spracheingabe, keine Decisions API und keine Migration auf die Interactions API.
- Kein Kombinieren von Maps Grounding und Function Calling im selben Request (das ist Preview). Maps läuft als eigener, gecachter Call.
- Keine Persistenz über Server-Neustarts. Der TTS- und Maps-Cache auf Platte ist die einzige Ausnahme.
- Keine Touch- oder Mobilsteuerung, kein Login.
- Der Codesphere-Deploy ist optional und die einzige Kürzungsoption in Phase 4.

## Architektur und Entscheidungen

```
Browser (Three.js + Rapier, Vite)                      FastAPI :3000 (main.py)
 core/ (Scheibe 1): Stadt, Spieler, Auto,   WS /ws      ws.py -> hub.py (Event-/Action-Bus)
   Ballern (Raycast), HUD, net.js        <=========>      |- game_state.py  Fahndung, Wahrheit   (S2)
 features/*.js registrieren Handler:     Envelope         |- runner.py      Debounce, Clamp, Fallback (S2)
   police.js (S2) npc/quest/radio.js (S3)                 |    '- agents/police.py (S2)
   agent-log.js (S4)                     POST /npc/talk   |- quests.py      Quest-Prüfung per Position (S3)
                                        ------------->    |- agents/quest.py + maps_facts.py   (S3)
                                         GET /tts/k.wav   '- tts.py         async + Cache      (S3)
                                        ------------->  gemini.py: generate() + Budget + genai_log.py
                                                           -> logs/genai.jsonl -> agent_log per WS
```

Getroffene Entscheidungen:
1. **Schritt 0 kommt gestaffelt.**
   - 0a (Vertrag): danach startet der Welt-Worktree.
   - 0b (Kern): danach starten der Polizei- und der Quest-Worktree.
   - `ws.py`, `geo.py` und `data/pois.json` wandern damit in Schritt 0.
   - Der Spielzustand wird geteilt: `game_state.py` gehört Scheibe 2 (Fahndung), `quests.py` gehört Scheibe 3.
2. **Fahndung = Regel-Boden + Agent.**
   - `game_state` hebt bei einem Verbrechen sofort von 0 auf 1 (`source: "rules"`).
   - Nach `WANTED_DECAY_S` ohne Verbrechen senkt es die Stufe um 1.
   - Alles andere entscheidet der Dispatcher-Agent oder sein Fallback: Eskalation, Einheiten, Taktik, Funk.
3. **Ein Request pro Polizei-Zyklus.**
   - Function Calling im Modus `ANY`, mehrere parallele Calls in einer Antwort.
   - Die Tool-Ergebnisse gehen nicht ans Modell zurück. Der Server validiert, clampt und schickt die Aktionen per WS.
   - Das Gedächtnis liegt serverseitig als Textzusammenfassung im Snapshot. Weil kein Verlauf mitgeschickt wird, gibt es keine Probleme mit Thought-Signatures.
4. **`reason` ist ein Pflichtfeld in jedem Tool.** Ein Satz, der die Begründungszeile für Log und Overlay liefert.
5. **Quest-Loop mit beendendem Tool.**
   - `assign_quest` beendet den Loop. Ein Gespräch kostet typisch 2 Requests (`lookup_place` → `assign_quest`), maximal `QUEST_MAX_STEPS`.
   - Für den Tool-Loop gilt das Muster aus `main.py:251-288`: Modell-Turn unverändert übernehmen, `FunctionResponse` mit `id` zurückgeben.
6. **Maps Grounding ist ein eigener Call pro POI.** Das Modul `maps_facts.py`:
   - fragt auf Englisch
   - cacht in `cache/maps_facts.json`
   - wird vor der Demo per Skript vorgewärmt
7. **TTS entkoppelt per `tts_key`.**
   - `protocol.make_radio_message()` berechnet `tts_key = sha256(voice|text)[:16]`.
   - `tts.py` beobachtet ausgehende `radio_message`-Aktionen und erzeugt das Audio vorab.
   - Der Client lädt `/tts/{key}.wav`. Bei 404 oder Timeout spricht der Browser selbst (`speechSynthesis`).
   - So kennt die Polizei-Scheibe TTS nicht.
8. **Spiel unter `/play/`.**
   - `GET /` bleibt der JSON-Healthcheck (CLAUDE.md, Codesphere, tests/test_api.py:10).
   - Vite: `base: '/play/'`, `outDir: '../static'`.
   - `static/` bleibt gitignored, bis Phase 4 den finalen Build einmal committet.
9. **`AGENTS_MODE` hat den Default `offline`.**
   - Ohne explizites `AGENTS_MODE=live` in der `.env` geht kein Spiel-Request an Gemini.
   - Zusätzlich gibt es ein hartes Budget pro Prozess: `GENAI_MAX_CALLS_PER_MIN` und `GENAI_MAX_CALLS_TOTAL`.
   - Ist es erschöpft, greifen die Fallbacks.
10. **Registrierungspunkte ohne Import-Seiteneffekte.**
    - `main.py` lädt eine feste Liste von Feature-Modulen, falls vorhanden, und ruft deren `register(hub)` auf.
    - Das Frontend lädt `features/*.js` per `import.meta.glob` und ruft `init(ctx)` auf.
    - Die Scheiben berühren `main.py` und `frontend/src/main.js` nicht.

## Der Vertrag (Inhalt für Design.md, Schritt 0a)

Phase 0a überträgt diesen Abschnitt nach `Design.md`, Abschnitt „Vertrag“. Die Implementierung steht in `protocol.py`, die Beispiele liegen in `contract/examples/*.json`. Ein pytest-Test validiert jedes Beispiel gegen `protocol.py`.

### Koordinaten
- Einheit ist Meter. Ursprung ist das Schloss (lat 49.0135, lon 8.4044).
- Achsen: **x = Ost**, **y = oben**, **z = Süd** (also z = −Nord, Three.js-Konvention: Norden zeigt nach −z).
- Die Projektion steht nur in `geo.py`:
  - `to_local(lat, lon) -> (x, z)` und `to_latlon(x, z) -> (lat, lon)`
  - äquirektangulär um den Ursprung, R = 6 371 008,8 m
  - x = R·Δλ·cos φ₀, z = −R·Δφ
  - Fehler unter 0,1 m auf 1 km
- `heading` in Radiant (Three.js-Rotation um y), `speed` in m/s.

### WebSocket `/ws`: Envelope
```json
{"type": "shot_fired", "ts": 1763125392123, "payload": {}}
```
- `type` ist ein String aus den Tabellen unten.
- `ts` ist ein int mit Unix-Zeit in ms, gesetzt vom Sender.
- `payload` ist ein Objekt gemäß dem Modell.
- Ungültige Nachrichten verwirft der Server. Er antwortet mit `error` und schließt die Verbindung nicht.
- Server-Limit: maximal `WS_MAX_EVENTS_PER_S` Events pro Sekunde und Client, der Rest wird verworfen.

### Events Client → Server
| type | payload-Felder | Hinweise |
|---|---|---|
| `player_position` | `x: float, z: float, heading: float, speed: float, in_vehicle: bool, zone_id: str\|null` | max. 2 Hz (Client drosselt), löst nie einen Agenten aus |
| `shot_fired` | `x, z, shots: int 1–50, weapon: "pistol"\|"smg", zone_id` | Client bündelt Schüsse pro 500 ms |
| `npc_killed` | `npc_id: str, npc_kind: "civilian"\|"police"\|"gang"\|"quest_target", x, z, zone_id, quest_id: str\|null` | sendet nur `core/combat` |
| `vehicle_stolen` | `vehicle_id: str, vehicle_kind: "civilian"\|"police", x, z, zone_id` | |
| `zone_entered` | `zone_id: str, previous_zone_id: str\|null` | zone = POI, in dessen `radius` der Spieler steht |

### Aktionen Server → Client
| type | payload-Felder | Hinweise |
|---|---|---|
| `set_wanted_level` | `level: int 0–5, source: "rules"\|"agent"\|"fallback", reason: str ≤160` | Level 0 → Client entfernt alle Polizei-Einheiten |
| `spawn_units` | `wave_id: str, faction: "police"\|"gang", count: int 1–6, unit_type: "patrol"\|"swat"\|"gang", tactic: "chase"\|"roadblock"\|"surround", near_poi_id: str\|null` | null = in der Nähe des Spielers, 120–200 m entfernt |
| `radio_message` | `id: str, speaker: str, text: str ≤160, voice: str, tts_key: str` | nur über `protocol.make_radio_message()` bauen |
| `quest_update` | `quest_id, status: "active"\|"target_reached"\|"completed", title, objective, poi_id, target: {x, z, radius}, spawn_targets: int 0–5, remaining: int` | bei `target_reached` spawnt der Client `spawn_targets` Gegner |
| `agent_log` | Log-Zeile ohne `prompt` und `config` (siehe JSONL) | für das Overlay |
| `error` | `code: str, message: str` | Debug-Hilfe |

Beim Verbinden schickt der Server den aktuellen Zustand nach (`hub.on_connect`): `set_wanted_level` sowie `quest_update`, falls eine Quest aktiv ist. Ein Reload synchronisiert also von selbst.

Beispiel (`contract/examples/spawn_units.json`):
```json
{"type": "spawn_units", "ts": 1763125398000,
 "payload": {"wave_id": "w-3", "faction": "police", "count": 2, "unit_type": "patrol",
             "tactic": "roadblock", "near_poi_id": "marktplatz"}}
```

### HTTP `POST /npc/talk`
Request:
```json
{"npc_id": "fixer_karl", "player_text": "Got any work?", "x": 12.0, "z": 40.5}
```
- `player_text`: höchstens 200 Zeichen, Default `""`, dann grüßt der NPC.
- `x` und `z`: optional.

Response 200 (auch im Fallback, nie 5xx durch Gemini):
```json
{"npc_id": "fixer_karl", "text": "Head to the Market Square ...",
 "quest": {"quest_id": "q-1", "status": "active", "title": "Pyramid Trouble",
           "objective": "Go to Market Square and deal with 3 thugs",
           "poi_id": "marktplatz", "target": {"x": -4.4, "z": 456.0, "radius": 35},
           "spawn_targets": 0, "remaining": 3},
 "sources": [{"title": "Marktplatz Karlsruhe", "uri": "https://maps.google.com/?cid=..."}],
 "model": "gemini-3.5-flash-lite", "fallback": false}
```
- `quest` ist null, wenn nur geredet wurde.
- Eine neue Quest kommt zusätzlich als `quest_update` per WS.
- 404 bei unbekannter `npc_id`, 422 bei ungültigem Body.

### Snapshot für Agenten (`protocol.AgentSnapshot`)
Er geht als kompaktes JSON (`model_dump_json(exclude_none=True)`, Ziel unter 2 KB) als User-Content an den Agenten.
```json
{"agent": "police", "t": "2026-11-14T14:03:12Z",
 "player": {"x": -3.0, "z": 450.2, "zone_id": "marktplatz", "in_vehicle": false, "speed": 1.2},
 "wanted_level": 1, "units_active": 0, "units_max": 6,
 "recent_events": [{"type": "shot_fired", "s_ago": 2.1, "zone_id": "marktplatz", "detail": {"shots": 9}},
                   {"type": "npc_killed", "s_ago": 1.4, "zone_id": "marktplatz", "detail": {"npc_kind": "quest_target"}}],
 "counts_60s": {"shot_fired": 3, "npc_killed": 1, "vehicle_stolen": 0},
 "memory": ["14:02:40 level 1 (rules), no units"],
 "places": [{"id": "marktplatz", "name": "Market Square"}, {"id": "schloss", "name": "Karlsruhe Palace"}],
 "extras": {"quest": {"title": "Pyramid Trouble", "poi_id": "marktplatz", "status": "target_reached"}}}
```
- `recent_events`: höchstens 12.
- `memory`: höchstens 5 Zeilen, vom Agentenmodul gepflegt.
- `extras`: kommt von `hub.register_snapshot_provider(name, fn)`. `quests.py` liefert `quest`, `game_state.py` liefert `wanted`.

### JSONL-Log `logs/genai.jsonl`
Eine Zeile pro GenAI-Request, also pro tatsächlichem HTTP-Versuch. Auch jede Fallback-Entscheidung bekommt eine Zeile.
```json
{"ts": "2026-11-14T14:03:13.412Z", "call_no": 42, "kind": "genai", "agent": "police",
 "model": "gemini-3.5-flash-lite", "status": "ok", "error": null, "latency_ms": 612,
 "prompt": "<Snapshot-JSON, gekürzt auf GENAI_LOG_MAX_PROMPT_CHARS>",
 "config": {"tools": ["set_wanted_level", "spawn_units", "radio_message"], "tool_mode": "ANY",
            "thinking_level": "low", "system_instruction_chars": 840, "response_modalities": null},
 "output": {"text": null,
            "calls": [{"tool": "spawn_units", "args": {"count": 2, "unit_type": "patrol", "tactic": "roadblock",
                       "near_poi_id": "marktplatz", "reason": "Shots fired near the square"}}],
            "inline": [], "sources": []},
 "reason": "Shots fired near the square"}
```
- `kind` ist `"genai"` oder `"fallback"`.
- Bei `kind: "fallback"` ist `model` null, und `output.calls` enthält die geskripteten Aktionen.
- `status` ist `"ok"` oder `"error"`. Ist er `"error"`, steht in `error` ein Objekt `{code, message}`.
- `reason` kommt aus `args.reason` des ersten Calls.
- Inline-Daten erscheinen nur als `{"mime": "audio/wav", "bytes": 48000}`.
- Nie im Log: Key, Header oder Auth.

### POI-Format `data/pois.json`
```json
{"version": 1, "origin": {"lat": 49.0135, "lon": 8.4044},
 "pois": [{"id": "marktplatz", "name": "Market Square", "category": "square",
           "lat": 49.0094, "lon": 8.4037, "x": -51.2, "z": 456.0, "radius": 35,
           "osm_ref": "way/123456", "tags": ["mission", "crowded"],
           "description": "Central square with the Pyramid, Karlsruhe's landmark."}]}
```
- Die Werte im Beispiel sind nur illustrativ. Phase 0a übernimmt die echten Koordinaten aus OSM und berechnet x und z mit `geo.to_local`.
- `id` ist ein Slug, `radius` ist in Metern.
- `tags` steuern die Auswahl: `mission`, `gang_turf` und `npc_spot`.

### Registrierungspunkte
- **Backend-Feature-Modul:** exportiert `register(hub: Hub) -> None` und optional `router: APIRouter`, `async startup()` und `async shutdown()`.
  - `main.py` geht `FEATURE_MODULES` durch: `game_state`, `quests`, `runner`, `maps_facts`, `tts`, `agents.police`, `agents.quest`.
  - Für jedes Modul: importieren, falls vorhanden, dann `register(HUB)`, dann `include_router`, dann die Lifespan-Hooks.
  - Fehlt ein Modul, wird es übersprungen (INFO-Log). Jeder andere Importfehler bricht den Start ab.
  - Die Reihenfolge bestimmt die Handler-Reihenfolge: erst der Zustand, dann die Agenten.
- **Hub-API** (`hub.py`):
  - `on_event(type | "*", fn)`
  - `await publish_event(env)` (nur ws.py)
  - `await send_action(type, payload_model)`
  - `send_action_threadsafe(type, payload)`
  - `on_action(type, fn)`: Beobachter, z. B. TTS
  - `on_connect(fn) -> list[Envelope]`
  - `register_snapshot_provider(name, fn)` und `snapshot_extras()`
  - Handler müssen schnell sein. Sie rufen kein LLM auf, sondern starten höchstens einen Task.
- **Agent-Runner** (`runner.py`, Scheibe 2): `runner.register_agent(AgentSpec(...))`.
  - Felder: `name`, `triggers: set[str]`, `min_interval_s`, `decide: async (snapshot) -> list[Envelope]`, `fallback: (snapshot) -> list[Envelope]`, `clamp: (actions, state) -> list[Envelope]`.
  - Ablauf:
    1. Ein Trigger-Event öffnet ein Sammelfenster von `AGENT_DEBOUNCE_S`.
    2. Danach wird `min_interval_s` seit dem letzten Zyklus eingehalten.
    3. Pro Agent läuft höchstens ein Call.
    4. `decide` läuft mit `wait_for(AGENT_DEADLINE_MS)`.
    5. Bei Timeout, Fehler, `offline` oder erschöpftem Budget greift `fallback`.
    6. Danach `clamp`, dann `send_action`.
  - Verspätete Ergebnisse werden verworfen (Generationszähler).
- **Frontend-Feature-Modul:** `frontend/src/features/<name>.js` exportiert `init(ctx)`. `main.js` lädt alle Module per `import.meta.glob('./features/*.js', {eager: true})`.
- **`ctx`** (JSDoc in `frontend/src/types.js`, implementiert von core/ in Scheibe 1):
  - `three`, `scene`, `camera`, `renderer`, `rapier`, `physics` (RAPIER.World)
  - `net`: `on(type, fn) -> off`, `send(type, payload)`, `onStatus(fn)`
  - `onUpdate(fn(dt, t)) -> off`
  - `input`: `isDown(code)`, `onKey(code, fn)`
  - `player`: `position() -> {x, z}`, `heading()`, `inVehicle()`, `object3d`
  - `world`: `pois`, `zoneAt(x, z)`, `randomRoadPoint({x, z}, minDist, maxDist)`
  - `combat`: `addTarget(object3d, {id, kind, questId?, hp, onKilled})` und `removeTarget(id)`. `core/combat` macht den Raycast, zieht HP ab, sendet `npc_killed` und ruft `onKilled` auf.
  - `models`: `car({police?: bool, color?})` und `person({color?})`
  - `hud`: `setWanted(n)`, `toast(text, ms)`, `setObjective(text | null)`, `subtitle(text, ms)`, `showDialog({speaker, text, sources?, pending?})`, `hideDialog()`, `addPanel(id) -> HTMLElement`

## Konfiguration (alle Schlüssel kommen in Schritt 0a nach config.py und .env.example)

Bestehende Schlüssel bleiben. Neu sind die folgenden. Scheiben ändern höchstens Defaults in ihrem Block und legen keine neuen Schlüssel an. Brauchen sie doch einen, kommt er nur in den eigenen Block am Dateiende.

| Schlüssel | Default | Zweck |
|---|---|---|
| `AGENTS_MODE` | `offline` | `live` oder `offline` (nur Fallbacks, kein Gemini) |
| `GEMINI_MODEL_POLICE`, `GEMINI_MODEL_QUEST` | = `GEMINI_MODEL_AGENT` | pro Agent |
| `GEMINI_MODEL_MAPS` | `gemini-3.5-flash-lite` | Maps Grounding (laut Doku unterstützt) |
| `GEMINI_MODEL_TTS` | `gemini-3.8-flash-lite-tts` | nicht gelistet, Live-Check in Phase 3 |
| `TTS_VOICE` | `Orus` | Funkstimme („Firm“) |
| `GENAI_MAX_CALLS_PER_MIN` / `GENAI_MAX_CALLS_TOTAL` | `30` / `400` | hartes Budget pro Prozess |
| `GENAI_LOG_PATH` / `GENAI_LOG_MAX_PROMPT_CHARS` | `logs/genai.jsonl` / `4000` | |
| `AGENT_DEBOUNCE_S` | `5.0`, erzwungen ≥ 5 | Sammelfenster |
| `POLICE_MIN_INTERVAL_S` | `8` | Abstand zwischen Zyklen |
| `AGENT_DEADLINE_MS` / `AGENT_ATTEMPTS` | `6000` / `1` | pro Zyklus. Kein Backoff im Spiel, der Fallback-Modellwechsel bleibt. |
| `WANTED_MAX` / `WANTED_MAX_STEP` / `WANTED_DECAY_S` | `5` / `2` / `30` | Clamps, Regel-Boden |
| `POLICE_MAX_UNITS` / `RADIO_MAX_CHARS` | `6` / `160` | Clamps |
| `QUEST_MAX_STEPS` / `QUEST_DEADLINE_MS` / `QUEST_MAX_TARGETS` | `3` / `8000` / `5` | |
| `TTS_DEADLINE_MS` / `TTS_CACHE_DIR` | `8000` / `cache/tts` | |
| `MAPS_CACHE_PATH` | `cache/maps_facts.json` | |
| `WS_MAX_EVENTS_PER_S` | `20` | |
| `DEBUG_ENDPOINTS` | `0` | `1` aktiviert `POST /debug/action` und `GET /debug/state` |

Die Client-Drosselung (2 Hz Position, 500 ms Schussbündel) steht als Konstanten in `frontend/src/net.js`. Der Server erzwingt sie zusätzlich über `WS_MAX_EVENTS_PER_S`.

## Datei-Besitz (keine Überschneidung nach Schritt 0)

| Pfad | Besitzer |
|---|---|
| `protocol.py`, `geo.py`, `contract/examples/*`, `tests/test_protocol.py`, `tests/test_geo.py`, `config.py`, `.env.example`, `scripts/check.ps1`, `scripts/check.sh` | 0a |
| `frontend/package.json`, `vite.config.js`, `index.html`, `src/main.js`, `src/net.js`, `src/types.js`, `src/core/index.js` (Platzhalter) | 0a, danach **Welt** |
| `data/pois.json` | 0a, danach **Quest** (Inhalt). Welt und Polizei lesen nur. |
| `gemini.py`, `genai_log.py`, `hub.py`, `ws.py`, `main.py`, `agents/__init__.py`, `tests/conftest.py`, `tests/fakes.py`, `tests/test_gemini_retry.py`, `tests/test_api.py`, `tests/test_genai_log.py`, `tests/test_hub.py`, `tests/test_ws.py`, `CLAUDE.md`, `agent_docs/gemini_api.md` (Pfadangaben) | 0b |
| `scripts/bake_osm.py`, `data/osm/raw.json`, `frontend/public/city/*`, `frontend/src/core/**`, `tests/test_bake_osm.py` | Welt |
| `game_state.py`, `runner.py`, `agents/police.py`, `frontend/src/features/police.js`, `tests/test_game_state.py`, `tests/test_runner.py`, `tests/test_police.py` | Polizei |
| `quests.py`, `agents/quest.py`, `maps_facts.py`, `tts.py`, `data/npcs.json`, `scripts/prewarm.py`, `frontend/src/features/npc.js`, `quest.js`, `radio.js`, `tests/test_quests.py`, `tests/test_quest_agent.py`, `tests/test_maps_facts.py`, `tests/test_tts.py`, `agent_docs/gemini_api.md` (neue Abschnitte TTS und Maps) | Quest |
| `frontend/src/features/agent-log.js`, `README.md`, `docs/demo.md`, `ci.yml`, `static/` (finaler Build), `test.py` (löschen) | Phase 4 |
| `Design.md` | 0a legt alle Feature-Abschnitte an. Danach editiert jede Scheibe **nur ihre** Abschnitte. |

Gemeinsame Dateien nach Schritt 0, also `config.py`, `Design.md` und `.env.example`, werden nur innerhalb des eigenen Blocks geändert. Merge-Konflikte dort sind trivial und werden beim Merge im Haupt-Checkout gelöst.

## Zeitplan

| Zeit | Haupt-Checkout | Worktree welt | Worktree polizei | Worktree quest |
|---|---|---|---|---|
| 12:35–13:00 | Phase 0a → PR, Merge | – | – | – |
| 13:00–13:35 | Phase 0b → PR, Merge | Phase 1 (W1) | – | – |
| 13:35–14:45 | Integrator | W1–W2 | Phase 2 (P1–P2) | Phase 3 (Q1–Q3) |
| **14:45** | **Checkpoint-Merge Welt** (ctx steht) | weiter W3 | Rebase auf main | Rebase auf main |
| 14:45–16:00 | Integrator | W3–W4 | P3 (police.js), P4 | Q4 (Frontend), Q5 |
| **15:30** | **Kürz-Entscheidung** (siehe Kürzungsoptionen) | | | |
| 16:00 / 16:10 / 16:20 | Merges: Welt → Polizei → Quest | | | |
| **16:30** | **Merge-Freeze** | | | |
| 16:30–18:00 | Phase 4 | | | |
| 17:30 | Sicherheits-Aufnahme des Demo-Pfads | | | |
| 18:00–19:00 | nur Bugfixes, finales Video, Abgabe | | | |

## Worktree-Setup (PowerShell, einmal pro Scheibe)

```powershell
# im Haupt-Checkout, sauber und auf aktuellem main; nach 0a (welt) bzw. 0b (polizei, quest)
git checkout main; git pull
.\scripts\setup-worktree.ps1 welt    3003 5173
.\scripts\setup-worktree.ps1 polizei 3001 5174
.\scripts\setup-worktree.ps1 quest   3002 5175
```
Das Skript legt `..\ka-<name>` mit Branch `feat/<name>` an. Danach:
- Es kopiert die `.env` und setzt `PORT`, `VITE_PORT` und `BACKEND_URL`. `vite.config.js` liest daraus nur die Port-Schlüssel.
- Es installiert `requirements-dev.txt` und führt `npm ci` aus.
- Es lässt `check.ps1` laufen und öffnet VS Code.

| Worktree | Branch | Backend | Vite | `.env`-Ergänzungen von Hand |
|---|---|---|---|---|
| Haupt-Checkout | `main` | 3000 (liefert `/play/`) | – (Build) | `AGENTS_MODE=live` nur für den Demo-Lauf |
| `..\ka-welt` | `feat/welt` | 3003 | 5173 | `DEBUG_ENDPOINTS=1` (`AGENTS_MODE` bleibt `offline`) |
| `..\ka-polizei` | `feat/polizei` | 3001 | 5174 | `DEBUG_ENDPOINTS=1`, `GENAI_MAX_CALLS_TOTAL=60` |
| `..\ka-quest` | `feat/quest` | 3002 | 5175 | `DEBUG_ENDPOINTS=1`, `GENAI_MAX_CALLS_TOTAL=60` |

- Backend starten: `.venv\Scripts\uvicorn main:app --reload --port <Backend>`.
- Frontend starten: `npm --prefix frontend run dev`. Danach `http://localhost:<Vite>/play/` öffnen. Der Proxy zeigt automatisch auf das Backend des Worktrees.
- Für bewusste Live-Tests setzt man `AGENTS_MODE=live` nur temporär in der Shell (`$env:AGENTS_MODE='live'`). Danach die Requests zählen: `(Get-Content logs\genai.jsonl).Count`.
- Aufräumen nach dem Merge: `git worktree remove ..\ka-welt`.

---

## Phase 0a: Vertrag (Haupt-Checkout, 12:35–13:00, ca. 25 min)

### Überblick
Den Vertrag festschreiben, die gemeinsamen Grundlagen für die Welt-Scheibe legen und das Frontend-Skelett aufsetzen. Danach startet der Welt-Worktree.

### Änderungen
1. **`Design.md`**
   - neuer Abschnitt „Vertrag“ mit dem Inhalt oben
   - neue Feature-Abschnitte (jeweils Vorlage mit Platzhaltern): Frontend-Kern, OSM-Stadt, Spielzustand, Agent-Runner, Polizei-Dispatcher, Gang-Boss, Quest-NPC, Maps-Fakten, Polizeifunk-TTS, Agent-Log-Overlay
   - Architekturdiagramm aktualisieren
2. **`protocol.py`** (Kopfkommentar, Docstrings)
   - Pydantic-v2-Modelle für Envelope, die 5 Events, die 6 Aktionen, `NpcTalkRequest/Response`, `QuestInfo`, `Source`, `AgentSnapshot`, `GenaiLogLine`, `Poi` und `PoiFile`
   - `EVENT_MODELS` und `ACTION_MODELS` (Dict type → Modell)
   - `parse_client_message(text) -> (Envelope, Model)`, wirft `ValidationError`
   - `make_action(type, payload) -> Envelope`
   - `make_radio_message(text, speaker="Dispatch", voice=config.TTS_VOICE)` mit `tts_key`
   - `load_pois(path="data/pois.json") -> PoiFile`, gecacht
   - Grenzen (Level, Anzahl, Textlänge) aus `config.py`
3. **`contract/examples/*.json`**: ein Beispiel pro Event und Aktion, dazu `npc_talk_request`, `npc_talk_response`, `snapshot_police` und `genai_log_line`.
4. **`geo.py`**: `ORIGIN`, `to_local` und `to_latlon`.
5. **`data/pois.json`**:
   - 8 bis 10 POIs im Bake-Bereich, die echten lat/lon-Werte aus OSM: Schloss, Schlossplatz, Marktplatz (Pyramide), Bundesverfassungsgericht, Botanischer Garten, Kunsthalle, Ev. Stadtkirche, Rondellplatz und ein Punkt auf der Kaiserstraße.
   - Englische Namen und Beschreibungen, x/z über `geo.py`. Mindestens 4 POIs mit `mission`, 1 mit `npc_spot`.
   - Die Koordinaten kommen per einmaliger Overpass- oder Nominatim-Abfrage. Ist sie gesperrt, einen Mirror nehmen (siehe Risiken).
6. **`config.py` und `.env.example`**: alle Schlüssel aus der Tabelle, in Blöcken pro Scheibe.
7. **`.gitignore`**: `static/`, `cache/`, `frontend/node_modules/` und `frontend/.env.local`.
8. **Frontend-Skelett**
   - `frontend/package.json`:
     - Abhängigkeiten `three`, `@dimforge/rapier3d-compat` und `vite`
     - Versionen beim Installieren exakt pinnen
     - Skripte `dev` und `build`
     - `package-lock.json` committen
   - `vite.config.js`:
     - `base: '/play/'`
     - `build.outDir: '../static'` und `emptyOutDir: true`
     - `server.port` aus `VITE_PORT`, `strictPort`
     - `server.fs.allow: ['..']` für Importe aus `data/`
     - Proxy `/ws` (ws), `/npc`, `/tts` und `/debug` auf `BACKEND_PORT`
   - `index.html`
   - `src/net.js`: Envelope, Reconnect mit 1 bis 5 s Backoff, `on`, `send`, `sendThrottled`, `onStatus`, Drossel-Konstanten
   - `src/main.js`: lädt core, dann die Features per Glob, ruft `init(ctx)` auf (Fehler pro Feature isoliert), dann `net.connect()` und `ctx.start()`
   - `src/types.js`: JSDoc für `ctx`
   - `src/core/index.js`: Platzhalter mit leerer Szene und dem Text „world arrives in slice 1“
   - `src/features/.gitkeep`
9. **`scripts/check.ps1` und `check.sh`**: neue Stufe „frontend build“ (`npm --prefix frontend run build`), nur wenn `frontend/node_modules` existiert.
10. **Tests**
    - `tests/test_protocol.py`: alle Beispiele validieren, ungültige Level und Anzahlen werden abgelehnt, unbekannter `type` wird abgelehnt, `tts_key` ist deterministisch, `pois.json` validiert
    - `tests/test_geo.py`: Ursprung ergibt (0, 0), 0,001° Nord ergibt z ≈ −111,2, Rundreise unter 0,01 m, alle POIs liegen in der Bake-Bounding-Box
11. **Commit, PR, Merge:** Branch `feat/vertrag`, dann `gh pr create --fill` und `gh pr merge --merge`.

### Schnittstellen zum Vertrag
Diese Phase definiert ihn.

### Erfolgskriterien
#### Automatisch
- [x] `scripts\check.ps1` grün, einschließlich frontend build
- [x] `.venv\Scripts\python -m pytest tests/test_protocol.py tests/test_geo.py -q`
#### Manuell
- [x] Design.md „Vertrag“ gelesen und freigegeben (die Feldnamen sind ab jetzt eingefroren)
- [x] POIs plausibel: `x`/`z` stimmen grob mit der Lage zum Schloss (Marktplatz ca. 507 m südlich, also z ≈ +507)

**Umsetzungsnotizen 0a (12:50):**
- Pakete exakt gepinnt: three 0.187.0, @dimforge/rapier3d-compat 0.21.0, vite 8.3.8. Der Skelett-Build dauert ca. 1,4 s.
- Overpass: Nur der Mirror `https://maps.mail.ru/osm/tools/overpass/api/interpreter` war erreichbar. overpass-api.de und kumi.systems lieferten keine Verbindung. Scheibe 1 nutzt deshalb mail.ru.
- 9 POIs, keine Zonen-Überlappung (Test). Rondellplatz liegt knapp südlich der Box und fehlt deshalb.
- Die zweite Latenzmessung (andere Session, agent_docs/gemini_api.md) hatte zwei Folgen:
  - **Sollwerte statt Mengen:** `spawn_units` fragt im Tool die Soll-Einheiten ab (`target_units`), der Server rechnet die Differenz. Grund: Das Modell zog aktive Einheiten in 3 von 5 Calls nicht ab. Das `agent_log`-Beispiel zeigt das schon.
  - **Kein Fallback-Modell im Spiel:** Das Fallback-Modell braucht 7 bis 12,5 s und liegt damit immer über `AGENT_DEADLINE_MS` (6 s). Spiel-Agenten rufen `generate(..., use_fallback_model=False)` auf (0b). Schlägt das Primärmodell fehl, greift direkt der geskriptete Fallback, ohne einen bezahlten Request, dessen Ergebnis verworfen würde.

**Hinweis zur Umsetzung:** Nach grünem Check kurz pausieren, um Vertrag und POIs zu bestätigen. Danach den Welt-Worktree starten.

---

## Phase 0b: Laufzeit-Kern (Haupt-Checkout, 13:00–13:35, ca. 35 min)

### Überblick
Gemini-Zugriff mit Log und Budget, Event-/Action-Bus, WebSocket und Feature-Loader. Danach starten der Polizei- und der Quest-Worktree. Vorher den Skill `gemini-api-dev` laden (CLAUDE.md).

### Änderungen
1. **`gemini.py`**
   - `get_client`, `backoff_delay`, `_sleep` und `generate` 1:1 aus main.py:36-124 übernehmen.
   - `generate` bekommt die zusätzlichen Keyword-Parameter `agent: str = "starter"`, `attempts: int | None = None` (Default `GEMINI_RETRY_ATTEMPTS`), `timeout_ms: int | None = None` und `use_fallback_model: bool = True`. Spiel-Agenten setzen `use_fallback_model=False`, siehe Umsetzungsnotizen 0a.
   - Den Timeout setzt `gen_config.model_copy(update={"http_options": HttpOptions(timeout=...)})`. Bei der Umsetzung prüfen, dass der Wert auch als `X-Server-Timeout` ankommt (SDK-Quelle `_api_client.py`).
   - Vor jedem Versuch das Budget prüfen. Ist es erschöpft, kommt `HTTPException(503, "GenAI budget exhausted ...")`, ohne Request.
   - Nach jedem Versuch `genai_log.log_call(...)`, mit Erfolg, Fehler und Latenz.
   - Neu: `async def agenerate(...)` als `asyncio.to_thread(generate, ...)`.
   - Neu: `live_enabled() -> bool` (`AGENTS_MODE == "live"`).
   - 429-, 5xx- und 504-Logik unverändert.
2. **`genai_log.py`**
   - `log_call(agent, model, contents, gen_config, response=None, error=None, latency_ms)`
   - `log_fallback(agent, actions, reason)`
   - Platzhalter für Inline-Daten, Kürzung des Prompts, Quellen aus `grounding_metadata`, falls vorhanden
   - JSONL anhängen (Ordner anlegen)
   - `add_listener(fn)`: Listener-Fehler werden geloggt und nie weitergereicht
   - thread-sicher (Lock)
3. **`hub.py`**
   - Klasse `Hub` mit der API aus „Registrierungspunkte“, Modul-Singleton `HUB`
   - `send_action` validiert über `protocol.ACTION_MODELS`, ruft die `on_action`-Beobachter auf und sendet an alle Clients
   - Tote Sockets werden entfernt
   - `send_action_threadsafe` über den beim Start gemerkten Event-Loop
   - In `startup` registriert sich ein `genai_log`-Listener, der jede Zeile als `agent_log` sendet (ohne `prompt` und `config`)
4. **`ws.py`**
   - Router mit `@websocket("/ws")`: accept, Client registrieren, `on_connect`-Nachrichten senden, Empfangsschleife mit `parse_client_message`, Rate-Limit, `publish_event`
   - Bei Fehler `error` an den Client schicken
   - `POST /debug/action` (nur bei `DEBUG_ENDPOINTS=1`): nimmt eine Server-Envelope, validiert sie und broadcastet sie. So können Frontend-Scheiben ohne Agenten testen: `Invoke-RestMethod -Method Post http://localhost:3001/debug/action -ContentType application/json -InFile contract\examples\spawn_units.json`
5. **`main.py`**
   - Starter-Endpoints bleiben und nutzen `gemini.generate(..., agent="starter"|"chat")`.
   - Neu: `FEATURE_MODULES` mit Loader, `include_router(ws.router)`, Lifespan (Hub-Loop merken, `startup`/`shutdown` der Features).
   - Mount `/play` mit StaticFiles(`static`, `html=True`), nur wenn der Ordner existiert, als letzter Schritt.
   - `GET /` bekommt zusätzlich `"agents_mode"` und `"genai_calls"` (Zähler).
6. **`agents/__init__.py`**: leer, mit Kopfkommentar.
7. **Tests**
   - `conftest.py` patcht jetzt `gemini.*`. Neue autouse-Fixtures:
     - `GENAI_LOG_PATH` → tmp_path
     - Budget zurücksetzen
     - `AGENTS_MODE` → `offline`
     - frische `Hub`-Instanz per Fixture `fresh_hub`
   - `fakes.py`:
     - `audio_response(data: bytes, mime="audio/wav")`
     - `grounded_response(text, sources=[(title, uri)])`
     - `FakeModels` ignoriert `http_options`
   - Anpassen: `test_gemini_retry.py` und `test_api.py`
   - Neu: `test_genai_log.py`
     - eine Zeile pro Versuch
     - Fehlerzeile mit Code
     - Audio nur als Platzhalter
     - ein Dummy-Key aus der Env steht nie in der Datei
     - Listener wird aufgerufen
   - Neu: `test_hub.py`: Reihenfolge der Handler, Validierung der Aktionen, `on_action`, Snapshot-Provider
   - Neu: `test_ws.py` (TestClient-Websocket)
     - gültiges Event erreicht den Handler
     - ungültiges Event liefert `error` und die Verbindung bleibt offen
     - `/debug/action` broadcastet und ist ohne Flag 404
     - Budget-Test: Nach `GENAI_MAX_CALLS_TOTAL` Calls wirft `generate` ohne `fake.models.calls`-Zuwachs
8. **Doku:** CLAUDE.md-Projektkarte (neue Dateien) und Pfadangaben in `agent_docs/gemini_api.md` (main.py → gemini.py) aktualisieren.
9. **Commit, PR, Merge:** Branch `feat/kern`.

### Schnittstellen zum Vertrag
Hub-API, Feature-Modul-Protokoll, JSONL-Format, `agent_log`, `/debug/action`.

### Erfolgskriterien
#### Automatisch
- [x] `scripts\check.ps1` grün (140 Tests, frontend build)
- [x] Alle bisherigen Tests laufen weiter: `/chat`, `/agent`, Retry, Fallback, 429.
- [x] Automatischer Smoke-Test gegen echten uvicorn (Port 3099, offline, ohne Key): `GET /` mit `agents_mode`/`genai_calls`, `/play/` 200, `/debug/action` (radio_message) kommt per WS an, ungültiges Event liefert `error`.
#### Manuell
- [ ] `uvicorn main:app --port 3000` startet ohne Feature-Module, `GET /` liefert JSON.
- [ ] WS-Smoke: `npm --prefix frontend run dev`, Konsole zeigt „connected“. `/debug/action` mit `contract\examples\radio_message.json` erscheint in der Browser-Konsole.

**Umsetzungsnotizen 0b:**
- Neue Tests: `test_gemini.py` (Deadline, Versuche, `use_fallback_model`, Budget, `agenerate`), `test_genai_log.py`, `test_hub.py`, `test_ws.py`, `test_main_loader.py`. Fixtures: `genai_log_lines`, `fresh_hub`. Builder: `audio_response`, `grounded_response`.
- Hub-Handler-Signatur: `fn(event, envelope)` bzw. `fn(payload_model, envelope)`, wie `net.on(type, (payload, env) => ...)` im Frontend.
- Budget-Ablehnung ist `HTTPException(503, "GenAI-Budget erschöpft: ...")` ohne Request und ohne Logzeile. Der Agent loggt danach seinen Fallback.
- Zwischendurch gemergt: PR #3 (setup-worktree.ps1 nur ASCII, Test `test_scripts_ascii.py`).

---

## Phase 1: Scheibe Welt (`feat/welt`, `..\ka-welt`, 13:00–16:00)

### Überblick
OSM-Stadt, Spieler, Kamera, Ballern, Auto, Fußgänger, HUD und `ctx`. Diese Scheibe liefert die Bühne und alle Client-Events. Sie entwickelt komplett mit `AGENTS_MODE=offline` und braucht 0 Gemini-Requests. Einen Rebase auf main nach 0b macht sie, sobald es passt; die Dateien sind disjunkt.

### Änderungen
**W1: Bake (ca. 50 min)**
- `scripts/bake_osm.py` (Python, nur Standardbibliothek)
  - Modus `--fetch`: einmalige Overpass-Abfrage für `building`, `highway` (ohne footway-Details), `leisure=park|garden` und `amenity=parking`. Bounding Box S 49.0075, W 8.3965, N 49.0160, E 8.4125 (ca. 0,95 × 1,17 km: Schloss, Schlossplatz, Marktplatz, Kaiserstraße). Ergebnis nach `data/osm/raw.json` (eingecheckt).
  - Modus `--bake` (Default, offline): liest `raw.json` und erzeugt:
    - `frontend/public/city/buildings.json` als `[{id, h, pts: [[x, z], ...]}]`. Höhe aus `height`, sonst `building:levels` × 3,2, sonst 12 m. Footprints vereinfacht (Douglas-Peucker 0,5 m), auf 0,1 m gerundet, im Uhrzeigersinn normalisiert.
    - `roads.json` als `[{id, kind, w, pts}]`.
    - `areas.json` (Grünflächen und Plätze).
  - Größenbudget: `buildings.json` ≤ 1,5 MB, `roads.json` ≤ 0,5 MB, `raw.json` ≤ 8 MB. Liegt ein Wert darüber, bricht das Skript mit Meldung ab.
- `tests/test_bake_osm.py`: auf einem kleinen eingebetteten OSM-Fixture prüfen:
  - Projektion über `geo.py`
  - Höhenregeln
  - Vereinfachung
  - Rundung
  - Budget-Prüfung
  - Das echte `raw.json` wird nicht neu geladen.

**W2: Kern und ctx (ca. 70 min, danach Checkpoint-Merge 14:45)**
- `frontend/src/core/`:
  - `renderer.js`: Scene, Licht, Nebel, Toon- oder Lambert-Materialien
  - `city.js`:
    - Gebäude per `ExtrudeGeometry`, mit `BufferGeometryUtils.mergeGeometries` nach Farbe gebündelt, unter 20 Draw-Calls
    - Straßen als flache Bänder, Grünflächen
    - ein statischer Trimesh-Collider für alle Gebäude
  - `physics.js`: `await RAPIER.init()`, World, fester Zeitschritt 1/60
  - `input.js`
  - `player.js`: Rapier `KinematicCharacterController`, WASD, Sprint, Third-Person-Kamera mit Maus-Orbit (Pointer-Lock)
  - `combat.js`:
    - Linksklick, `THREE.Raycaster` gegen die registrierten Ziele, Mündungsfeuer, Treffer-Feedback
    - HP-Verwaltung
    - sendet `npc_killed`, gebündelt `shot_fired`, `zone_entered` und `player_position`
  - `models.js`: Low-Poly-`car()` und `person()` aus Primitiven
  - `hud.js`: Sterne, Toast, Objective, Untertitel, Dialog, Panels
  - `attribution.js`: dauerhaft sichtbar „© OpenStreetMap contributors“ mit Link auf openstreetmap.org/copyright
  - `world.js`: `pois` (Import `../../data/pois.json`), `zoneAt` und `randomRoadPoint` über Punkte auf `roads.json`
  - `index.js`: baut `ctx` gemäß `types.js`, `start()` startet den Loop
- `features/` bleibt leer, Welt-Logik gehört in core/.
- `Design.md`: Abschnitte „Frontend-Kern“ und „OSM-Stadt“.

**W3: Fahrzeuge und Fußgänger (ca. 60 min)**
- `core/vehicle.js`: Rapier `DynamicRayCastVehicleController` (4 Räder, Federung, Lenkung), Ein- und Aussteigen mit F, Verfolgerkamera. Timebox 45 min, dann greift die Kürzungsoption.
- 6 bis 8 geparkte Zivilautos an Straßenpunkten. Einsteigen schickt `vehicle_stolen`.
- `core/pedestrians.js`: ungefähr 15 bis 20 Zivilisten, die zwischen Straßenpunkten laufen, als `combat`-Ziele (`civilian`, hp 1). Bei Schüssen in der Nähe fliehen sie.

**W4: Politur und Performance (ca. 30 min)**
- Ziel 60 fps auf dem Laptop, Ladezeit unter 3 s.
- Minimap optional.
- Prüfen, ob die Fehlerbehandlung beim WS-Reconnect sichtbar ist (HUD-Punkt rot oder grün).

### Schnittstellen zum Vertrag
- erzeugt alle 5 Events
- implementiert `ctx` vollständig
- `net.js`, `main.js` und `vite.config.js` gehören ab jetzt Welt
- `ctx` nur additiv ändern, Änderungen im Abschnitt „Frontend-Kern“ in Design.md ankündigen

### Kürzungsoption
Kinematisches Arcade-Auto statt Rapier-Vehicle-Controller: Fahrradmodell, Character-Controller für Kollisionen, gleiche Schnittstelle `ctx.player.inVehicle()`. Letzte Stufe: kein Auto, nur Sprint. Das ist laut globaler Reihenfolge die letzte Kürzung insgesamt.

### Erfolgskriterien
#### Automatisch
- [x] `scripts\check.ps1` grün, einschließlich `tests/test_bake_osm.py` und Frontend-Build (auf main nach PR #7 geprüft)
- [x] `python scripts/bake_osm.py` (offline) reproduziert die eingecheckten `city/*.json` byte-gleich (sha256 geprüft: 959 Gebäude, 1546 Straßen, 230 Flächen, zusammen 345 KB; `raw.json` 1,46 MB)
#### Manuell
- [x] Stadt erkennbar: Schloss mit Fächerstraßen, Marktplatz, Kaiserstraße. Die Attribution ist sichtbar.
- [x] Laufen ohne Durchdringen von Gebäuden, Schießen trifft Fußgänger, `npc_killed` erscheint im Backend-Log (`AGENTS_MODE=offline`).
- [x] `/debug/action` mit `set_wanted_level` → Sterne im HUD.
- [x] Checkpoint: Spieler, Ballern, Events und `ctx` sind auf main gemergt (PR #7, Merge-Commit `7157031`, W1 + W2 + Fußgänger aus W3).
- [x] Auto: einsteigen, fahren, Kollision mit Gebäude, aussteigen. `vehicle_stolen` kommt an. (PR #10, Merge-Commit `b2960ab`, zusammen mit dem Look-Pass: HDRI, Schatten, ACES, Fassaden, GTAO, Bloom; Rapier-Vehicle-Controller, keine Kürzung nötig)

---

## Phase 2: Scheibe Polizei und Spielzustand (`feat/polizei`, `..\ka-polizei`, 13:35–16:10)

### Überblick
Wahrheit über die Fahndung, Agent-Runner, Polizei-Dispatcher, Fallback, Clamps und die clientseitige Verfolgung. Vorher den Skill `gemini-api-dev` laden.

### Änderungen
**P1: `game_state.py` (ca. 40 min)**
- `register(hub)`: abonniert alle Events, speichert Spielerzustand und Zone, einen Ringpuffer der letzten 50 Events oder 120 s und Zähler für 60 s.
- Regel-Boden:
  - `shot_fired`, `npc_killed` (außer `gang`/`quest_target`, die zählen aber über `shot_fired`) und `vehicle_stolen` heben bei Level 0 sofort auf 1 (`source: "rules"`).
  - Bei Level ≥ 1 aktualisieren sie `last_crime`.
- `startup`: Decay-Task. Nach `WANTED_DECAY_S` ohne Verbrechen sinkt das Level um 1.
- Einheiten:
  - Beobachtet `spawn_units`. `units_active` ergibt sich aus der Summe, abzüglich `npc_killed` vom Typ `police`.
  - Bei Level 0 ist die Summe 0.
- `snapshot(agent, memory) -> AgentSnapshot`, einschließlich `hub.snapshot_extras()` und `places` aus den POIs.
- Snapshot-Provider `wanted`.
- `on_connect`: aktuelles `set_wanted_level`.
- Router `GET /debug/state` (nur mit Flag).
- `tests/test_game_state.py`: Regel-Boden, Decay mit Fake-Uhr, Einheitenbilanz, Snapshot-Größe unter 2 KB.

**P2: `runner.py` und `agents/police.py` (ca. 60 min)**
- `runner.py`: `AgentSpec`, `register_agent`, Sammelfenster und Mindestabstand, ein Call gleichzeitig, `wait_for`, Generationszähler.
  - Fallback bei `not gemini.live_enabled()`, Timeout, `HTTPException` oder anderer Exception.
  - Jeder Fallback wird mit `genai_log.log_fallback` geloggt, dadurch erscheint er im Overlay.
  - Uhr injizierbar.
- `agents/police.py`:
  - System-Prompt (EN): „Karlsruhe police dispatcher. You only set parameters …, radio in short police jargon, name real places.“
  - Drei `FunctionDeclaration`s:
    - `set_wanted_level(level, reason)`
    - `spawn_units(target_units, unit_type, tactic, near_place_id?, reason)`: `target_units` ist die gewünschte Gesamtzahl aktiver Einheiten. Der Server schickt `count = target_units − units_active` (geclampt).
    - `radio_message(text, reason)`
  - Config:
    - `tool_config` mit `function_calling_config.mode = "ANY"`
    - `thinking_level` aus der Config
    - Aufruf: `gemini.agenerate(..., agent="police", attempts=AGENT_ATTEMPTS, timeout_ms=AGENT_DEADLINE_MS, use_fallback_model=False)`
  - Trigger: `shot_fired`, `npc_killed`, `vehicle_stolen`; `zone_entered` nur bei Level ≥ 1. Mindestabstand `POLICE_MIN_INTERVAL_S`.
  - Clamp:
    - Level in [Boden, 5]. Der Boden ist 1, solange das letzte Verbrechen weniger als `WANTED_DECAY_S` her ist.
    - Pro Zyklus ändert sich das Level um höchstens ±`WANTED_MAX_STEP`.
    - `count = min(target_units, POLICE_MAX_UNITS) − units_active`. Ist das ≤ 0, wird die Aktion verworfen.
    - Ungültige Enums bekommen Defaults (`patrol`/`chase`).
    - Unbekannte `near_place_id` wird null.
    - Funktext getrimmt auf ≤ `RADIO_MAX_CHARS`, leer wird verworfen.
    - Pro Tool höchstens ein Call, unbekannte Tools ignorieren.
  - Fallback, deterministisch:
    - Level = min(5, Boden + Tote der letzten 60 s)
    - Einheiten bis Level
    - Funk aus 5 englischen Vorlagen mit Zonennamen
  - Gedächtnis: höchstens 5 Zeilen Zusammenfassung pro Zyklus.
- Tests mit `fake_gemini` und `call_response`:
  - `tests/test_runner.py`: Debounce bündelt 10 Events zu 1 Zyklus, Mindestabstand, Deadline führt zum Fallback, offline führt zum Fallback ohne Call, verspätetes Ergebnis wird verworfen
  - `tests/test_police.py`:
    - Clamps (count 9 → 6 bzw. Rest, Level 5 → 3 bei Start 1)
    - Nach 3 parallelen Calls kommen 3 Aktionen
    - Es gibt genau 1 `generate_content`-Call pro Zyklus
    - E2E über TestClient-WS mit `config.AGENT_DEBOUNCE_S` per monkeypatch auf 0: `npc_killed` rein, `set_wanted_level` + `spawn_units` + `radio_message` raus

**P3: `frontend/src/features/police.js` (nach dem Rebase auf den Welt-Checkpoint, ca. 50 min)**
- `set_wanted_level` → `hud.setWanted`. Bei 0 alle Einheiten entfernen.
- `spawn_units` → `count` Polizeiautos (`ctx.models.car({police: true})`) an `randomRoadPoint(player, 120, 200)` oder in der Nähe des POI.
  - Blaulicht
  - Verfolgung per Kinematic-Character-Controller
  - Taktiken:
    - `chase`: direkt auf den Spieler zu
    - `roadblock`: zu einem Punkt 60 m vor dem Spieler in Blickrichtung fahren und halten
    - `surround`: 4 Offsets um den Spieler
  - Geschwindigkeit nach Level
  - `combat.addTarget(kind "police", hp 3)`
- `faction: "gang"` wird nicht gesendet (Gang-Boss gestrichen), police.js muss sie nicht behandeln.

**P4: Live-Check und Tuning (ca. 15 min, höchstens 10 Requests)**
- Einmal `AGENTS_MODE=live`: drei Schießerei-Szenen.
- Prüfen: Latenz in `logs/genai.jsonl`, sinnvolle Calls, Clamps greifen.
- Prompt nachschärfen.

**P5 (Gang-Boss): gestrichen am 2026-11-14.** Kein `agents/gang.py`, keine Gang-Schlüssel in `config.py`.

### Schnittstellen zum Vertrag
- Konsumiert die Events.
- Erzeugt `set_wanted_level`, `spawn_units` und `radio_message` (über `make_radio_message`).
- Snapshot-Provider `wanted`.
- Liest `extras.quest` von Scheibe 3, falls vorhanden.
- Nutzt `ctx.models`, `ctx.world`, `ctx.combat` und `ctx.hud`.

### Kürzungsoption
Gang-Boss (`agents/gang.py`) streichen. Das ist die erste Kürzung insgesamt. **Gezogen am 2026-11-14.**

### Erfolgskriterien
#### Automatisch
- [ ] `scripts\check.ps1` grün, einschließlich `test_game_state.py`, `test_runner.py` und `test_police.py`
- [ ] Test belegt: maximal 1 Gemini-Request pro Polizei-Zyklus, 0 Requests bei `AGENTS_MODE=offline`
#### Manuell
- [ ] Offline: schießen → sofort 1 Stern. Nach ca. 5 s Fallback-Einheiten und Funk-Untertitel, im Overlay bzw. in der Konsole mit `FALLBACK`.
- [ ] Live (P4): Agent setzt Level und Einheiten passend zur Szene. Antwort unter 2 s, keine hängende Demo bei künstlich niedriger Deadline (`AGENT_DEADLINE_MS=1`).
- [ ] 30 s ohne Verbrechen → Level sinkt. Bei 0 verschwinden die Einheiten.

---

## Phase 3: Scheibe Quest, Maps und TTS (`feat/quest`, `..\ka-quest`, 13:35–16:20)

### Überblick
Quest-NPC hinter `POST /npc/talk`, Quest-Wahrheit per Position, Maps-Fakten und Polizeifunk-TTS. Vorher den Skill `gemini-api-dev` laden und für TTS und Maps die Doku-Seiten lesen (`speech-generation.md`, `maps-grounding.md`).

### Änderungen
**Q0: Live-Checks (ca. 10 min, genau 2 Requests, Ergebnis in `agent_docs/gemini_api.md`)**
- TTS: ein `generate_content` mit `GEMINI_MODEL_TTS`.
  - Config: `response_modalities=["AUDIO"]` und `speech_config` mit `voice_config` → `prebuilt_voice_config(voice_name=TTS_VOICE)`.
  - Festhalten: MIME-Typ (WAV oder L16/PCM), Latenz, Fehlercode.
  - Bei 404 `gemini-3.8-flash-tts` probieren. Scheitert auch das, sofort die TTS-Kürzung ziehen.
- Maps: ein `generate_content` mit `GEMINI_MODEL_MAPS` und `tools=[Tool(google_maps=GoogleMaps())]` zum Schloss.
  - Festhalten: wo die Quellen im Response stehen (`candidates[0].grounding_metadata.grounding_chunks[].maps`?), außerdem Latenz.

**Q1: `quests.py` (ca. 40 min)**
- `QuestBook`: eine aktive Quest plus Historie.
  - `create(poi_id, title, objective, enemies)` validiert die POI-ID gegen `load_pois()` und clampt `enemies` auf 1 bis `QUEST_MAX_TARGETS`.
- `register(hub)`:
  - `player_position`: Ist die Distanz zum POI ≤ `radius`, gilt `target_reached` mit `spawn_targets = remaining = n`.
  - `npc_killed`: Bei `quest_target` und passender `quest_id` sinkt `remaining`. Bei 0 ist die Quest `completed`.
  - Jeder Statuswechsel geht als `quest_update` per `hub.send_action`.
  - `on_connect` liefert die aktive Quest. Snapshot-Provider ist `quest`.
- `fallback_quest(npc)`: zufälliger `mission`-POI außerhalb der aktuellen Zone, Titel aus Vorlagen.
- `tests/test_quests.py`:
  - Position außerhalb/innerhalb des Radius
  - Kills mit falscher und mit richtiger `quest_id`
  - unbekannte POI-ID wird abgelehnt
  - Reconnect liefert die aktive Quest

**Q2: `maps_facts.py` und `agents/quest.py` (ca. 60 min)**
- `maps_facts.get_facts(poi) -> {facts: str, sources: [{title, uri}]}`
  - englischer Prompt, 2 kurze Sätze für Missions-Flavor
  - gecacht im Speicher und unter `MAPS_CACHE_PATH`
  - Fehler oder offline → `poi.description` und keine Quellen
- `agents/quest.py`: Router `POST /npc/talk` mit `NpcTalkRequest`.
  - NPCs aus `data/npcs.json`: `[{id, name, persona, poi_id, x, z}]`, z. B. „Karl the Fixer“ am Schlossplatz.
  - System-Prompt (EN) mit Persona und kompakter Liste der `mission`-POIs (id und Name).
  - Gedächtnis: letzte 6 Sätze pro NPC.
  - Tools:
    - `lookup_place(place_id, reason)`: liefert POI und `maps_facts`
    - `assign_quest(place_id, title, objective, enemies, npc_line, reason)`: beendet den Loop. Bei unbekannter ID oder schon aktiver Quest kommt `{"error": ...}` zurück, das Modell darf neu wählen.
  - Tool-Loop wie in main.py:251-288 (Modell-Turn unverändert, `id` zurück), höchstens `QUEST_MAX_STEPS`, Gesamt-Deadline `QUEST_DEADLINE_MS` über `asyncio.wait_for`.
  - Fallback: `fallback_quest` plus Vorlagensatz, `fallback: true`.
  - Antwort `NpcTalkResponse` mit `sources` aus `maps_facts`.
- Tests:
  - `tests/test_maps_facts.py`: Quellen werden extrahiert, Cache verhindert den zweiten Call, offline ergibt 0 Calls
  - `tests/test_quest_agent.py`:
    - Loop `lookup_place` → `assign_quest` ergibt 2 Calls und eine Quest
    - falsche ID führt zum Retry im Loop
    - Deadline führt zum Fallback mit HTTP 200
    - unbekannter NPC ergibt 404

**Q3: `tts.py` (ca. 30 min)**
- `register(hub)`: `on_action("radio_message")` startet `asyncio.create_task(synthesize(...))`, sofern nicht im Cache.
- `synthesize`: `gemini.agenerate(..., agent="tts", attempts=1, timeout_ms=TTS_DEADLINE_MS)`.
  - Inline-Bytes lesen. Bei L16/PCM selbst einen WAV-Header schreiben (24 kHz, mono, 16 bit).
  - Ablage `TTS_CACHE_DIR/{key}.wav`.
  - Offline → nichts tun.
- Router `GET /tts/{key}.wav`:
  - Cache vorhanden → FileResponse.
  - Laufend → bis zur Deadline warten.
  - Sonst 404.
  - `key` per Regex `^[0-9a-f]{16}$` validieren.
- `scripts/prewarm.py`: wärmt Maps-Fakten für alle `mission`-POIs vor (höchstens 10 Calls) und optional die 5 Fallback-Funksätze (höchstens 5 Calls). Läuft vor der Demo.
- `tests/test_tts.py`: Cache-Treffer ergibt 0 Calls, PCM wird zu WAV, ungültiger Key ergibt 404, offline erzeugt keinen Task.

**Q4: Frontend (nach dem Rebase auf den Welt-Checkpoint, ca. 60 min)**
- `features/npc.js`:
  - NPCs aus `data/npcs.json` als `ctx.models.person`, „Press E to talk“ unter 3 m
  - `POST /npc/talk` mit `hud.showDialog({pending: true})`. Das Spiel läuft weiter, man kann weggehen.
  - Antwort mit Quellenzeile direkt unter dem Text: `Source: <span translate="no">Google Maps</span> · <a href=uri>title</a>`
- `features/quest.js`:
  - `quest_update` → `hud.setObjective`, Zielmarker (Lichtsäule) und Richtungspfeil
  - Bei `target_reached` werden `spawn_targets` Gegner im POI-Radius erzeugt (`combat.addTarget(kind "quest_target", questId)`). Sie laufen auf den Spieler zu und zeigen Mündungsfeuer ohne Schaden.
  - Bei `completed`: Toast „Mission complete“, Marker entfernen
- `features/radio.js`:
  - `radio_message` → sofort `hud.subtitle("Dispatch: …")`
  - dann `/tts/{key}.wav` laden und über WebAudio mit Funkfilter abspielen (Bandpass 300–3000 Hz und leichtes Rauschen)
  - bei 404 oder nach 6 s Timeout: `speechSynthesis` (en-US)

**Q5: Design.md und agent_docs (ca. 10 min)**
Abschnitte Quest-NPC, Maps-Fakten und Polizeifunk-TTS. In `agent_docs/gemini_api.md` neue Abschnitte zu TTS und Maps mit den Ergebnissen aus Q0.

### Schnittstellen zum Vertrag
- `POST /npc/talk`
- `quest_update`
- `GET /tts/{key}.wav`
- konsumiert `player_position`, `npc_killed` (`quest_id`) und `radio_message` (Beobachter)
- Snapshot-Provider `quest`
- Inhaber von `data/pois.json` (nur Beschreibungen und Tags, die IDs bleiben)

### Kürzungsoption
In der globalen Reihenfolge:
1. **TTS** streichen: `tts.py` entfällt, `radio.js` nutzt nur `speechSynthesis`.
2. **Maps Grounding** streichen: `maps_facts.py` entfällt, `lookup_place` liefert `description` aus `pois.json`, keine Quellenzeile.

**Stand 15:30:** Beide Kürzungen gezogen. Q0 ergab TTS 400 (`speechConfig` unbekannt) und Maps 429 (quota exceeded), Details in `agent_docs/gemini_api.md`.

### Erfolgskriterien
#### Automatisch
- [x] `scripts\check.ps1` grün, einschließlich `test_quests.py`, `test_quest_agent.py` (`test_maps_facts.py` und `test_tts.py` entfallen mit den Kürzungen 1 und 2)
- [x] Test belegt: `/npc/talk` liefert bei jedem Gemini-Fehler HTTP 200 mit `fallback: true`
#### Manuell
- [ ] Q0 dokumentiert: TTS-Modell aufrufbar ja/nein, MIME-Typ, Latenz. Maps-Quellenpfad.
- [ ] Offline: NPC gibt eine Fallback-Quest, Marker erscheint, Ankunft spawnt Gegner, nach dem Erschießen ist die Quest erfüllt.
- [ ] Live (höchstens 10 Requests): Dialog nennt einen echten Fakt mit Google-Maps-Quelle, Funkspruch ist als WAV mit Funkfilter hörbar.

---

## Phase 4: Overlay und Abgabe (Haupt-Checkout, 16:30–18:00)

### Überblick
Das Agent-Log-Overlay macht die Agenten sichtbar. Dazu kommen README, Sicherheits-Scan, Build-Commit und Demo-Ablauf.

### Änderungen
1. **`frontend/src/features/agent-log.js` (ca. 30 min)**
   - `hud.addPanel("agent-log")`, die letzten 12 `agent_log`-Einträge, Taste L zum Umschalten
   - pro Zeile: Uhrzeit, farbiger Agent-Chip, `tool(args)`, `reason`, Latenz, kurzes Modell, Badges `FALLBACK` bzw. `ERROR` und `#call_no`
   - Zähler „Gemini calls this session“
   - Design.md-Abschnitt „Agent-Log-Overlay“
2. **`README.md` (EN, ca. 30 min)**
   - Pitch, Link zum Demo-Video, Architekturdiagramm
   - Setup: venv, `npm install`, `.env`, `npm run build`, uvicorn, `/play/`
   - Steuerung
   - Agentenbeschreibung
   - APIs, Frameworks und Tools: Gemini API über google-genai (Function Calling, Maps Grounding, TTS, genutzte Modelle), FastAPI, uvicorn, Pydantic, Three.js, Rapier, Vite, OpenStreetMap/Overpass (ODbL), Claude Code, ruff, pytest, gitleaks, optional Codesphere
   - Kosten-Guards (Budget, Offline-Modus)
   - Lizenz- und Attributionshinweise (OSM, Google Maps, HDRI „Kloofendal 48d Partly Cloudy (Pure Sky)“ von Poly Haven, CC0)
3. **`test.py` löschen.** Den letzten Stand von CLAUDE.md und `agent_docs` prüfen.
4. **Secret-Scan (ca. 10 min)**
   - `gitleaks detect --source . --log-opts="--all"` (Binary per `winget install gitleaks` oder aus dem GitHub-Release)
   - zusätzlich `git log -p --all | Select-String -Pattern "AIza[0-9A-Za-z_-]{35}"` muss leer sein (echtes Key-Format; Test-Dummys und diese Zeile passen nicht darauf)
   - prüfen, dass `logs/`, `cache/` und `.env` nicht getrackt sind
5. **Build-Commit (ca. 10 min):** `static/` aus `.gitignore` nehmen, `npm --prefix frontend run build`, `git add static`. Das Repo läuft danach ohne Node.
6. **`ci.yml` (optional, ca. 20 min):** unverändert Python-only, weil `static/` committet ist. Deploy laut `agent_docs/codesphere_deploy.md`, dort `AGENTS_MODE=live` und das Budget setzen.
7. **`docs/demo.md` (ca. 20 min), Ablauf des Videos (2:00)**
   - Vorbereitung:
     - `python scripts/prewarm.py`
     - `AGENTS_MODE=live`
     - Server auf 3000, Browser im Vollbild, Overlay an
   - 0:00–0:10: Titel, Kamera über dem Schloss
   - 0:10–0:35: NPC-Dialog mit Quest, Maps-Quelle und Overlay-Calls (`lookup_place`, `assign_quest`)
   - 0:35–0:55: zum Marktplatz fahren
   - 0:55–1:25: Schießerei, Stern sofort, Funk (TTS), Overlay zeigt `police` mit `spawn_units` und `reason`, Polizeiautos rücken an
   - 1:25–1:40: Quest erfüllt
   - 1:40–2:00: Architekturfolie (Gemini-Features, Request-Budget, „nothing is scripted, but nothing waits for the LLM“)
   - Sicherungs-Take um 17:30, finaler Take 18:15–18:45

### Kürzungsoption
Codesphere-Deploy (`ci.yml`) streichen.

### Erfolgskriterien
#### Automatisch
- [ ] `scripts\check.ps1` grün auf main
- [ ] gitleaks: „no leaks found“
#### Manuell
- [ ] Demo-Pfad live einmal komplett durchgespielt. Die Zahl der Zeilen in `logs/genai.jsonl` für den Lauf liegt unter 40.
- [ ] Demo-Pfad offline einmal komplett durchgespielt (Fallback-Probe)
- [ ] Frischer Clone in einem temporären Ordner: Das README-Setup funktioniert Schritt für Schritt.
- [ ] Video unter 2:00, Repo public, README-Link zum Video

---

## Merge-Reihenfolge und Merge-Checks

1. `feat/vertrag` (0a) → `feat/kern` (0b): sofort, per PR (TEAM.md: kein direkter Push auf main).
2. **Welt-Checkpoint um 14:45** (W1–W2): Danach rebasen Polizei und Quest auf main (`git fetch; git rebase origin/main`).
3. **16:00 Welt final** → **16:10 Polizei** → **16:20 Quest.** Die Reihenfolge folgt den Abhängigkeiten: Die Features brauchen `ctx`, und Quest liefert den Snapshot-Provider für Polizei, nicht umgekehrt.

Ablauf pro Merge, im Haupt-Checkout:
```powershell
git pull; gh pr create --base main --head feat/<x> --fill; gh pr merge feat/<x> --merge
git pull
scripts\check.ps1                                # muss grün sein, einschließlich Frontend-Build
.venv\Scripts\uvicorn main:app --port 3000      # AGENTS_MODE=offline
# Browser: http://localhost:3000/play/  -> manueller Smoke-Check der gemergten Scheibe (Liste in der Phase)
```
- Konflikte in Design.md, `config.py` oder `.env.example` blockweise zusammenführen. Andere Konflikte bedeuten eine Verletzung des Datei-Besitzes: stoppen und klären.
- Nach dem Merge von Quest: ein Live-Lauf des Demo-Pfads (höchstens 40 Requests) vor dem Freeze.

## Request-Volumen (Schätzung)

| Quelle | Auslöser | Requests | Pro Demo-Minute mit Action |
|---|---|---|---|
| Polizei | Fenster ≥ 5 s, Abstand ≥ 8 s, 1 Request pro Zyklus | 1 | maximal 7,5, typisch 3–4 |
| TTS | jeder neue Funktext (Cache) | 1 | höchstens so viele wie Polizei, typisch 2–3 |
| Quest | pro NPC-Gespräch, höchstens 3 Schritte | typisch 2 | 1–2 Gespräche, also 2–4 |
| Maps | pro POI bei Cache-Fehlschlag | 1 | 0 nach Prewarm |
| **Summe** | | | **typisch 8–12, höchstens ca. 20** |

- 2-Minuten-Demo: ungefähr 20 bis 25 Requests.
- Entwicklung: Die Worktrees laufen offline, jeder hat ein Budget von 60, bewusste Live-Checks liegen bei etwa 10 bis 20 pro Scheibe.
- Rehearsals: etwa 3 × 40.
- **Tagessumme unter 400 Requests**, weit unter „Tausenden“.
- Harte Grenzen pro Prozess: `GENAI_MAX_CALLS_PER_MIN=30` und `GENAI_MAX_CALLS_TOTAL`.

## Risiken

| Risiko | Wirkung | Gegenmaßnahme |
|---|---|---|
| **Rapier im Browser** (WASM-Init, Tuning des Vehicle-Controllers) | Fahrgefühl frisst die Zeit von Scheibe 1 | `@dimforge/rapier3d-compat` (WASM inline, kein Vite-Plugin). Vehicle-Controller mit 45 min Timebox, danach Arcade-Auto (Kürzungsoption). Trimesh-Collider ist statisch. Wenn er zu langsam ist: Cuboid-Collider nur im Umkreis von 300 m. |
| **Overpass-Größe und -Erreichbarkeit** | Bake hängt, Daten zu groß. overpass-api.de und kumi.systems waren nicht erreichbar, nur mail.ru (getestet in 0a). | Box klein (ca. 1,1 km², geschätzt 1.000–3.000 Gebäude, Rohdaten 2–6 MB). Nur einmal holen und `raw.json` einchecken. Mirror `https://maps.mail.ru/osm/tools/overpass/api/interpreter` funktioniert. Größenbudget im Skript. Draw-Calls durch zusammengeführte Geometrie. |
| **Agent-Latenz** | Spiel wirkt träge | Regel-Boden reagiert sofort. Flash-Lite gemessen mit 0,5–0,8 s Median. `AGENT_DEADLINE_MS=6000`, danach Fallback. Kein Backoff im Spiel. Verspätete Ergebnisse werden verworfen. 503-Spitzen beim Fallback-Modell (2/6 in der Messung) landen im Fallback. |
| **Request-Volumen und Missbrauchsgrenze** | Disqualifikation | Default `AGENTS_MODE=offline`, Budget pro Prozess, Debounce ≥ 5 s, 1 Request pro Polizei-Zyklus, Caches für TTS und Maps, Overlay-Zähler macht das sichtbar. Schätzung oben. |
| **TTS-Modell nicht gelistet** | Kein Funk-Audio | Q0-Live-Check gleich zu Beginn. Browser-`speechSynthesis` als eingebauter Fallback, Kürzung 2. |
| **Maps über `generate_content` nur durch SDK-Test belegt, nur Englisch, Attributionspflicht** | Kein Flavor, Lizenzverstoß | Q0-Live-Check. Spielsprache ist ohnehin Englisch. Quellenzeile im Dialog ist Pflicht und Teil von Q4. Kürzung 3. |
| **Per-Request-Timeout über `http_options`** | Deadline wirkt nicht serverseitig | In 0b an der SDK-Quelle prüfen. `asyncio.wait_for` im Runner greift unabhängig davon. |
| **Threads und Event-Loop** | Race-Conditions | `generate` läuft per `to_thread`. Aktionen aus Threads nur über `send_action_threadsafe`. Hub-Handler machen keine Blocker. |
| **Merge-Konflikte** | Zeitverlust kurz vor dem Freeze | Besitzmatrix, Schlüssel vorab in 0a, Checkpoint-Merge um 14:45, gestaffelte Merges ab 16:00 |
| **Zeitplan** | Demo unvollständig | Kürz-Entscheidung um 15:30 nach der globalen Reihenfolge Gang-Boss → TTS → Maps Grounding → Auto. Sicherungs-Take um 17:30. |

## Teststrategie

- **Unit**: Protokoll und Beispiele, Projektion, Bake (Fixture), JSONL-Log, Budget, Hub, Runner (Fake-Uhr), Clamps, Quest-Zustand, TTS-Cache und WAV-Header, Maps-Cache.
- **Integration**: TestClient-WebSocket.
  - Event rein → Aktionen raus (Polizei offline und mit `fake_gemini`)
  - `/npc/talk` mit `fake_gemini`: Loop, Fehler, Deadline
- **Kosten-Invarianten als Tests**:
  - 1 Request pro Polizei-Zyklus
  - 0 Requests offline
  - Cache verhindert Wiederholungen
  - Budget stoppt vor dem Request
- **Nie live in Tests**. Die autouse-Blockade bleibt, `AGENTS_MODE=offline` ist die Test-Default-Einstellung.
- **Manuell**: Smoke-Checks pro Phase, Demo-Pfad offline und live, frischer Clone.
- Frontend ohne Unit-Tests. Abgesichert durch Build-Stufe, `/debug/action` mit den Vertragsbeispielen und manuelle Checks.

## Vergleich mit dem Referenzspiel des Kollegen

Die Datei selbst haben wir nicht gesehen. Der Vergleich bezieht sich auf das Muster „ein mit Gemini generiertes GTA-artiges Three.js-Spiel in einer HTML-Datei“.

| | Referenz (typisch One-Shot) | Dieser Plan |
|---|---|---|
| Stadt | Fantasie-Raster | echtes Karlsruhe aus OSM, mit Attribution |
| KI | geskriptete Zustandsmaschinen im Client | Gemini-Agenten auf dem Server mit Function Calling, Gedächtnis, Clamps und Fallback |
| Gemini-Features | höchstens Codegenerierung | Function Calling, Maps Grounding, TTS und Live-Log der Calls |
| Robustheit | – | Spiel wartet nie, Offline-Modus, Request-Budget, Tests ohne Live-Calls |
| Struktur | eine Datei | Vertrag plus Module, 3 parallele Scheiben |
| Wo die Referenz vorne liegt | Steuerung und Spielgefühl sofort vorhanden | Unser Risiko: Scheibe 1 muss das Spielgefühl in ca. 3 h liefern. Deshalb gibt es den Checkpoint um 14:45 und die Auto-Kürzung. |

Die Bewertungskriterien sind Kreativität, technische Komplexität und Partner-Tech. Bei allen drei liegt der Plan klar vorn, solange der Demo-Pfad flüssig läuft. Das Spielgefühl ist der Punkt, an dem man verlieren kann.

## Referenzen

- Gemini-Infrastruktur: `main.py:36-124` (`generate`), `main.py:251-288` (Tool-Loop), `config.py:40-75`, `agent_docs/gemini_api.md`
- Tests: `tests/conftest.py`, `tests/fakes.py`, `tests/test_api.py:68-91` (Loop-Test-Muster)
- Deploy: `ci.yml`, `agent_docs/codesphere_deploy.md`
- SDK: `.venv/Lib/site-packages/google/genai/types.py:4007` (`GoogleMaps`), `:6616` (`http_options`), `:5756` (`SpeechConfig`); `tests/models/test_generate_content_tools.py:649`
- Doku: aistudio.google.com/docs/maps-grounding.md, `/tool-combination.md`, `/speech-generation.md`, `/function-calling.md`
- Skill: `.claude/skills/gemini-api-dev/SKILL.md`
