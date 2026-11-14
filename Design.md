# Design

Lebendes Design-Dokument. Jedes Feature bekommt unter "Features" einen eigenen Abschnitt, der bei jeder Änderung nachgezogen wird (Regel in CLAUDE.md).

## Architektur

```
Browser (Three.js + Rapier, Vite)                    FastAPI :3000 (main.py)
 core/: Stadt, Spieler, Auto, Ballern,    WS /ws      ws.py -> hub.py (Event-/Action-Bus)
   HUD, net.js                         <=========>      |- game_state.py  Fahndung, Wahrheit
 features/*.js registrieren Handler:    Envelope        |- runner.py      Debounce, Clamp, Fallback
   police.js, npc.js, quest.js,                         |    '- agents/police.py
   radio.js, agent-log.js              POST /npc/talk   |- quests.py      Quest-Prüfung per Position
                                       ------------->   |- agents/quest.py + maps_facts.py
                                       GET /tts/k.wav   '- tts.py         async + Cache
                                       ------------->  gemini.py: generate() + Budget + genai_log.py
                                                         -> logs/genai.jsonl -> agent_log per WS
                                                         -> Gemini API (google-genai)
```
Umsetzungsplan mit Scheiben, Datei-Besitz und Zeitplan: `docs/plans/2026-11-14-faecherstadt.md`.

### Frontend
- Three.js für das Rendering, Rapier für die Physik. Beides läuft im Browser. Vite für Dev, `npm run build` nach `static/`, FastAPI liefert das Spiel unter `/play/` aus.
- Der Client ist zuständig für Physik, Treffer und Bewegung. Er meldet Events, der Server entscheidet über Fahndung, Quests und Agenten.
- Das Agent-Log-Overlay zeigt die GenAI-Calls der Agenten live an (Format siehe "Vertrag").

### Backend
- FastAPI. Der Spielverkehr läuft über WebSocket (`/ws`), der Quest-Dialog über `POST /npc/talk`, Funk-Audio über `GET /tts/{key}.wav`.
- HTTP-Endpoints: `GET /` (Healthcheck, ruft Gemini nie auf), `/chat` und `/agent` aus dem Starter zum Debuggen.
- Das Spiel wartet nie auf das LLM. Agenten ändern nur Parameter (Level, Anzahl, Taktik, Funk); bei Fehler, Timeout, `AGENTS_MODE=offline` oder erschöpftem Budget greifen geskriptete Fallbacks.

### Agenten
- Polizei-Dispatcher und Quest-NPC (Gang-Boss am 2026-11-14 gestrichen). Jeder Agent bekommt eine eigene Datei und einen eigenen Abschnitt unter "Features".
- Modell und Limits je Agent kommen aus `config.py`.

### Karte (OpenStreetMap, vorgebacken)
- OSM-Daten werden vorab in statische Assets umgewandelt und mit dem Frontend ausgeliefert. Zur Laufzeit gibt es keine OSM-Abfragen.
- Die Lizenz (ODbL) verlangt den Hinweis "© OpenStreetMap-Mitwirkende" im Spiel.

### Querschnitt
- Konfiguration: Modellnamen, Agent-Limits, Timeouts und Retries nur in `config.py`, per Env-Var überschreibbar.
- Logging: jeder GenAI-Call als eine JSON-Zeile (Zeitstempel, Agent, Modell, Prompt, Config, Output). Inline-Daten nur als Platzhalter. Quelle für das Agent-Log-Overlay.
- Secrets: nur aus der Umgebung, nie in Code oder Logs. Das Repo ist public.
- Fehler: 429 heißt Spend-Cap und wird nicht wiederholt. Bei 503 wird auf das Fallback-Modell ausgewichen.

## Vertrag

Verbindliche Schnittstellen zwischen Browser, Server und Agenten. Code: `protocol.py` (Pydantic-Modelle), Beispiele: `contract/examples/*.json` (pytest validiert jedes gegen `protocol.py`). Seit Schritt 0 gilt: Felder nur additiv ändern, nie umbenennen. Events vom Client sind tolerant (unbekannte Felder werden ignoriert), alles vom Server ist strikt.

### Koordinaten
- Meter, Ursprung Schloss Karlsruhe (lat 49.0135, lon 8.4044). **x = Ost, y = oben, z = Süd** (z = −Nord, Three.js-Konvention: Norden zeigt nach −z).
- Einzige Projektion: `geo.py` (`to_local(lat, lon) -> (x, z)`, `to_latlon(x, z)`), äquirektangulär, R = 6 371 008,8 m. Bake-Bereich `geo.BAKE_BBOX` = (S 49.0075, W 8.3965, N 49.0160, E 8.4125).
- `heading` in Radiant (Rotation um y), `speed` in m/s. Koordinaten außerhalb ±5000 m sind ungültig.

### WebSocket `/ws`: Envelope
```json
{"type": "shot_fired", "ts": 1763125392123, "payload": {}}
```
- `type`: String aus den Tabellen unten. `ts`: int, Unix-Zeit in ms, gesetzt vom Sender. `payload`: Objekt gemäß Modell.
- Ungültige Nachrichten: Der Server verwirft sie und antwortet mit `error`, die Verbindung bleibt offen.
- Server-Limit: höchstens `WS_MAX_EVENTS_PER_S` Events pro Sekunde und Client, der Rest wird verworfen (`error` mit `rate_limited`).
- Beim Verbinden schickt der Server den aktuellen Zustand nach: `set_wanted_level` und, falls aktiv, `quest_update`.

### Events: Client -> Server
| type | payload | Hinweise |
|---|---|---|
| `player_position` | `x: float, z: float, heading: float, speed: float 0–200, in_vehicle: bool, zone_id: str\|null` | höchstens 2 Hz (Client drosselt), löst nie einen Agenten aus |
| `shot_fired` | `x, z, shots: int 1–50, weapon: "pistol"\|"smg", zone_id` | Client bündelt Schüsse pro 500 ms |
| `npc_killed` | `npc_id: str, npc_kind: "civilian"\|"police"\|"gang"\|"quest_target", x, z, zone_id, quest_id: str\|null` | sendet nur `core/combat` |
| `vehicle_stolen` | `vehicle_id: str, vehicle_kind: "civilian"\|"police", x, z, zone_id` | |
| `zone_entered` | `zone_id: str, previous_zone_id: str\|null` | Zone = POI, in dessen `radius` der Spieler steht |

