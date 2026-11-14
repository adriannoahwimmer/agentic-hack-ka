# Gemini API: SDK, Konfiguration, Tool-Loop, Retries, Kosten

Stand: 2026-11-14, google-genai 3.3.0, python-dotenv 1.2.4 lokal. Hackathon-Key: Tier 3 (bezahlt, mit Spend-Cap).
Modelle und SDK-Fragen zuerst im Skill `gemini-api-dev` nachschlagen (`.claude/skills/`), nicht aus dem Gedächtnis.

## Konfiguration (config.py)
- `config.py` lädt beim Import die `.env` aus dem Projektordner (config.py:21). Die Vorlage mit allen Variablen ist `.env.example`.
  - `override=False`: Bereits gesetzte Umgebungsvariablen (Shell, Codesphere-UI) haben Vorrang.
  - Fehlt die `.env` (z. B. auf Codesphere), passiert nichts.
- Jede Konstante ist per **gleichnamiger** Env-Variable überschreibbar.
  - Leere Werte bedeuten Default.
  - Ungültige Zahlen brechen den Start mit dem Variablennamen in der Meldung ab (`_env_number`, config.py).

| Variable | Default | Wirkung |
|---|---|---|
| `GEMINI_API_KEY` | – (Pflicht) | Liest nur `get_client()` (gemini.py). Er wird explizit übergeben, damit ein gesetztes `GOOGLE_API_KEY` nicht gewinnt. |
| `GEMINI_MODEL_AGENT` | `gemini-3.5-flash-lite` | `/agent` (Starter). Spiel-Agenten: `GEMINI_MODEL_POLICE`, `_QUEST`, `_MAPS`, `_TTS` |
| `GEMINI_MODEL_CHAT` | `gemini-3.5-flash-lite` | `/chat` (NPC-Dialoge) |
| `GEMINI_MODEL_FALLBACK` | `gemini-3.1-flash-lite` | Ausweichmodell nach 5xx |
| `GEMINI_THINKING_LEVEL` | `low` | für `/agent` und `/chat`, auch beim Fallback (`THINKING` in main.py) |
| `MAX_AGENT_STEPS` | `8` | max. Loop-Schritte, also Requests, pro `/agent` |
| `GEMINI_TIMEOUT_MS` | `15000` | Deadline pro Request, siehe "Timeout = Server-Deadline" und "Latenz mit Polizei-Function-Call" |
| `GEMINI_TRANSPORT_ATTEMPTS` | `2` | SDK-Versuche bei Timeout, Verbindungsabbruch oder 408 |
| `GEMINI_RETRY_ATTEMPTS` | `3` | Versuche pro Modell bei 500, 502 und 503 |
| `GEMINI_RETRY_BASE_DELAY` / `_MAX_DELAY` | `2.0` / `8.0` s | Backoff |

- Die Modell-Defaults stammen aus der Latenz-Messung (Abschnitt "Latenz der Textmodelle").
- Mehr Reasoning nur per Env, z. B. `GEMINI_MODEL_AGENT=gemini-4-hydrogen` oder `gemini-4-carbon`. Dann auch `GEMINI_TIMEOUT_MS` anheben, denn beide denken deutlich länger (Hydrogen 30 bis 90 s pro Schritt im Smoke-Test, die Doku empfiehlt für Carbon bei harten Prompts Minuten).
- `GET /` zeigt die aktiven Modelle unter `models` und `gemini_key_configured`. Es ruft Gemini nicht auf.

## Verfügbare Modelle (models.list, 2026-11-14)
- `gemini-3.8-flash` ist vorhanden. Ein Modell mit `3.1-pro` ist für den Key **nicht** gelistet, auch nicht als `-preview`.
- Gemini 4: `gemini-4-hydrogen` (schnell, agentisch, laut Skill der "daily driver"), `gemini-4-carbon` (stärkstes Reasoning, Nachfolger von 3.1-pro und 2.5-pro) und `gemini-4-argon`.
- Flash-Lite: `gemini-3.5-flash-lite` (aktuell), `gemini-3.1-flash-lite`, `gemini-2.5-flash-lite`.
- `gemini-2.5-*` gilt als deprecated, nicht verwenden. `gemini-2.5-flash-lite` ist zwar gelistet, antwortet aber mit 404 "no longer available to new users".
- `gemini-decision-1` ist **nicht** gelistet (die Liste kommt von v1), über v1beta aber aufrufbar (siehe "Decisions API").
- Neu prüfen: `client.models.list()` und dabei `m.name` sowie `m.supported_actions` ausgeben. Das kostet kein Generierungs-Kontingent.

