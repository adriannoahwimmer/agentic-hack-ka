# Grand Theft Fächer (Fächerstadt Agents)

Video: [demo video (Google Photos album)](https://photos.app.goo.gl/Yyjkj5WYqiEQ7gaX6)

A browser open world around Karlsruhe Palace, built from real OpenStreetMap data: walk, drive, shoot, and get chased by the police. The twist: nothing is scripted. A Gemini police dispatcher and a Gemini quest giver make the decisions through function calling. The game never waits for them, because deterministic rules and scripted fallbacks keep it running when the model is slow or offline.

Built in one day at the {Tech: Europe} Agentic AI Hack Karlsruhe on 14 November 2026, co-hosted by Google DeepMind and Codesphere.

<!-- Videos: drag the MP4s into the GitHub README editor and paste the generated URLs here, one per line. -->

## Demo path
1. Walk up to **Karl the Fixer** on Palace Square and press **E**. The quest agent picks a real place from the map and gives you a mission against a rival gang or smuggling crew. The enemies are never real people, officials or institutions, and courts and authorities (e.g. the Federal Constitutional Court) are blocked as quest targets on the server.
2. Steal a car (**F**) and drive to the target. The marker and the minimap show the way.
3. When you arrive, the enemies show up ("Here they come!"). Shoot them.
4. The shots raise your wanted level immediately (rule-based floor). After the event window, the dispatcher agent decides how far to escalate: stars, number of units, tactic (chase, roadblock, surround) and a radio message.
5. Police cars with flashing red and blue light bars and wailing sirens spawn and chase you. Officers on foot jump out of cars near you and open fire; at 5 stars a tank joins the chase. The dispatcher's radio call is in German (Polizeifunk, with real Karlsruhe place names). It appears as a subtitle and is spoken by the browser with a German voice.
6. Talk back on the police radio: **G** pleads innocence, **T** taunts the cops. The dispatcher agent answers in German and may lower or raise your stars.
7. Kill the last target and you get **Mission complete**.

The **agent overlay** (top right, toggle with **L**) shows every agent decision live: tool calls, the reason, model and latency, scripted fallbacks and your own radio calls.

## Controls
| Key | Action |
|---|---|
| Click | Start (captures the mouse) |
| Mouse | Look around / camera |
| W A S D | Walk; in a car: throttle, brake/reverse, steer |
| Shift | Sprint |
| Left mouse button | Shoot (on foot) |
| 1 / 2 | Pistol / SMG |
| F | Enter or leave a car |
| Space | Handbrake |
| R | Put the car back on its wheels |
| E | Talk to an NPC |
| G | Police radio: plead ("Ich hab nichts gemacht!"), 8 s cooldown |
| T | Police radio: taunt ("Ihr kriegt mich nie!"), 8 s cooldown |
| L | Agent overlay on/off |
| M | Minimap on/off |
| Q | Cycle graphics quality |
| P | Post-processing on/off (remembered in the browser) |
| O | Ambient occlusion on/off |

### URL flags
| Flag | Effect |
|---|---|
| `?q=high` / `medium` / `low` / `lowest` | Fixed graphics tier. Without it the game picks one from the GPU and steps down by itself when the frame rate drops. |
| `?fx=0` | Start without post-processing |
| `?view=top` | Fixed top-down camera above the palace (intro and debug) |
| `?start=0` | Hide the "Click to play" screen |

Example: `http://localhost:3000/play/?q=medium&start=0`

## Setup
Requirements: Python 3.10+, Node.js with npm (developed with Node 24), and a Gemini API key.

```powershell
git clone https://github.com/adriannoahwimmer/agentic-hack-ka.git
cd agentic-hack-ka
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt   # runtime only: requirements.txt
copy .env.example .env                              # then set GEMINI_API_KEY
npm --prefix frontend install
npm --prefix frontend run build                     # builds the game into static/
.venv\Scripts\uvicorn main:app --port 3000
```
Open `http://localhost:3000/play/`. `GET /` is the health check.

- `.env.example` lists every setting with its default. All values live in `config.py` and can be overridden by environment variables.
- **`AGENTS_MODE=offline`** (default): no Gemini request at all; the agents use their scripted fallbacks. The full demo path works this way.
- **`AGENTS_MODE=live`**: the police dispatcher and the quest giver call Gemini.
- Hard request budget per server process: `GENAI_MAX_CALLS_PER_MIN` (30) and `GENAI_MAX_CALLS_TOTAL` (400). When it is used up, the fallbacks take over.
- Development: run the backend on port 3000 and `npm --prefix frontend run dev` (Vite on 5173, proxies `/ws`, `/npc`, `/tts` and `/debug` to the backend). Then open `http://localhost:5173/play/`.
- Checks: `scripts\check.ps1` (bash: `scripts/check.sh`) runs ruff, pytest and the frontend build. Tests never call Gemini.

## Architecture
```
Browser (Three.js + Rapier, Vite)              FastAPI :3000
 core/: city, player, car, shooting,  WS /ws    ws.py -> hub.py (event/action bus)
   HUD, minimap                     <======>      game_state.py   wanted level, rules, units
 features/: police, npc, quest,     envelope      runner.py       debounce, clamp, fallback
   radio                                            agents/police.py  Gemini dispatcher
                                    POST /npc/talk quests.py      quest check by position
                                    ----------->   agents/quest.py  Gemini quest giver
                                                  gemini.py: budget, deadlines, JSONL log
```
- **Contract first.** Every WebSocket message (`{type, ts, payload}`), `POST /npc/talk`, the agent snapshot and the log line are Pydantic models in `protocol.py`, with one example per message in `contract/examples/`. See `Design.md`, section "Vertrag".
- **The client** owns physics, hits and movement and sends events: `player_position`, `shot_fired`, `npc_killed`, `vehicle_stolen`, `zone_entered`.
- **The server** owns the truth: wanted level, units, quests. It sends actions: `set_wanted_level`, `spawn_units`, `radio_message`, `quest_update`, `agent_log`.
- **Police dispatcher.** Crime events open a collection window of at least 5 s, with at least 8 s between cycles. Each cycle sends a compact snapshot and exactly one Gemini request (function calling, mode `ANY`). The tools are `set_wanted_level`, `spawn_units` and `radio_message`. The server validates and clamps the result (wanted level 0–5, at most 6 units) before sending it to the browser.
- **Quest giver.** A short tool loop: `lookup_place`, then `assign_quest`. It may only choose places from `data/pois.json`. The server, not the model, decides when a quest is complete, from the player position and kill events.
- **Never wait for the model.** Game agents use a local 6 s deadline (Gemini itself gets at least 10 s, its minimum) and no slow fallback model. On timeout, error, budget exhaustion or offline mode, scripted fallbacks take over.
- **Model choice.** Heavier models were too slow for real-time gameplay; `gemini-3.5-flash-lite` was the fastest option that still makes reliable tool calls within our 6 s deadline. Heavier models can be set via `GEMINI_MODEL_AGENT`.
- **Logging.** Every Gemini request goes to `logs/genai.jsonl` as one JSON line: agent, model, tool calls, reason, latency, without keys. Each line is also sent to the browser as `agent_log` and appears in the developer console (verbose level). The in-game agent overlay (top right, **L**) shows the last five entries.
- **Map.** OSM data is baked once into compact JSON (`scripts/bake_osm.py`, 959 buildings, 1546 road segments, 230 areas) with a single projection (`geo.py`, origin at the palace). There are no map requests at runtime.

## Landmarks
Four hand-modelled low-poly landmarks (`frontend/src/landmarks/`) make the city recognisable. Each one finds its OSM footprint by `osm_ref` in the baked buildings and sits on it, aligned to the longest edge:
- **Karlsruhe Palace** (`way/316433983`): the octagonal palace tower at the centre of the fan of streets (about 51 m), a grey-blue mansard roof and the central gable facing Palace Square.
- **Pyramid** on the Market Square (`way/90034221`): the red sandstone tomb of the city's founder (about 6.8 m). It is the only landmark that hides its extruded OSM block (`ctx.world.hideBuilding`); the block's collider stays as the pyramid's collision.
- **Protestant City Church** (`way/90180591`): Weinbrenner's portico with six columns and a pediment facing the square, the nave roof and the white tower (about 62 m).
- **Town Hall** (`relation/1333212`): hipped roof, central projection with a gable towards the square, and the town hall tower.

All landmarks are a single mesh with vertex colours and one Lambert material (one extra draw call, no textures, no per-frame code) and add no colliders. A landmark whose footprint is missing is skipped with a console warning.

## Police polish
- **Light bars:** police cars flash red and blue (`ctx.models.setLightbar`).
- **Siren:** a wail generated with the Web Audio API, no audio file. A sawtooth oscillator sweeps between about 600 and 1300 Hz through a low-pass filter. It gets louder as the nearest police car comes closer and wails faster at higher wanted levels. It starts after the first click (browser autoplay rules).
- **German police radio:** the dispatcher prompt asks for one short German Polizeifunk call (at most 15 words) with the real German place name. The scripted fallback calls are German too. The browser speaks them with a German voice (`de-DE`), with a short burst of radio static before and after. The rest of the game is in English.

## APIs, models, frameworks and tools
**Google Gemini**
- Gemini API via the `google-genai` Python SDK (`models.generate_content`), using manual function calling, `thinking_level=low`, per-request deadlines and a fallback model for the debug endpoints.
- `gemini-3.5-flash-lite`: police dispatcher, quest giver, and the debug endpoints `/chat` and `/agent`.
- `gemini-3.1-flash-lite`: fallback model, only for `/chat` and `/agent`.

**Backend**
- Python, FastAPI, Uvicorn, Pydantic, python-dotenv, WebSockets.

**Frontend**
- Three.js 0.187, including EffectComposer, UnrealBloomPass, GTAOPass, OutputPass and HDRLoader from the examples.
- Rapier 3D (`@dimforge/rapier3d-compat` 0.21): physics, character controller, ray-cast vehicle controller.
- Vite 8.

**Browser APIs**
- WebGL, WebSocket, Pointer Lock, Web Speech API (`speechSynthesis`, radio voice), Web Audio API (radio static, police siren), localStorage.

**Data and assets**
- OpenStreetMap, © OpenStreetMap contributors, ODbL. The city geometry was fetched once from the OpenStreetMap API 0.6 (`map` call in 2 × 2 tiles, because no Overpass server answered that afternoon). The POI coordinates came from the Overpass API (mirror `maps.mail.ru`).
- HDRI "Kloofendal 48d Partly Cloudy (Pure Sky)" by Poly Haven, CC0.

**Development tools**
- ruff, pytest, httpx (test client), gitleaks (secret scan), GitHub CLI, and Claude Code (agentic development, up to five parallel sessions in git worktrees).

**Prepared, not deployed**
- Codesphere (`ci.yml`).

## Wanted rules and police units
The server enforces a deterministic **floor** for the wanted level; the dispatcher agent may only set the level between the floor and floor + 1 and must give a reason.

| Crime | Floor |
|---|---|
| Shot fired | at least 1 star |
| Car stolen | +1 star (at least 1) |
| Civilian killed | at least 2 stars, +1 for each further one within 60 s |
| Police officer hit | at least 3 stars |
| Police officer killed | at least 4 stars |

5 stars only come from the agent, on sustained escalation (2 or more officers killed, or a taunt at 4 stars). After 30 s without a new crime the level drops by one star every 30 s.

Units per level (at most 6, enforced in the prompt and as a server-side clamp; the scripted fallback follows the same table):

| Stars | Units |
|---|---|
| 1 | 1 officer on foot |
| 2 | 1 on foot + 1 car |
| 3 | 2 on foot + 2 cars |
| 4 | 2 on foot + 4 cars |
| 5 | 2 on foot + 3 cars + 1 tank |

**Player radio** (`player_radio` event): a plea or taunt triggers a dispatcher call right away (8 s cooldown). A plea can take one star off, but only if the last crime was more than 20 s ago and never below the floor. A taunt may add a star and more units. The dispatcher always answers on the radio; without Gemini, a plea has no effect and a taunt adds one star.

**Officers on foot** (`unit_type: "foot"`) walk straight at you, stop at 12 m and shoot every 1.5 s (at most 3 at once). Shooting one sends `police_hit` / `police_killed`. The **tank** (`unit_type: "tank"`, 5 stars) is a dark green, 1.6× police car with a turret; it is slower, does not shoot and pushes.

## Roadmap
- **Google Photorealistic 3D Tiles** instead of extruded OSM blocks, using our own Google Maps Platform key.
- **Maps Grounding** for real facts in quest dialogs. Implemented as a separate cached call, but blocked on this project (HTTP 429 for the `google_maps` tool); the quest giver currently uses the POI descriptions.
- **Gemini TTS** (`gemini-3.8-flash-lite-tts`) for the police radio. The `generate_content` call on API version `v1` was rejected (400, `speechConfig` unknown); next try is `v1beta` or the Interactions API. Until then the browser speaks.
- Send police unit positions to the server so wanted-level decay also waits until no unit is within 40 m (today only the 30 s timer applies).
- Player health, so officers on foot do real damage instead of a red screen flash.

## Repository map
- `main.py`: app and feature loader
- `gemini.py`, `genai_log.py`: Gemini access and logging
- `hub.py`, `ws.py`: event bus and WebSocket
- `protocol.py`: the contract
- `game_state.py`, `runner.py`, `agents/`, `quests.py`: game logic and agents
- `frontend/`: the game (`core/`, `features/`, `landmarks/`, `look/`, `audio/`)
- `scripts/`: OSM bake, checks, worktree setup
- `Design.md`: architecture, contract and features
- `docs/plans/`: implementation plan
- `agent_docs/`: notes on the Gemini API and the deployment
- `TEAM.md`, `CLAUDE.md`: team workflow and rules for Claude Code

## Team
**Adrian Wimmer**. The project was built with Claude Code sessions running in parallel, one git worktree per slice (world, police, quest).

How we worked (details in `TEAM.md`):
- One branch per slice (`feat/<slice>`). Nobody pushes directly to `main`; everything is merged through pull requests.
- `scripts\check.ps1` (ruff, pytest, frontend build) must be green before every push.
- Every developer uses their own Gemini key in their own local `.env`. Keys are never shared or committed.
- Tests always mock Gemini (`fake_gemini`, `tests/fakes.py`), because every live call counts against the request limit.
- Schedule: deadline 19:00, bug fixes only from 18:00.

## Licenses and attribution
The code is released under the [MIT License](LICENSE): you may use, change and redistribute it, as long as the copyright notice stays in.

Map data © OpenStreetMap contributors (ODbL). The HDRI by Poly Haven is CC0.