### Aktionen: Server -> Client
| type | payload | Hinweise |
|---|---|---|
| `set_wanted_level` | `level: int 0–WANTED_MAX (5), source: "rules"\|"agent"\|"fallback", reason: str ≤160` | Level 0: Client entfernt alle Polizei-Einheiten |
| `spawn_units` | `wave_id: str, faction: "police"\|"gang", count: int 1–POLICE_MAX_UNITS (6), unit_type: "patrol"\|"swat"\|"gang", tactic: "chase"\|"roadblock"\|"surround", near_poi_id: str\|null` | null = in Spielernähe, 120–200 m entfernt |
| `radio_message` | `id: str, speaker: str, text: str ≤RADIO_MAX_CHARS (160), voice: str, tts_key: str (16 hex)` | nur über `protocol.make_radio_message()` bauen; Audio unter `GET /tts/{tts_key}.wav` |
| `quest_update` | `quest_id, status: "active"\|"target_reached"\|"completed", title ≤80, objective ≤200, poi_id, target: {x, z, radius}, spawn_targets: int 0–5, remaining: int 0–5` | bei `target_reached` spawnt der Client `spawn_targets` Gegner |
| `agent_log` | Logzeile ohne `prompt` und `config` (siehe JSONL-Log) | fürs Overlay |
| `error` | `code: "invalid_message"\|"unknown_type"\|"rate_limited", message: str` | Debug-Hilfe |

### Beispiele (je eine Datei in `contract/examples/`)
```json
{"type": "player_position", "ts": 1763125392123, "payload": {"x": -30.5, "z": 480.0, "heading": 3.14, "speed": 1.4, "in_vehicle": false, "zone_id": null}}
{"type": "shot_fired", "ts": 1763125392123, "payload": {"x": -33.0, "z": 500.2, "shots": 6, "weapon": "pistol", "zone_id": "marktplatz"}}
{"type": "npc_killed", "ts": 1763125392123, "payload": {"npc_id": "ped-12", "npc_kind": "civilian", "x": -36.1, "z": 509.8, "zone_id": "marktplatz", "quest_id": null}}
{"type": "vehicle_stolen", "ts": 1763125392123, "payload": {"vehicle_id": "car-3", "vehicle_kind": "civilian", "x": 20.4, "z": 470.0, "zone_id": null}}
{"type": "zone_entered", "ts": 1763125392123, "payload": {"zone_id": "marktplatz", "previous_zone_id": null}}
{"type": "set_wanted_level", "ts": 1763125398123, "payload": {"level": 2, "source": "agent", "reason": "Civilian killed at Market Square"}}
{"type": "spawn_units", "ts": 1763125398123, "payload": {"wave_id": "w-3", "faction": "police", "count": 2, "unit_type": "patrol", "tactic": "roadblock", "near_poi_id": "marktplatz"}}
{"type": "radio_message", "ts": 1763125398123, "payload": {"id": "r-7", "speaker": "Dispatch", "text": "Dispatch to all units: shots fired at Market Square, suspect on foot. Two patrols, block Kaiserstrasse.", "voice": "Orus", "tts_key": "1ad3fd64a39b91dd"}}
{"type": "quest_update", "ts": 1763125332123, "payload": {"quest_id": "q-1", "status": "active", "title": "Pyramid Trouble", "objective": "Go to Market Square and deal with 3 thugs", "poi_id": "marktplatz", "target": {"x": -35.2, "z": 506.9, "radius": 35}, "spawn_targets": 0, "remaining": 3}}
{"type": "error", "ts": 1763125392123, "payload": {"code": "invalid_message", "message": "payload.shots: Input should be less than or equal to 50"}}
```
`agent_log`: siehe `contract/examples/agent_log.json` (Payload = JSONL-Zeile ohne `prompt`/`config`).

### HTTP `POST /npc/talk`
Request (`NpcTalkRequest`, tolerant): `npc_id: str, player_text: str ≤200 (Default "", dann grüßt der NPC), x, z: float|null`.
```json
{"npc_id": "fixer_karl", "player_text": "Got any work?", "x": -12.0, "z": 150.5}
```
Response 200 (`NpcTalkResponse`), auch im Fallback, nie 5xx durch Gemini: `npc_id, text ≤600, quest: QuestUpdate|null, sources: [{title, uri}], model: str|null, fallback: bool`.
```json
{"npc_id": "fixer_karl", "text": "You want work? Three of Viper's thugs are hanging around the Pyramid on Market Square. Make them leave. Permanently.",
 "quest": {"quest_id": "q-1", "status": "active", "title": "Pyramid Trouble", "objective": "Go to Market Square and deal with 3 thugs",
           "poi_id": "marktplatz", "target": {"x": -35.2, "z": 506.9, "radius": 35}, "spawn_targets": 0, "remaining": 3},
 "sources": [{"title": "Marktplatz Karlsruhe", "uri": "https://maps.google.com/?cid=1234567890"}],
 "model": "gemini-3.5-flash-lite", "fallback": false}
```
- `quest` ist null, wenn nur geredet wurde. Eine neue Quest kommt zusätzlich als `quest_update` per WS.
- `sources` (Maps Grounding) muss das UI direkt unter dem Text zeigen: "Google Maps" unverändert, mit `translate="no"`, Titel als Link auf `uri`.
- 404 bei unbekannter `npc_id`, 422 bei ungültigem Body.