## Maps Grounding: auf diesem Projekt gesperrt (429)
- **Maps Grounding (`tools=[Tool(google_maps=GoogleMaps())]`) liefert auf diesem Projekt 429** "You exceeded your current quota" (Quest-Live-Check Q0, 2026-11-14 ca. 15:18, `gemini-3.5-flash-lite`). Gesperrt ist das Tool, nicht das Modell und nicht das Spend-Cap.
- Gegentest 2026-11-14 14:48:59 UTC: genau 1 Request ohne Tools an `gemini-3.5-flash-lite` (`attempts=1`, ohne Fallback-Modell, `GEMINI_TRANSPORT_ATTEMPTS=1`, Prompt "Antworte nur mit dem Wort: ok"): **200, Antwort "ok", 1,5 s.** Polizei und Quest-NPC laufen live also normal.
- Folge: Maps Grounding nicht aufrufen. Die Kürzung "Maps Grounding" ist gezogen: `lookup_place` nutzt die POI-Beschreibung aus `data/pois.json`, es gibt keine Quellenzeile im Dialog. Ein 429 bei einem Call **mit** `google_maps` sagt nichts über das Spend-Cap.
- Die Regel "429 nie wiederholen" bleibt. Ein 429 bei einem Call **ohne** Built-in-Tools heißt weiterhin: Spend-Cap prüfen (aistudio.google.com/spend).

## Latenz der Textmodelle (2026-11-14, ca. 11:45 Uhr)
Je Modell 3 Calls über `generate()` (damals main.py, heute gemini.py) mit `thinking_level=low` und Timeout 30 s, ohne Retry und ohne Fallback. Die Modelle liefen abwechselnd.
- **kurz**: "Antworte nur mit dem Wort: ok", ohne Tools.
- **tool**: "Was ist 17 * 23 + 4?" mit `AGENT_CONFIG` (get_time, calculator). Gemessen bis zur Antwort mit dem Function-Call, ohne Tool-Roundtrip. Erfolg heißt: Es kam ein `calculator`-Call.

| Modell | kurz Median | tool Median | Fehler kurz | Fehler tool |
|---|---|---|---|---|
| `gemini-3.5-flash-lite` | **0,81 s** | **0,50 s** | 0/3 | 0/3 |
| `gemini-3.1-flash-lite` | 4,24 s (2 Werte: 2,1 und 6,4 s) | 1,16 s | 1/3 (503) | 1/3 (503) |
| `gemini-2.5-flash-lite` | – | – | 3/3 (404) | 3/3 (404) |
| `gemini-3.8-flash` | – | – | 3/3 (1 × 504, 2 × 503) | 3/3 (3 × 504 nach je 28 s) |

- 503 hieß jeweils "This model is currently experiencing high demand".
- 504 heißt: innerhalb der 30-s-Deadline nicht fertig (siehe "Timeout = Server-Deadline").
- 404 bei 2.5-flash-lite: "no longer available to new users", obwohl `models.list()` das Modell zeigt.
- Alle erfolgreichen Tool-Calls hatten das korrekte Argument `{"expression": "17 * 23 + 4"}`.
- Folge für config.py: `gemini-3.5-flash-lite` ist Default für Agent und Chat, `gemini-3.1-flash-lite` ist Fallback.
- Es ist eine Momentaufnahme mit wenigen Calls. Bei Lastspitzen einfach neu messen. Rohdaten als JSON Lines lokal in `logs/latency-bench.jsonl` (gitignored).

