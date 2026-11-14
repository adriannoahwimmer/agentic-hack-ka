# Fächerstadt Agents

Video: TBD

A browser open world around Karlsruhe Palace, built from real OpenStreetMap data: walk, drive, shoot, and get chased by the police. The twist: nothing is scripted. A Gemini police dispatcher and a Gemini quest giver make the decisions through function calling. The game never waits for them, because deterministic rules and scripted fallbacks keep it running when the model is slow or offline.

Built in one day at the {Tech: Europe} Agentic AI Hack Karlsruhe (2026-11-14).

## Demo path
1. Walk up to **Karl the Fixer** on Palace Square and press **E**. The quest agent picks a real place from the map and gives you a mission.
2. Steal a car (**F**) and drive to the target. The marker and the minimap show the way.
3. When you arrive, the enemies show up ("Here they come!"). Shoot them.
4. The shots raise your wanted level immediately (rule-based floor). After the event window, the dispatcher agent decides how far to escalate: stars, number of units, tactic (chase, roadblock, surround) and a radio message.
5. Police cars spawn and chase you. The radio message appears as a subtitle and is spoken by the browser.
6. Kill the last target and you get **Mission complete**.

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
- **Logging.** Every Gemini request goes to `logs/genai.jsonl` as one JSON line: agent, model, tool calls, reason, latency, without keys. Each line is also sent to the browser as `agent_log`; the in-game overlay for it is still open.
- **Map.** OSM data is baked once into compact JSON (`scripts/bake_osm.py`, 959 buildings, 1546 road segments, 230 areas) with a single projection (`geo.py`, origin at the palace). There are no map requests at runtime.

## Landmarks
_Placeholder, to be confirmed after the landmarks merge._

Hand-modelled low-poly models of the Palace, the Pyramid, the Protestant City Church and the Town Hall (Rathaus) replace the generic extruded OSM blocks at these spots.

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
- WebGL, WebSocket, Pointer Lock, Web Speech API (`speechSynthesis`, radio voice), Web Audio API (radio static), localStorage.

**Data and assets**
- OpenStreetMap, © OpenStreetMap contributors, ODbL. The city geometry was fetched once from the OpenStreetMap API 0.6 (`map` call in 2 × 2 tiles, because no Overpass server answered that afternoon). The POI coordinates came from the Overpass API (mirror `maps.mail.ru`).
- HDRI "Kloofendal 48d Partly Cloudy (Pure Sky)" by Poly Haven, CC0.

**Development tools**
- ruff, pytest, httpx (test client), gitleaks (secret scan), GitHub CLI, and Claude Code (agentic development, up to five parallel sessions in git worktrees).

**Prepared, not deployed**
- Codesphere (`ci.yml`).

## Roadmap
- **Google Photorealistic 3D Tiles** instead of extruded OSM blocks, using our own Google Maps Platform key.
- **Maps Grounding** for real facts in quest dialogs. Implemented as a separate cached call, but blocked on this project (HTTP 429 for the `google_maps` tool); the quest giver currently uses the POI descriptions.
- **Gemini TTS** (`gemini-3.8-flash-lite-tts`) for the police radio. The `generate_content` call on API version `v1` was rejected (400, `speechConfig` unknown); next try is `v1beta` or the Interactions API. Until then the browser speaks.
- The in-game agent log overlay (the server already streams `agent_log`).

## Repository map
- `main.py`: app and feature loader
- `gemini.py`, `genai_log.py`: Gemini access and logging
- `hub.py`, `ws.py`: event bus and WebSocket
- `protocol.py`: the contract
- `game_state.py`, `runner.py`, `agents/`, `quests.py`: game logic and agents
- `frontend/`: the game
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
Map data © OpenStreetMap contributors (ODbL). The HDRI by Poly Haven is CC0.