### Snapshot für Agenten (`protocol.AgentSnapshot`)
Geht als kompaktes JSON (`to_prompt()`, ohne None-Felder, Ziel unter 2 KB) als User-Content an den Agenten. Beispiel: `contract/examples/snapshot_police.json`.
- `agent: str, t: ISO-UTC, player: {x, z, zone_id, in_vehicle, speed}|null`
- `wanted_level: int, units_active: int, units_max: int`
- `recent_events: [{type, s_ago, zone_id, detail}]` (höchstens 12), `counts_60s: {type: int}`
- `memory: [str]` (höchstens 5 Zeilen, vom Agentenmodul gepflegt)
- `places: [{id, name}]` (POIs)
- `extras: {name: any}` aus `hub.register_snapshot_provider(name, fn)`: `quests.py` liefert `quest`, `game_state.py` liefert `wanted`.
- Mengen rechnet der Server, nicht das Modell (Messung 2026-11-14: das Modell zog aktive Einheiten in 3 von 5 Calls nicht ab). Tools fragen deshalb Sollwerte ab (z. B. Soll-Einheiten), der Server rechnet die Differenz und clampt.

### JSONL-Log `logs/genai.jsonl` (`protocol.GenaiLogLine`)
Eine Zeile pro GenAI-Request (pro tatsächlichem HTTP-Versuch) und pro Fallback-Entscheidung. Beispiel: `contract/examples/genai_log_line.json`.
- `ts` (ISO-UTC mit ms), `call_no` (Zähler pro Prozess), `kind: "genai"|"fallback"`, `agent`, `model` (null bei Fallback)
- `status: "ok"|"error"`, `error: {code: int|str, message}|null`, `latency_ms`
- `prompt` (gekürzt auf `GENAI_LOG_MAX_PROMPT_CHARS`), `config: {tools, tool_mode, thinking_level, system_instruction_chars, response_modalities}`
- `output: {text, calls: [{tool, args}], inline: [{mime, bytes}], sources: [{title, uri}]}`
- `reason`: aus `args.reason` des ersten Calls (jedes Spiel-Tool hat ein Pflichtfeld `reason`, ein Satz)
- Inline-Daten nur als Platzhalter `{mime, bytes}`. Nie im Log: Key, Header, Auth.
- Das Overlay bekommt jede Zeile als `agent_log` (ohne `prompt` und `config`).

### POI-Datei `data/pois.json` (`protocol.PoiFile`)
`{version: 1, origin: {lat, lon}, pois: [Poi]}`; `Poi`:
- `id` (Slug `[a-z0-9_]`), `name` (EN), `category`, `lat`, `lon`, `x`, `z` (aus `geo.to_local`), `radius` (m)
- `osm_ref` (`way/316433983`), `tags` aus `mission`, `gang_turf`, `npc_spot`, `crowded`, `description` (EN, ≤300)
- Quest-Ziele kommen nur von hier (`poi_id` muss existieren). Zonen überlappen nicht (Test).
- Aktueller Stand: 9 POIs (Schloss, Schlossplatz, Marktplatz, Stadtkirche, Bundesverfassungsgericht, Botanischer Garten, Kunsthalle, Kronenplatz, Friedrichsplatz), Koordinaten aus OSM (Overpass, 2026-11-14).

### Registrierungspunkte
Ziel: Feature-Scheiben berühren `main.py` und `frontend/src/main.js` nicht.
- **Backend-Feature-Modul** exportiert `register(hub) -> None` und optional `router` (APIRouter), `async startup()`, `async shutdown()`.
  - `main.py` geht `FEATURE_MODULES` durch (`game_state`, `quests`, `runner`, `maps_facts`, `tts`, `agents.police`, `agents.quest`): importieren, falls vorhanden, `register(HUB)`, `include_router`, Lifespan-Hooks. Fehlt ein Modul, wird es übersprungen. Jeder andere Importfehler bricht den Start ab.
  - Die Reihenfolge ist die Handler-Reihenfolge: erst Zustand, dann Agenten. Kein Code mit Seiteneffekten beim Import.
- **Hub** (`hub.py`):
  - `on_event(type | "*", fn)`, `await publish_event(env)` (nur ws.py)
  - `await send_action(type, payload)`, `send_action_threadsafe(type, payload)` (aus Threads)
  - `on_action(type, fn)`: Beobachter ausgehender Aktionen (z. B. TTS)
  - `on_connect(fn) -> list[Envelope]`: Zustand für neue Clients
  - `register_snapshot_provider(name, fn)`, `snapshot_extras()`
  - Handler müssen schnell sein: kein LLM-Call im Handler, höchstens einen Task starten.
- **Agent-Runner** (`runner.py`): `register_agent(AgentSpec(name, triggers, min_interval_s, decide, fallback, clamp))`.
  - Ablauf: Trigger-Event öffnet ein Sammelfenster von `AGENT_DEBOUNCE_S` (≥5 s) → Mindestabstand `min_interval_s` → höchstens ein Call pro Agent → `decide(snapshot)` mit Deadline `AGENT_DEADLINE_MS` → bei Timeout, Fehler, `offline` oder Budget: `fallback(snapshot)` → `clamp` → `send_action`. Verspätete Ergebnisse werden verworfen.
- **Frontend-Feature-Modul**: `frontend/src/features/<name>.js` exportiert `init(ctx)`. `main.js` lädt alle per `import.meta.glob('./features/*.js', {eager: true})`.
- **`ctx`** (JSDoc: `frontend/src/types.js`, gebaut von `frontend/src/core/`): `three, scene, camera, renderer, rapier, physics, net {on, send, sendThrottled, onStatus}, onUpdate(fn(dt, t)), input {isDown, onKey}, player {position, heading, inVehicle, object3d}, world {pois, zoneAt, randomRoadPoint}, combat {addTarget, removeTarget}, models {car, person}, hud {setWanted, toast, setObjective, subtitle, showDialog, hideDialog, addPanel}, start()`.
  - `combat.addTarget(obj, {id, kind, questId?, hp, onKilled})`: core macht Raycast und HP, sendet `npc_killed` und ruft `onKilled`.
- **Debug**: `POST /debug/action` (nur mit `DEBUG_ENDPOINTS=1`) nimmt eine Server-Envelope (z. B. eine Datei aus `contract/examples/`) und broadcastet sie.

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