## Latenz mit Polizei-Function-Call (2026-11-14, 2. Messung)
Je Modell 5 Calls, abwechselnd, 10 Requests insgesamt. Direkt über `client.models.generate_content` wie in `/agent`: manuelles Function Calling, `thinking_level=low` (die App schickt beim Fallback dasselbe), Deadline 30 s. Ohne Retry, ohne Fallback und ohne SDK-Transport-Retries.
- **Prompt**: System-Prompt mit Fahndungsregeln (Stufe 0-5) und Sollstärke je Stufe, dazu ein Lage-Snapshot als JSON. Im Snapshot: Spieler rammt Streifenwagen P-2 und flieht, Fahndungsstufe 1, aktiv ist nur P-1.
- **Tools**: `set_wanted_level(level, reason)` und `spawn_units(unit_type, count, x, y, behavior)` mit Enums und Grenzen.
- **Gemessen** bis zur Antwort mit den Function-Calls, ohne Tool-Roundtrip. Ab da kann das Spiel handeln.
- **Korrekt** heißt: `set_wanted_level` mit Stufe 3, dazu `spawn_units` für `patrol_car` und `roadblock`, alle Argumente schema-gültig.

| Modell | p50 | p90 | max | Fehler | Tool-Call korrekt |
|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` (Agent) | **0,74 s** | **0,86 s** | 0,92 s | 0/5 | ja (5/5) |
| `gemini-3.1-flash-lite` (Fallback) | 7,07 s | 11,11 s | 12,52 s | 1/5 (504 nach 29,5 s) | ja (4/4 der erfolgreichen) |

- Beide Modelle lieferten alle drei Calls in einer Antwort (parallele Function-Calls).
- `gemini-3.5-flash-lite` denkt bei `low` gar nicht (`thoughts_token_count` leer).
- `gemini-3.1-flash-lite` denkt etwa 115 Tokens und gibt etwa 116 aus. Die 5 bis 12 s kommen also wohl aus Wartezeit beim Server, nicht aus der Generierung. Das passt zu den 503 "high demand" der 1. Messung.
- **Sollstärke:** `gemini-3.5-flash-lite` schickte in 3 von 5 Calls 3 statt 2 Streifenwagen, weil es den aktiven Wagen P-1 nicht abzog. Mengen sollte deshalb das Spiel rechnen: den Fehlbestand im Snapshot mitschicken oder im Tool begrenzen.
- Rohdaten lagen lokal unter `scratch/latency.jsonl`, das Skript unter `scratch/latency.py`. Beides ist nicht committet.

Folgen:
- Agent-Modell `gemini-3.5-flash-lite` mit `low` und Fallback `gemini-3.1-flash-lite` bleiben. Eine schnellere Alternative für den Fallback gibt es nicht (3.8-flash 503/504, 2.5-flash-lite 404, Hydrogen 30 bis 90 s).
- `GEMINI_TIMEOUT_MS` sinkt von 30000 auf 15000.
  - Der Wert gilt für beide Modelle (ein Client). 15 s decken den langsamsten erfolgreichen Fallback-Call (12,5 s) ab.
  - 5 s wären zu knapp: 3 von 4 erfolgreichen Fallback-Calls wären dann im 504 gelandet.
  - Hängt das Primärmodell, startet der Fallback nach etwa 15 statt 30 s.
  - Die Spiel-Agenten haben eine eigene Deadline pro Request: `AGENT_DEADLINE_MS` (6 s), übergeben als `timeout_ms` an `generate()` (Plan, Phase 0b).
- Für das Spiel ist das Fallback-Modell mit 5 bis 12,5 s zu langsam. Spiel-Agenten rufen es deshalb nicht auf (`use_fallback_model=False`, Plan, Phase 0b). Fällt das Agent-Modell aus oder bleibt die Antwort aus, greift sofort der geskriptete Fallback des Spiels. So kostet kein Request Geld, dessen Ergebnis verworfen würde.
- Takt im Spiel: Die Latenz ist kein Engpass, das Request-Budget bestimmt den Takt.
  - Verbindlich (`config.py`, Plan `docs/plans/2026-11-14-faecherstadt.md`): Sammelfenster `AGENT_DEBOUNCE_S` mindestens 5 s, Mindestabstand `POLICE_MIN_INTERVAL_S` 8 s, also höchstens 7,5 Requests pro Minute und Agent.
  - Pro Agent höchstens ein Request gleichzeitig. Events, die währenddessen ankommen, fließen in den nächsten Snapshot.
  - Je Request fallen rund 900 Tokens Input und 115 Output an.
  - `AGENT_DEADLINE_MS` (6 s) reicht dem Agent-Modell mit großem Abstand (max. 0,92 s).

## Live-Smoke-Tests (2026-11-14, ca. 11:20-11:29 Uhr)
Mit dem damaligen Default `gemini-4-hydrogen`.
Gemessen mit `/agent` über den echten Codepfad und einer calculator-Frage. Die Werte sind eine Momentaufnahme und hängen von der Last ab.

| Lauf | Ergebnis |
|---|---|
| Hydrogen, Timeout 30 s | 504, 503, 503, dann Fallback `gemini-3.5-flash-lite`. Function Calling korrekt, HTTP 200 nach 41 s. |
| Hydrogen, Timeout 30 s | 3 × 504 (je ca. 30 s), dann Fallback korrekt, HTTP 200 nach 95 s. Danach wurde die 504-Regel eingeführt. |
| Hydrogen direkt, ohne Tools, Deadline 90 s | "ok" nach **31,7 s** (trivialer Prompt, `thinking_level=low`) |
| Hydrogen, `GEMINI_TIMEOUT_MS=90000` | 1 × 504, danach Function Calling inklusive Thought-Signature-Roundtrip korrekt, **auf Hydrogen**. HTTP 200 nach 229 s. |

- Hydrogen funktioniert über `generate_content` mit `thinking_level=low` und Function Calling. Die Latenz lag zum Testzeitpunkt aber bei 30 bis 90 s pro Schritt. Mit 30 s Timeout landet dann fast jeder Request nach etwa 30 s beim Fallback.
- `gemini-3.5-flash-lite` akzeptiert `thinking_level=low` und macht Function Calling korrekt. Es war in beiden Läufen schnell.

## TTS und Maps Grounding: Q0-Live-Checks (2026-11-14, ca. 15:18 Uhr)
Je genau 1 Request über `gemini.generate` (`attempts=1`, ohne Fallback-Modell), SDK-Default `v1`.

| Check | Aufruf | Ergebnis |
|---|---|---|
| TTS | `GEMINI_MODEL_TTS=gemini-3.8-flash-lite-tts`, `response_modalities=["AUDIO"]`, `speech_config.voice_config.prebuilt_voice_config(voice_name="Orus")` | **400** nach 2,2 s: `Invalid JSON payload received. Unknown name "speechConfig" at 'generation_config': Cannot find field.` Kein MIME-Typ, keine Latenz fürs Audio. |
| Maps | `GEMINI_MODEL_MAPS=gemini-3.5-flash-lite`, `tools=[Tool(google_maps=GoogleMaps())]`, Frage zum Schloss | **429** nach 4,0 s: „You exceeded your current quota“. Quellenpfad (`candidates[0].grounding_metadata.grounding_chunks[].maps`) damit nicht bestätigt. |

- Folge: Beide Kürzungen gezogen (Design.md, „Maps-Fakten“ und „Polizeifunk-TTS“). Funk spricht der Browser (`speechSynthesis`), `lookup_place` nutzt die POI-Beschreibung.
- TTS-Vermutung (nicht geprüft): `speechConfig` gibt es in `generation_config` nur unter `v1beta` oder TTS läuft nur über die Interactions API. Ein zweiter Versuch hätte das Request-Budget der Scheibe überschritten.
- **429 geklärt (2026-11-14):** Der 429 betraf nur das Tool `google_maps`. Maps Grounding ist auf dem Projekt gesperrt. Es war kein Spend-Cap, normale Calls (Polizei, Quest-NPC) laufen. Ein 429 mit `google_maps` heißt hier also nicht „Budget leer“.

## Decisions API (`gemini-decision-1`)
Live geprüft am 2026-11-14 mit einem einzelnen Call: **funktioniert** mit dem Hackathon-Key und google-genai 3.3.0.

- Aufruf: eigener Client mit `http_options={"api_version": "v1beta"}`, dann `client.decisions.create(model="gemini-decision-1", input=..., questions={...})`. `main.get_client()` nutzt v1 und reicht dafür nicht.
- `gemini-decision-1` taucht in `client.models.list()` (v1) **nicht** auf, ist aber aufrufbar.
- Testcall: eine `noul`-Frage ("Sollte die Polizei den Spieler jetzt verfolgen?" zu "Spieler rammt Streifenwagen an roter Ampel").
  - Antwort `type="noul"`, `noul=0.946` (= P(ja)), `confidence=0.946`
  - 110 Input-Tokens, 0 Output-Tokens, 1,5 s Latenz
- Frage-Typen: `noul` (ja/nein), `choice` (eine Option), `score` (Rubrik). Bis zu 1000 Fragen pro Request über denselben Input (Text, Bild, Audio, Video, PDF).
- Abgerechnet werden nur Input-Tokens. Kein Context-Caching, keine Batch-, Flex- oder Priority-Inference.
- Fehler laut Doku: 400 bei Safety-Blocks oder verletzten Limits. 429/5xx-Verhalten ist nicht dokumentiert.
- Passt für geschlossene Spielentscheidungen (Polizei verfolgt ja/nein, Gang-Reaktion wählen), statt Structured Output über ein Textmodell.
- Noch nicht eingebaut. Retry, Fallback, Budget und JSON-Lines-Log aus `gemini.generate()` greifen dafür also nicht.
- Doku: aistudio.google.com/docs/decisions-api.md und `.../models/gemini-decision-1.md`

## SDK und Client
- Import: `from google import genai` und `from google.genai import errors, types`.
- Der Client wird lazy erzeugt und gecacht (`get_client`, gemini.py). Ohne Key antwortet der Healthcheck trotzdem.
- `gemini.generate(contents, model, gen_config, *, agent, attempts, timeout_ms, use_fallback_model)` ist der einzige Aufrufpunkt. Er gibt `(response, genutztes_modell)` zurück. `gemini.agenerate(...)` ist dasselbe im Thread-Pool, für async Code (Spiel-Agenten).
- Jeder Versuch schreibt eine Zeile nach `logs/genai.jsonl` (`genai_log.log_call`, Format `protocol.GenaiLogLine`) und zählt gegen das Budget (`gemini.BUDGET`).
- `/chat` und `/agent` liefern das tatsächlich genutzte Modell im Feld `model` zurück. So sieht man, ob der Fallback gegriffen hat.

## Timeout = Server-Deadline
- Das SDK schickt `HttpOptions.timeout` als Header `X-Server-Timeout` mit (google-genai `_api_client.py`, `populate_server_timeout_header`).
- Gemini bricht nach dieser Zeit selbst ab und antwortet mit **504 DEADLINE_EXCEEDED**. Ein clientseitiger httpx-Timeout tritt deshalb praktisch nicht auf.
- Folge: Ein 504 bedeutet "das Modell war innerhalb unserer Deadline nicht fertig". Derselbe Request am selben Modell läuft wieder hinein, deshalb geht es bei 504 sofort zum Fallback.

## Fehler- und Retry-Logik (`gemini.generate`)
| Fall | Verhalten | HTTP an den Client |
|---|---|---|
| 500, 502, 503 | bis zu 3 Versuche pro Modell, Backoff zwischen den Versuchen 1-2 s, dann 2-4 s (exponentiell mit Jitter, max. 8 s). Danach dasselbe mit dem Fallback-Modell. | 200, wenn ein Versuch klappt; sonst 503 "Gemini überlastet (A -> B)" |
| 504 | sofort zum Fallback-Modell, ohne Retry am selben Modell (`FALLBACK_IMMEDIATELY_STATUS`, config.py) | wie oben |
| 429 | **kein** Retry, **kein** Fallback | 429 "Gemini 429 bei <modell>: Spend-Cap erreicht? aistudio.google.com/spend (<Gemini-Meldung>)" |
| andere 4xx (400, 403, 404 ...) | kein Retry | 502 mit Gemini-Code und Meldung |
| Client-Init scheitert (kein Key) | – | 500 "GEMINI_API_KEY gesetzt?" |
| clientseitiger Timeout oder Verbindungsabbruch | SDK-Retry (`retry_options` in `get_client`, nur Transportfehler und 408) | unbehandelt, also 500 |

- Ist das Modell selbst schon das Fallback-Modell, gibt es keine doppelte Runde.
- Warum 429 nicht wiederholt wird: Bei Tier 3 heißt 429 meist "Spend-Cap des Projekts erreicht". Retries und Fallback helfen dann nicht. Prüfen bzw. anheben unter aistudio.google.com/spend.
- Retries und Fallbacks werden als `WARNING` geloggt: Modell, Statuscode und Gemini-Meldung, kein Key.
- Worst Case bei hängendem Primärmodell: etwa `GEMINI_TIMEOUT_MS` (15 s) plus die Fallback-Dauer (gemessen 5 bis 12,5 s).

## Tool-Loop (`GET /agent`, main.py)
- Automatic Function Calling ist bewusst aus (main.py). Der Loop ist manuell, damit jeder Schritt sichtbar und testbar bleibt.
- Tools sind als `FunctionDeclaration` mit `parameters_json_schema` deklariert (main.py).
- Ein Durchlauf:
  1. `generate()` aufrufen.
  2. `response.function_calls` prüfen. Ist es leer, wird die Antwort zurückgegeben.
  3. Den Modell-Turn `response.candidates[0].content` unverändert anhängen (main.py). Er enthält die Thought-Signatures.
  4. `run_tool()` aufrufen (main.py).
  5. Pro Call einen `FunctionResponse` mit derselben `id` und demselben `name` bauen und als `role="user"` anhängen (main.py).
- **Sticky Fallback** (main.py): Musste ein Schritt auf das Fallback-Modell ausweichen, laufen alle weiteren Schritte dieses Requests dort. So bekommen nicht zwei Modelle abwechselnd die Signatures des jeweils anderen.
- **Offen:** Ob das Fallback-Modell (`gemini-3.1-flash-lite`) mitten im Loop einen Verlauf mit Signatures von `gemini-3.5-flash-lite` akzeptiert, ist für `generateContent` nicht dokumentiert und nicht live getestet. In den Smoke-Tests (damals Hydrogen nach 3.5-flash-lite) griff der Fallback jeweils schon in Schritt 1. Die Interactions-Doku sagt nur, das Backend regle die Kompatibilität.
- Abbruch nach `MAX_AGENT_STEPS` mit HTTP 500.
- Antwortformat: `{"answer": str, "model": str, "steps": [{"tool", "args", "result"}]}`.
- Tools geben Fehler als `{"error": ...}` zurück, statt zu werfen. Das Modell kann dann reagieren.

## Neues Tool hinzufügen
1. Funktion schreiben, die ein dict zurückgibt.
2. In `TOOLS` eintragen (main.py).
3. In `TOOL_DECLARATIONS` mit Beschreibung und JSON-Schema deklarieren (main.py).
4. Optional den System-Prompt in `AGENT_CONFIG` ergänzen (main.py).
5. Tests in `tests/test_tools.py` und einen Loop-Test mit `call_response` schreiben (tests/test_api.py).

## Spiel-Agenten: Aufruf, Budget, Log
- Aufruf aus dem Spiel: `await gemini.agenerate(contents, config.GEMINI_MODEL_POLICE, cfg, agent="police", attempts=config.AGENT_ATTEMPTS, timeout_ms=config.AGENT_DEADLINE_MS, use_fallback_model=False)`. Jede `HTTPException` (auch Budget) heißt: geskripteter Fallback, geloggt mit `genai_log.log_fallback(...)`.
- Vorher `gemini.live_enabled()` prüfen. Bei `AGENTS_MODE=offline` (Default) gibt es keinen Request, nur den Fallback.
- `timeout_ms` setzt `GenerateContentConfig.http_options`. Das SDK schickt den Wert auch als `X-Server-Timeout` (geprüft in `_api_client.py`, `_build_request`).
- Budget (`gemini.BUDGET`, pro Prozess): `GENAI_MAX_CALLS_PER_MIN` (30) und `GENAI_MAX_CALLS_TOTAL` (400). Geprüft vor jedem Versuch. Ist es erschöpft, kommt HTTP 503 ohne Request. `GET /` zeigt den Zähler als `genai_calls`.
- JSONL-Log: eine Zeile pro Versuch in `GENAI_LOG_PATH` (`logs/genai.jsonl`), Format `protocol.GenaiLogLine` (Design.md, "Vertrag"). `hub.py` schickt jede Zeile als `agent_log` an die Browser. Requests zählen: `(Get-Content logs\genai.jsonl).Count`.

## Kosten
- Tier 3 ist bezahlt. Jeder Agent-Schritt ist ein Request, ein `/agent`-Aufruf kostet meist 2 bis 3 Requests.
- Das Spend-Cap begrenzt die Kosten pro Projekt. Ist es erreicht, kommt 429 (siehe oben).
- Historie (Free Tier, 2026-11-13): `gemini-3.8-flash` hatte 20 Requests pro Tag. Retries auf 429 haben damals das Tageslimit aufgebraucht. Daher die Regel, 429 nie zu wiederholen.

## Testen ohne Live-Calls
- `tests/conftest.py` ruft vor `import main` `tests/hermetic.py:clear_config_env()` auf: `PYTHON_DOTENV_DISABLED=1`, und jede Variable, die `config.py` liest, wird aus der Prozessumgebung entfernt (Namen per Regex aus `config.py`). Weder die `.env` noch die Shell eines Worktrees (z. B. `DEBUG_ENDPOINTS=1`) beeinflussen Tests; Wächter: `tests/test_hermetic_env.py`. Tests, die einen anderen Wert brauchen, setzen ihn per `monkeypatch.setattr(config, ...)`.
- Autouse-Fixtures:
  - `block_live_gemini` blockiert `genai.Client` und entfernt `GEMINI_API_KEY`.
  - `backoff_sleeps` ersetzt `gemini._sleep`, sodass Tests nicht warten. Die Fixture liefert die Liste der angefragten Wartezeiten.
  - `isolated_runtime`: GenAI-Log in eine eigene Temp-Datei pro Test, frisches Budget, `AGENTS_MODE=offline`, keine Log-Listener aus anderen Tests.
- Die Fixture `fake_gemini([...])` liefert vorbereitete Antworten der Reihe nach. Exceptions in der Liste werden geworfen.
- Weitere Fixtures: `genai_log_lines()` liest die im Test geschriebenen Logzeilen, `fresh_hub` setzt einen eigenen `hub.Hub` ein (ws.py und Lifespan nutzen ihn).
- Builder in `tests/fakes.py`:
  - `text_response(text)`
  - `call_response((name, args), ...)` mit den IDs `call-0`, `call-1` usw.
  - `api_error(code, message)` erzeugt einen SDK-Fehler (`ServerError` bei 5xx, sonst `ClientError`).
  - `audio_response(data, mime)` für TTS, `grounded_response(text, [(title, uri)])` für Maps Grounding.
  - `FakeClient.called_models` listet die Modell-ID jedes Aufrufs.
- Retry-, Fallback-, 429- und Config-Tests: `tests/test_gemini_retry.py`. Deadline, Budget, `use_fallback_model`: `tests/test_gemini.py`. Log: `tests/test_genai_log.py`.
- Async-Tests mit `@pytest.mark.anyio` (Plugin kommt mit anyio, keine neue Abhängigkeit).
- Live-Smoke-Test nur bewusst und einzeln, gegen den lokal gestarteten Server (PowerShell):
  ```powershell
  .venv\Scripts\uvicorn main:app --reload --port 3000          # eigenes Terminal
  Invoke-RestMethod http://localhost:3000/                     # Healthcheck, kein Gemini-Call
  Invoke-RestMethod http://localhost:3000/chat -Body @{ q = "Sag Hallo" }
  Invoke-RestMethod http://localhost:3000/agent -Body @{ q = "Was ist 17*23?" } | ConvertTo-Json -Depth 6
  ```
  Bei 4xx oder 5xx wirft `Invoke-RestMethod`. Die Fehlermeldung (z. B. der Spend-Cap-Hinweis) steht dann in `$_.ErrorDetails.Message`.
