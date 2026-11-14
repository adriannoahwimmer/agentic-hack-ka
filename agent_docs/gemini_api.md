# Gemini API: SDK, Konfiguration, Tool-Loop, Retries, Kosten

Stand: 2026-11-14, google-genai 3.3.0, python-dotenv 1.2.4 lokal. Hackathon-Key: Tier 3 (bezahlt, mit Spend-Cap).
Modelle und SDK-Fragen zuerst im Skill `gemini-api-dev` nachschlagen (`.claude/skills/`), nicht aus dem Gedächtnis.

## Konfiguration (config.py)
- `config.py` lädt beim Import die `.env` aus dem Projektordner (config.py:21). Die Vorlage mit allen Variablen ist `.env.example`.
  - `override=False`: Bereits gesetzte Umgebungsvariablen (Shell, Codesphere-UI) haben Vorrang.
  - Fehlt die `.env` (z. B. auf Codesphere), passiert nichts.
- Jede Konstante ist per **gleichnamiger** Env-Variable überschreibbar.
  - Leere Werte bedeuten Default.
  - Ungültige Zahlen brechen den Start mit dem Variablennamen in der Meldung ab (`_env_number`, config.py:29).

| Variable | Default | Wirkung |
|---|---|---|
| `GEMINI_API_KEY` | – (Pflicht) | Liest nur `get_client()` (main.py:37). Er wird explizit übergeben, damit ein gesetztes `GOOGLE_API_KEY` nicht gewinnt. |
| `GEMINI_MODEL_AGENT` | `gemini-3.5-flash-lite` | `/agent` (Polizei- und Gang-Agenten) |
| `GEMINI_MODEL_CHAT` | `gemini-3.5-flash-lite` | `/chat` (NPC-Dialoge) |
| `GEMINI_MODEL_FALLBACK` | `gemini-3.1-flash-lite` | Ausweichmodell nach 5xx |
| `GEMINI_THINKING_LEVEL` | `low` | für `/agent` und `/chat`, auch beim Fallback (main.py:202-214) |
| `MAX_AGENT_STEPS` | `8` | max. Loop-Schritte, also Requests, pro `/agent` |
| `GEMINI_TIMEOUT_MS` | `30000` | Deadline pro Request, siehe "Timeout = Server-Deadline" |
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

## Latenz der Textmodelle (2026-11-14, ca. 11:45 Uhr)
Je Modell 3 Calls über `main.generate()` mit `thinking_level=low` und Timeout 30 s, ohne Retry und ohne Fallback. Die Modelle liefen abwechselnd.
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
- Noch nicht in `main.py` eingebaut. Retry, Fallback und JSON-Lines-Log aus `generate()` greifen dafür also nicht.
- Doku: aistudio.google.com/docs/decisions-api.md und `.../models/gemini-decision-1.md`

## SDK und Client
- Import: `from google import genai` und `from google.genai import errors, types`.
- Der Client wird lazy erzeugt und gecacht (`get_client`, main.py:36-53). Ohne Key antwortet der Healthcheck trotzdem.
- `generate(contents, model, gen_config)` (main.py:64-124) ist der einzige Aufrufpunkt. Er gibt `(response, genutztes_modell)` zurück.
- `/chat` und `/agent` liefern das tatsächlich genutzte Modell im Feld `model` zurück. So sieht man, ob der Fallback gegriffen hat.

## Timeout = Server-Deadline
- Das SDK schickt `HttpOptions.timeout` als Header `X-Server-Timeout` mit (google-genai `_api_client.py`, `populate_server_timeout_header`).
- Gemini bricht nach dieser Zeit selbst ab und antwortet mit **504 DEADLINE_EXCEEDED**. Ein clientseitiger httpx-Timeout tritt deshalb praktisch nicht auf.
- Folge: Ein 504 bedeutet "das Modell war innerhalb unserer Deadline nicht fertig". Derselbe Request am selben Modell läuft wieder hinein, deshalb geht es bei 504 sofort zum Fallback.

## Fehler- und Retry-Logik (main.py:64-124)
| Fall | Verhalten | HTTP an den Client |
|---|---|---|
| 500, 502, 503 | bis zu 3 Versuche pro Modell, Backoff zwischen den Versuchen 1-2 s, dann 2-4 s (exponentiell mit Jitter, max. 8 s). Danach dasselbe mit dem Fallback-Modell. | 200, wenn ein Versuch klappt; sonst 503 "Gemini überlastet (A -> B)" |
| 504 | sofort zum Fallback-Modell, ohne Retry am selben Modell (`FALLBACK_IMMEDIATELY_STATUS`, config.py:72) | wie oben |
| 429 | **kein** Retry, **kein** Fallback | 429 "Gemini 429 bei <modell>: Spend-Cap erreicht? aistudio.google.com/spend (<Gemini-Meldung>)" |
| andere 4xx (400, 403, 404 ...) | kein Retry | 502 mit Gemini-Code und Meldung |
| Client-Init scheitert (kein Key) | – | 500 "GEMINI_API_KEY gesetzt?" |
| clientseitiger Timeout oder Verbindungsabbruch | SDK-Retry (`retry_options`, main.py:46-51, nur Transportfehler und 408) | unbehandelt, also 500 |