### Vertrag und Kern (Schritt 0)
- Zweck: gemeinsame Schnittstellen und Infrastruktur, auf denen alle Scheiben aufbauen.
- Use-Cases: Nachrichten validieren, Koordinaten projizieren, POIs laden, Features registrieren.
- Dateien:
  - 0a: `protocol.py`, `geo.py`, `data/pois.json`, `contract/examples/`, Frontend-Skelett (`frontend/package.json`, `vite.config.js`, `index.html`, `src/main.js`, `src/net.js`, `src/types.js`, Platzhalter `src/core/index.js`), Tests `tests/test_protocol.py`, `tests/test_geo.py`
  - 0b: `gemini.py` (generate/agenerate, Budget, Deadline, Fallback-Modell abschaltbar), `genai_log.py` (JSONL + Listener), `hub.py` (Bus, `HUB`), `ws.py` (`/ws`, `/debug/action`), `agents/__init__.py`, in `main.py`: `FEATURE_MODULES`, `load_features`, `lifespan`, `mount_static` (`/play/`). Tests `tests/test_gemini.py`, `test_genai_log.py`, `test_hub.py`, `test_ws.py`, `test_main_loader.py`, `test_scripts_ascii.py`
- Schnittstellen: siehe "Vertrag". Zusätzlich zeigt `GET /` jetzt `agents_mode` und `genai_calls` (Budget-Zähler).
- Ablauf einer Agenten-Aktion: Feature ruft `await HUB.send_action(type, payload)` → `protocol.make_action` validiert → `on_action`-Beobachter → alle WebSocket-Clients. Aus Threads: `HUB.send_action_threadsafe(...)`. Jeder GenAI-Call landet über `genai_log` → `HUB` als `agent_log` im Browser.
- Agent und Modell: Schlüssel im Block "Kern" und "Modelle je Agent" in `config.py`.
- Offene Punkte:
  - Overpass: von dieser Maschine nur der Mirror `maps.mail.ru` erreichbar (overpass-api.de und kumi.systems: keine Verbindung, 2026-11-14).
  - `static/` ist bis Phase 4 gitignored. Ohne Build zeigt `/play/` 404; der Loader loggt das.

### Frontend-Kern (Scheibe Welt)
- Zweck: baut `ctx` (Vertrag, `frontend/src/types.js`) und die Spielschleife. Bühne, Spieler, Ballern und alle Client-Events.
- Use-Cases:
  - Spieler läuft (WASD, Shift sprintet) mit Third-Person-Kamera (Maus-Orbit im Pointer-Lock, Kamera weicht Wänden aus) und kann nicht durch Gebäude gehen.
  - Linksklick schießt (1 = Pistole, 2 = SMG mit Dauerfeuer). Gebäude blockieren Schüsse.
  - Fußgänger laufen auf Straßen, fliehen bei Schüssen und sind Ziele (`civilian`, hp 1).
  - Minimap unten links (`minimap.js`): nach Norden ausgerichtet, zeigt Spieler (rot, im Auto blau), POIs und Quest-Ziel (gelber Ring, außerhalb ein Pfeil am Rand). Ab 1 Stern blinkt der Rand rot/blau. Das Quest-Ziel kommt aus `quest_update` (nur lesend über `ctx.net`). Die Grundkarte wird einmal offscreen gezeichnet, neu gezeichnet wird mit 15 Hz. **M** blendet sie aus.
  - Auto klauen und fahren: F steigt in ein geparktes Auto (≤ 4 m) ein und aus. W/S Gas, Bremse, rückwärts, A/D lenken, Leertaste Handbremse, R aufrichten (automatisch nach 2 s auf dem Dach). Ab 4 m/s überfährt das Auto Fußgänger (`npc_killed`).
  - Feature-Scheiben docken über `init(ctx)` an (Polizei, Quest, Overlay).
- Dateien (`frontend/src/core/`):
  - `index.js`: baut `ctx`, Reihenfolge pro Frame: Physik (fester Schritt) → Spieler/Kamera → Kampf/Events → Fußgänger → `ctx.onUpdate` → Rendern
  - `renderer.js` (Szene, Licht, Nebel), `physics.js` (Rapier, 1/60 s, `fixed(fn)` vor jedem Schritt), `input.js`, `player.js`, `combat.js`, `models.js`, `hud.js`, `attribution.js`, `world.js`, `city.js`, `pedestrians.js`, `minimap.js`, `vehicle.js` (Rapier `DynamicRayCastVehicleController`, 8 geparkte Zivilautos, Verfolgerkamera)
- Schnittstellen:
  - Empfängt `set_wanted_level` und zeigt die Sterne im HUD (`police.js` darf zusätzlich reagieren, `setWanted` ist idempotent). `error` vom Server landet als Warnung in der Konsole.
  - Sendet alle 5 Events: `player_position` (gedrosselt 2 Hz), `shot_fired` (pro 500 ms gebündelt), `npc_killed` (nur combat), `zone_entered` (`previous_zone_id` = letzte Zone, in der der Spieler war, sonst null), `vehicle_stolen` (beim ersten Einsteigen pro Auto, `vehicle_kind` `civilian`).
  - `heading`: Rotation um y; Blickrichtung (−sin h, −cos h) in (x, z), also h = 0 → Norden. Modelle schauen nach −z.
  - Zusätze zu `ctx` (additiv, Stand W2):
    - `ctx.combat.onShot(fn({x, z, weapon})) -> off`: lokaler Beobachter für jeden Schuss (z. B. Gegner reagieren lassen).
    - `ctx.world.poi(id)`, `ctx.world.roadPoints` (Punkte alle 10 m auf befahrbaren Straßen und Fußgängerzonen, mit `heading`), `ctx.world.bounds`.
    - `ctx.world.randomRoadPoint()` liefert zusätzlich `heading` (Straßenrichtung).
    - `ctx.hud.wanted()`, `setConnected(ok)`, `setWeapon(name)`, `hitMarker()`, `setStartVisible(v)`.
    - `models.car()` setzt `userData.lightbar` = [rot, blau] (Polizei) und `userData.wheels`; `models.person()` setzt `userData.legs`/`arms`. `animateWalk(obj, speed, dt)` ist aus `core/models.js` importierbar.
  - `ctx._core` (Spieler, Physik, Kampf) ist intern und kein Vertrag. Im Vite-Dev-Server hängt `ctx` an `window.__ctx` (Konsole, Smoke-Tests).
  - Debug: `/play/?view=top` zeigt die Stadt von oben.