- Ist das Modell selbst schon das Fallback-Modell, gibt es keine doppelte Runde.
- Warum 429 nicht wiederholt wird: Bei Tier 3 heißt 429 meist "Spend-Cap des Projekts erreicht". Retries und Fallback helfen dann nicht. Prüfen bzw. anheben unter aistudio.google.com/spend.
- Retries und Fallbacks werden als `WARNING` geloggt: Modell, Statuscode und Gemini-Meldung, kein Key.
- Worst Case bei hängendem Primärmodell: etwa `GEMINI_TIMEOUT_MS` plus die Fallback-Dauer.

## Tool-Loop (`GET /agent`, main.py:251-288)
- Automatic Function Calling ist bewusst aus (main.py:212). Der Loop ist manuell, damit jeder Schritt sichtbar und testbar bleibt.
- Tools sind als `FunctionDeclaration` mit `parameters_json_schema` deklariert (main.py:179-200).
- Ein Durchlauf:
  1. `generate()` aufrufen.
  2. `response.function_calls` prüfen. Ist es leer, wird die Antwort zurückgegeben.
  3. Den Modell-Turn `response.candidates[0].content` unverändert anhängen (main.py:269). Er enthält die Thought-Signatures.
  4. `run_tool()` aufrufen (main.py:217).
  5. Pro Call einen `FunctionResponse` mit derselben `id` und demselben `name` bauen und als `role="user"` anhängen (main.py:271-283).
- **Sticky Fallback** (main.py:263): Musste ein Schritt auf das Fallback-Modell ausweichen, laufen alle weiteren Schritte dieses Requests dort. So bekommen nicht zwei Modelle abwechselnd die Signatures des jeweils anderen.
- **Offen:** Ob das Fallback-Modell (`gemini-3.1-flash-lite`) mitten im Loop einen Verlauf mit Signatures von `gemini-3.5-flash-lite` akzeptiert, ist für `generateContent` nicht dokumentiert und nicht live getestet. In den Smoke-Tests (damals Hydrogen nach 3.5-flash-lite) griff der Fallback jeweils schon in Schritt 1. Die Interactions-Doku sagt nur, das Backend regle die Kompatibilität.
- Abbruch nach `MAX_AGENT_STEPS` mit HTTP 500.
- Antwortformat: `{"answer": str, "model": str, "steps": [{"tool", "args", "result"}]}`.
- Tools geben Fehler als `{"error": ...}` zurück, statt zu werfen. Das Modell kann dann reagieren.

## Neues Tool hinzufügen
1. Funktion schreiben, die ein dict zurückgibt.
2. In `TOOLS` eintragen (main.py:177).
3. In `TOOL_DECLARATIONS` mit Beschreibung und JSON-Schema deklarieren (main.py:179).
4. Optional den System-Prompt in `AGENT_CONFIG` ergänzen (main.py:206-214).
5. Tests in `tests/test_tools.py` und einen Loop-Test mit `call_response` schreiben (tests/test_api.py).

## Kosten
- Tier 3 ist bezahlt. Jeder Agent-Schritt ist ein Request, ein `/agent`-Aufruf kostet meist 2 bis 3 Requests.
- Das Spend-Cap begrenzt die Kosten pro Projekt. Ist es erreicht, kommt 429 (siehe oben).
- Historie (Free Tier, 2026-11-13): `gemini-3.8-flash` hatte 20 Requests pro Tag. Retries auf 429 haben damals das Tageslimit aufgebraucht. Daher die Regel, 429 nie zu wiederholen.

## Testen ohne Live-Calls
- `tests/conftest.py` setzt `PYTHON_DOTENV_DISABLED=1` vor `import main`. Tests laden die lokale `.env` also nie, weder den echten Key noch Overrides.
- Autouse-Fixtures:
  - `block_live_gemini` blockiert `genai.Client` und entfernt `GEMINI_API_KEY`.
  - `backoff_sleeps` ersetzt `main._sleep`, sodass Tests nicht warten. Die Fixture liefert die Liste der angefragten Wartezeiten.
- Die Fixture `fake_gemini([...])` liefert vorbereitete Antworten der Reihe nach. Exceptions in der Liste werden geworfen.
- Builder in `tests/fakes.py`:
  - `text_response(text)`
  - `call_response((name, args), ...)` mit den IDs `call-0`, `call-1` usw.
  - `api_error(code, message)` erzeugt einen SDK-Fehler (`ServerError` bei 5xx, sonst `ClientError`).
  - `FakeClient.called_models` listet die Modell-ID jedes Aufrufs.
- Retry-, Fallback-, 429- und Config-Tests: `tests/test_gemini_retry.py`.
- Live-Smoke-Test nur bewusst und einzeln, gegen den lokal gestarteten Server (PowerShell):
  ```powershell
  .venv\Scripts\uvicorn main:app --reload --port 3000          # eigenes Terminal
  Invoke-RestMethod http://localhost:3000/                     # Healthcheck, kein Gemini-Call
  Invoke-RestMethod http://localhost:3000/chat -Body @{ q = "Sag Hallo" }
  Invoke-RestMethod http://localhost:3000/agent -Body @{ q = "Was ist 17*23?" } | ConvertTo-Json -Depth 6
  ```
  Bei 4xx oder 5xx wirft `Invoke-RestMethod`. Die Fehlermeldung (z. B. der Spend-Cap-Hinweis) steht dann in `$_.ErrorDetails.Message`.