- Agent und Modell: keine (0 Gemini-Requests).
- Offene Punkte:
  - Fahrzeuge: Vorzeichen per Probe ermittelt. `currentVehicleSpeed() < 0` heißt vorwärts (−z), positive Lenkung dreht nach links. Vorwärtsachse ist z (`setIndexForwardAxis = 2`). Polizeiautos der Feature-Scheibe sind davon unabhängig (kinematisch).
  - Der Spieler schwebt 6 cm über dem Boden und wird nur horizontal kollidiert. Mit Schwerkraft sank die Kapsel in den Boden-Collider und blieb hängen. Die Stadt ist flach, also gibt es keine Stufen.
  - Bundle ca. 5 MB (Rapier-WASM inline). Lokal unkritisch, für Codesphere prüfen.

### OSM-Stadt (Scheibe Welt)
- Zweck: echtes Karlsruhe rund ums Schloss als Low-Poly-Stadt, vorgebacken, ohne OSM-Abfragen zur Laufzeit.
- Use-Cases:
  - Einmal holen: `python scripts/bake_osm.py --fetch` (Overpass-Mirror, bei Fehler OSM-API 0.6 in 2 × 2 Kacheln, `--source overpass|osmapi|auto`). Ergebnis `data/osm/raw.json` (eingecheckt, ca. 1,5 MB).
  - Backen (offline, Default): `python scripts/bake_osm.py` → `frontend/public/city/{buildings,roads,areas}.json`. Der Bake ist deterministisch (byte-gleich, Test).
- Dateien: `scripts/bake_osm.py`, `data/osm/raw.json`, `frontend/public/city/*.json`, `frontend/src/core/city.js`, `tests/test_bake_osm.py`
- Formate (Weltkoordinaten über `geo.py`, Meter, gerundet auf 0,1 m):
  - `buildings.json`: `[{id, h, pts}]`. `id` ist die OSM-Referenz (`way/123`, Teile von Multipolygonen `way/123#1`). Höhe aus `height`, sonst `building:levels` × 3,2 m, sonst 12 m (geclampt 2,5–120 m). Ring offen, im Uhrzeigersinn von oben (Shoelace in (x, z) > 0), Douglas-Peucker 0,5 m.
  - `roads.json`: `[{id, kind, w, pts}]`, `kind` = OSM-`highway`, `w` aus `width` oder Tabelle. Ohne Gehsteige, Querungen, Indoor-Korridore und Baustellen.
  - `areas.json`: `[{id, kind, pts}]`, `kind` aus park, garden, grass, parking, plaza.
  - Budget: buildings ≤ 1,5 MB, roads ≤ 0,5 MB, areas ≤ 0,5 MB, raw ≤ 8 MB, sonst Abbruch. Stand 2026-11-14: 959 Gebäude (136 KB), 1546 Straßen (156 KB), 236 Flächen (54 KB).
- Darstellung (`city.js`): Gebäude, Straßen und Flächen je ein Mesh mit Vertex-Farben (4 Draw-Calls mit Boden). Gebäude der POIs (`osm_ref`) bekommen Landmark-Farben. Collider: ein statisches Trimesh aus allen Wänden, Boden-Quader und vier Randwände.
- Schnittstellen: keine Nachrichten. Liest `data/pois.json` (nur lesend).
- Lizenz: © OpenStreetMap contributors (ODbL). Der Hinweis mit Link auf openstreetmap.org/copyright ist unten rechts immer sichtbar (`attribution.js`).
- Offene Punkte:
  - Overpass am 2026-11-14 ab 13:30 nicht nutzbar (mail.ru 504, osm.ch Laufzeitfehler, overpass-api.de und kumi.systems keine Verbindung). `raw.json` stammt deshalb aus der OSM-API 0.6.
  - Überlappende Grünflächen zeigen aus großer Höhe Z-Fighting. In Spielerhöhe ist das unauffällig.

### Look-Pass (Scheibe Welt)
- Zweck: Die Low-Poly-Stadt soll im Demo-Video gut aussehen, ohne core/ umzubauen. Ein eigenes Modul `frontend/src/look/`, das `core/index.js` einmal aufruft (`createLook`, dann pro Frame `update(dt)` und `render()`).
- Use-Cases:
  - HDRI-Himmel mit Wolken und bildbasiertem Licht. Die Sonnenrichtung (hellster Texel, mindestens 28° hoch) und die Nebelfarbe (Horizont-Mittel) kommen aus dem HDRI, damit Himmel, Schatten und Nebel zusammenpassen.
  - Sonne mit Schatten (PCF, 2048², ±90 m), der Bereich folgt dem Spieler auf einem 2-m-Raster gegen Flimmern. ACES-Tonemapping, Belichtung 0,62, Nebel `FogExp2`.
  - Prozedurale Fassaden (`look/facade.js`): Fenster- und Geschossraster per Shader aus Weltkoordinaten (3,2 m Geschoss, 3 m Achse), Schaufenster im Erdgeschoss. Glatte Scheiben spiegeln das HDRI.
  - Post-FX (`look/post.js`): MSAA-Render-Target, GTAO (Umgebungsverdeckung), Bloom (nur HDR-Helles, z. B. Mündungsfeuer ×8), Output-Pass.
  - Tasten: **P** schaltet alle Post-FX, **O** nur die AO. Der Browser merkt sich P (localStorage, robust gegen Fehler). `?fx=0` startet ohne Post-FX.
  - Qualitätsstufen (`look/quality.js`, für das Demo-Laptop mit Intel HD 620): high (Pixel-Ratio ≤ 1,5, Schatten 2048, AO, Bloom), medium (≤ 1,0, Schatten 1024, Bloom), low (≤ 1,0, Schatten 1024, ohne Post-FX), lowest (0,75, ohne Schatten und Post-FX). Intel-GPUs starten auf medium, Software-Renderer auf lowest, sonst high. Liegt ein 2-s-Fenster unter 30 fps, geht es eine Stufe runter, mit Toast. Automatisch geht es nie hoch, sonst pendelt es. 5 s Schonfrist nach Start und Wechsel. **Q** schaltet reihum, `?q=high|medium|low|lowest` erzwingt die Startstufe.
- Dateien: `frontend/src/look/{index,env,post,facade,quality}.js`, `frontend/public/look/kloofendal_48d_partly_cloudy_puresky_1k.hdr` (1,4 MB)
- Schnittstellen: keine Nachrichten. Alle `MeshLambertMaterial`s in der Szene werden zu `MeshStandardMaterial` mit denselben `color`-/`emissive`-Objekten, auch die später von Features hinzugefügten (Scan alle 0,5 s). Features können also weiter Lambert verwenden, Farbänderungen (Blaulicht) wirken weiter. Meshes werfen und empfangen Schatten, die Stadtflächen empfangen nur. `MeshBasicMaterial` bleibt unverändert.
- Debug: `?start=0` blendet das Start-Overlay aus (Screenshots, Video).
- Lizenz: HDRI „Kloofendal 48d Partly Cloudy (Pure Sky)“ von Poly Haven, CC0 (polyhaven.com). Ins README (Phase 4) aufnehmen.
- Offene Punkte:
  - Die Bildrate auf dem Demo-Laptop (HD 620) ist noch nicht gemessen, headless gibt es nur Software-Rendering. Headless belegt: Die Stufen fallen bei niedriger Bildrate high → medium → low → lowest (je ca. 9 s). Fürs Video die Stufe mit `?q=` festlegen.
  - `PCFSoftShadowMap` gibt es in three r187 nicht mehr, deshalb PCF mit `shadow.radius`.

### Spielzustand (Scheibe Polizei)
- Zweck: Wahrheit über Fahndung, Einheiten, Spielerposition und jüngste Events. Baut die Agent-Snapshots.
- Use-Cases:
  - Regel-Boden: `shot_fired`, `npc_killed` (außer `gang`/`quest_target`) und `vehicle_stolen` heben Level 0 sofort auf 1 (`source: "rules"`) und setzen `last_crime`.
  - Decay: Nach `WANTED_DECAY_S` ohne Verbrechen (und seit dem letzten Decay) sinkt das Level um 1 (Task, Tick 1 s).
  - Einheitenbilanz: Summe aus `spawn_units` (police) minus getötete `police`, gedeckelt auf `POLICE_MAX_UNITS`, bei Level 0 gleich 0.
  - Reload: `on_connect` schickt das aktuelle `set_wanted_level` (`reason: "State sync"`).
- Dateien: `game_state.py`, `tests/test_game_state.py`
- Schnittstellen:
  - Das Level ändert sich nur über ausgehende `set_wanted_level`-Aktionen (`on_action`), egal ob Regeln, Agent oder Fallback. Eine Quelle der Wahrheit.
  - Ringpuffer: letzte 50 Events bzw. 120 s; `player_position` wird nur als Zustand gemerkt, nicht gepuffert.
  - `snapshot(agent, memory)` → `AgentSnapshot` (12 Events, 5 Gedächtniszeilen, alle POIs als `places`, `extras` vom Hub). Test: unter 2 KB.
  - Snapshot-Provider `wanted`: `{level, floor, crime_s_ago}`. `floor` ist 1, solange das letzte Verbrechen unter `WANTED_DECAY_S` her ist.
  - `GET /debug/state` (nur `DEBUG_ENDPOINTS=1`).
- Agent und Modell: keine (0 Requests).

### Agent-Runner (Scheibe Polizei)
- Zweck: entscheidet, wann ein Spiel-Agent läuft, und sorgt dafür, dass das Spiel nie auf ihn wartet.
- Use-Cases: `agents/police.py` meldet sich mit `register_agent(AgentSpec(...))` an.
- Dateien: `runner.py`, `tests/test_runner.py`
- Ablauf: Trigger-Event (optional `trigger_filter`) öffnet ein Sammelfenster `AGENT_DEBOUNCE_S` → Mindestabstand `min_interval_s` seit dem letzten Zyklusstart → Lock (ein Call pro Agent) → `decide` mit `wait_for(AGENT_DEADLINE_MS)` → `clamp` → `send_action` → `on_sent` (Gedächtnis).
  - Fallback bei `AGENTS_MODE=offline` (ohne Request), Timeout, `HTTPException` (429, 5xx, Budget) oder jeder anderen Exception, und wenn nach dem Clamp vom Modell nichts übrig bleibt.
  - Jeder Fallback wird mit `genai_log.log_fallback` geloggt (`reason: "fallback (<grund>): ..."`) und erscheint so im Overlay.
  - Generationszähler: `set_wanted_level` 0 mit `source: "rules"` verwirft laufende Entscheidungen.
  - `AgentSpec` hat zusätzlich zum Vertrag `snapshot`, `trigger_filter` und `on_sent` (additiv).
- Agent und Modell: keine eigenen; Schlüssel `AGENT_DEBOUNCE_S`, `AGENT_DEADLINE_MS`, `AGENTS_MODE`.

### Polizei-Dispatcher (Scheibe Polizei)
- Zweck: Gemini-Agent, der Fahndungsstufe, Einheiten, Taktik und Funk festlegt. Clientseitig fährt `police.js` die Autos.
- Use-Cases: Schießerei → Agent eskaliert, schickt Einheiten an echte Orte, funkt. Ohne Gemini greift ein deterministischer Fallback.
- Dateien: `agents/police.py`, `frontend/src/features/police.js`, `tests/test_police.py`
- Agent: ein Request pro Zyklus, `gemini.agenerate(..., agent="police", attempts=AGENT_ATTEMPTS, timeout_ms=AGENT_DEADLINE_MS, use_fallback_model=False)`, Function Calling `ANY`, `thinking_level` = `GEMINI_THINKING_LEVEL`. Kein Verlauf: das Gedächtnis (5 Zeilen) steht im Snapshot.
  - Tools (alle mit Pflichtfeld `reason`): `set_wanted_level(level)`, `spawn_units(target_units, unit_type patrol|swat, tactic, near_place_id?)`, `radio_message(text)`.
  - Trigger: `shot_fired`, `npc_killed`, `vehicle_stolen`, `zone_entered` nur ab Level 1. Mindestabstand `POLICE_MIN_INTERVAL_S`.
- Clamps: pro Tool nur der erste Call, unbekannte Tools weg; Level in [Boden, `WANTED_MAX`] und höchstens ±`WANTED_MAX_STEP`, unverändert → weg; `count = min(target_units, POLICE_MAX_UNITS) − units_active`, ≤ 0 → weg, bei Level 0 keine Einheiten; ungültige Enums → `patrol`/`chase`; unbekannter Ort → `null`; Funk auf `RADIO_MAX_CHARS`, leer → weg.
- Fallback: Level = max(aktuell, min(5, Boden + Tote der letzten 60 s)), Einheiten bis Level (ab 4 SWAT; Taktik chase ≤ 2, roadblock 3, surround ≥ 4), Funk aus 5 englischen Vorlagen mit dem Zonennamen. Deeskalation macht nur der Decay.
- Client (`police.js`): `set_wanted_level` → `hud.setWanted`, bei 0 alle Autos weg. `spawn_units` → `count` Polizeiautos (höchstens 8 gleichzeitig) 120–200 m vom Spieler oder 10–80 m um `near_poi_id`, Toast. Blaulicht blinkt (`userData.lightbar`). Bewegung per Rapier-Kinematic-Character-Controller (ohne Schwerkraft). Taktiken: chase (auf den Spieler, Halt bei 7 m), roadblock (Straßenpunkt 60 m vor dem Spieler, quer stehen; ist der Spieler 140 m weg, wird daraus chase), surround (4 Punkte im Abstand 12 m). Tempo 9 + 3·Level m/s. Festgefahren (3 s) oder weiter als 420 m → neu auf eine Straße nahe am Spieler. Ziel `police`, hp 3, Wrack 8 s. `faction: "gang"` wird ignoriert.
- Live-Check (2026-11-14, 4 Requests): `AGENT_DEADLINE_MS=6000` ergab 400 „Minimum allowed deadline is 10s“ (die Deadline geht als Server-Timeout mit). Default deshalb 10 000. Danach 3 Szenen mit 1,2–4,3 s Latenz und passenden Calls: Marktplatz-Schießerei → Level 2; 3 tote Zivilisten → Level 3, 2 Streifen am Schlossplatz; Polizist tot und Streifenwagen gestohlen → Level 4, 3 SWAT am Kronenplatz, Funk „officer down“. Der Gemini-Client wird im Live-Modus beim Start vorgewärmt (`startup`, kalt ca. 3 s, kein Request).
- Offene Punkte:
  - Polizisten schießen nicht zurück und verhaften nicht; Autos fahren direkt aufs Ziel zu (kein Straßen-Routing), Gebäude umfahren sie nur per Slide.
  - Im Live-Check lag beim ersten Zyklus 25–33 s zwischen Zyklusstart und HTTP-Start (Ursache offen, der Fallback griff nach der Deadline). Kandidat: `hub.broadcast` an einen gerade geschlossenen Socket hält den Zyklus-Lock.

### Gang-Boss (gestrichen)
- Am 2026-11-14 gestrichen (erste Kürzung laut Plan). Es gibt kein `agents/gang.py`.
- Im Vertrag bleiben `faction: "gang"`, `unit_type: "gang"`, `npc_kind: "gang"` und der POI-Tag `gang_turf` stehen (nur additiv ändern). Quest-Gegner sind `quest_target`.

### Quest-NPC (Scheibe Quest)
- Zweck: Ein NPC vergibt per Gemini-Function-Calling eine Quest zu einem echten Ort. Ob das Ziel erreicht und die Quest erfüllt ist, entscheidet nur der Server per Position und Kills.
- Use-Cases:
  - Spieler steht unter 3 m beim NPC, drückt E → `POST /npc/talk`, Dialog mit Warteanzeige, das Spiel läuft weiter
  - Neue Quest → `quest_update` (`active`) per WS: Objective, Lichtsäule am Ziel, Pfeil über dem Spieler
  - `player_position` im POI-Radius → `target_reached` mit `spawn_targets = remaining = n`, der Client spawnt n Gegner (`quest_target`), sie laufen auf den Spieler zu und zeigen Mündungsfeuer ohne Schaden
  - `npc_killed` mit passender `quest_id` → `remaining` sinkt (`spawn_targets` 0), bei 0 `completed` → Toast „Mission complete“
  - Reload: `on_connect` schickt die aktive Quest, bei `target_reached` mit `spawn_targets = remaining`
  - Gemini offline, Budget leer, Fehler, Deadline oder kein brauchbares Ergebnis → Fallback-Quest (zufälliger `mission`-POI außerhalb der aktuellen Zone), HTTP 200 mit `fallback: true`, Logzeile `kind: "fallback"`
  - Läuft schon eine Quest, erinnert der NPC daran (keine zweite Quest)
- Dateien: `quests.py` (QuestBook, Handler, Snapshot-Provider `quest`, `fallback_quest`), `agents/quest.py` (Router, Tool-Loop, Fallback), `data/npcs.json` (Karl the Fixer am Schlossplatz, nahe Spawn), `frontend/src/features/npc.js`, `frontend/src/features/quest.js`, Tests `tests/test_quests.py`, `tests/test_quest_agent.py`
- Schnittstellen: `POST /npc/talk` (Vertrag), Aktion `quest_update`, Events `player_position` und `npc_killed`, Snapshot-Extra `quest = {title, poi_id, status}`
- Agent und Modell: `GEMINI_MODEL_QUEST`, Tools `lookup_place(place_id, reason)` und `assign_quest(place_id, title, objective, enemies, npc_line, reason)`; `place_id` ist ein Enum der `mission`-POIs, falsche IDs kommen als `{"error": ...}` zurück und das Modell wählt neu. `assign_quest` beendet den Loop (typisch 2 Requests, höchstens `QUEST_MAX_STEPS`). Pro Request `AGENT_DEADLINE_MS`, gesamt `QUEST_DEADLINE_MS` (`asyncio.wait_for`), `use_fallback_model=False`. Gedächtnis: letzte 6 Sätze pro NPC (im Prozess).
- Offene Punkte:
  - Spieler kann noch keinen freien Text eingeben (erstes Gespräch „Got any work for me?“, danach leer).
  - Live-Lauf steht aus. Der Q0-429 betraf nur `google_maps` (auf dem Projekt gesperrt), normale Calls laufen (`agent_docs/gemini_api.md`).

### Maps-Fakten (Scheibe Quest)
- **Gestrichen** (2026-11-14, Kürzung 2). Der Q0-Live-Check (1 Request, `gemini-3.5-flash-lite` mit `google_maps`) lieferte 429 „quota exceeded“; 429 wird nie wiederholt. Ursache: Maps Grounding ist auf dem Projekt gesperrt (nur das Tool `google_maps`, kein Spend-Cap).
- Stattdessen liefert `lookup_place` die `description` aus `data/pois.json`. `sources` in `/npc/talk` bleibt leer, die Quellenzeile im Dialog (`hud.showDialog`) ist vorbereitet und erscheint, sobald `sources` gefüllt ist.
- Kein `maps_facts.py`, kein `scripts/prewarm.py`; `MAPS_CACHE_PATH` und `GEMINI_MODEL_MAPS` bleiben in `config.py` (Vertrag nur additiv).

### Polizeifunk-TTS (Scheibe Quest)
- **Gemini-TTS gestrichen** (2026-11-14, Kürzung 1). Der Q0-Live-Check (1 Request, `gemini-3.8-flash-lite-tts`) lieferte 400 „Unknown name speechConfig at generation_config“.
- Zweck jetzt: Funksprüche des Dispatchers hörbar machen, ohne Server-Audio.
- Use-Cases: `radio_message` → sofort `hud.subtitle("Dispatch: …")`, dann `speechSynthesis` (en-US, etwas tiefer und schneller) mit kurzem Funkrauschen (WebAudio, Bandpass) davor und danach. Mehrere Funksprüche stellen sich in die Warteschlange des Browsers.
- Dateien: `frontend/src/features/radio.js`. Kein `tts.py`, kein `GET /tts/{key}.wav`; `tts_key` bleibt im Vertrag.
- Offene Punkte: Das Rauschen braucht eine Nutzergeste (Autoplay-Regel), vorher spricht nur die Stimme.

### Agent-Log-Overlay (Phase 4)
_noch leer_

### Starter-Endpoints `/chat` und `/agent`
- Zweck: Gemini-Setup (Key, Modelle, Retry und Fallback) ohne Spiel-Frontend prüfen und den Tool-Loop debuggen.
- Use-Cases:
  - Smoke-Test nach Key- oder Modellwechsel
  - sehen, ob der Fallback gegriffen hat (Feld `model`)
  - neue Tools im Loop ausprobieren
- Dateien:
  - `main.py`: `chat`, `agent`, Beispiel-Tools `get_time` und `calculator`
  - `gemini.py`: `generate` (Retry, Fallback, Budget, JSONL-Log)
  - `config.py`
  - Tests: `tests/test_api.py`, `tests/test_gemini_retry.py`
- Schnittstellen (HTTP, keine WebSocket-Nachrichten):
  - `GET /`: `{status, models: {agent, chat, fallback}, gemini_key_configured, agents_mode, genai_calls}`. Ruft Gemini nie auf.
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
  - Die Latenz ist kein Engpass, das Request-Budget bestimmt den Takt: Sammelfenster `AGENT_DEBOUNCE_S` mindestens 5 s, Mindestabstand `POLICE_MIN_INTERVAL_S` 8 s, also höchstens 7,5 Requests pro Minute und Agent.
  - `AGENT_DEADLINE_MS` 6 s reicht dem Agent-Modell. Das Fallback-Modell (5 bis 12,5 s) rufen Spiel-Agenten nicht auf (`use_fallback_model=False`), stattdessen greift sofort der geskriptete Fallback.
  - Pro Agent höchstens ein Request gleichzeitig. Events, die währenddessen ankommen, fließen in den nächsten Snapshot.
  - Mengen (z. B. fehlende Einheiten) rechnet das Spiel und schickt sie im Snapshot mit oder begrenzt sie im Clamp. Das Modell lag dabei in 3 von 5 Calls daneben.
- Offene Punkte:
  - Hydrogen war beim Smoke-Test am 2026-11-14 sehr langsam (30 bis 90 s pro Schritt). Deshalb ist Flash-Lite Default. Hydrogen oder Carbon nur per Env und mit höherem Timeout.
  - Der Fallback mitten im Tool-Loop (3.5-flash-lite-Signatures an 3.1-flash-lite) ist nicht live getestet.
  - `gemini-3.1-flash-lite` lieferte in der Messung 2 von 6 Mal 503. Als Fallback reicht das, als Primärmodell nicht.
  - Mit Polizei-Function-Call braucht `gemini-3.1-flash-lite` 5 bis 12,5 s (1 von 5 Calls: 504). Spiel-Agenten nutzen es deshalb nicht, sondern den geskripteten Fallback.
  - Die Decisions API (`gemini-decision-1`) funktioniert mit dem Key. Für geschlossene Agent-Entscheidungen ist sie ein Kandidat, eingebaut ist sie noch nicht (`agent_docs/gemini_api.md`).
