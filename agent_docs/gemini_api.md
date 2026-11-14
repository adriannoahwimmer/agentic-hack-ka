# Gemini API: SDK, Tool-Loop, Retries, Quota

Stand: 2026-11-13, google-genai 3.3.0 lokal.

## SDK und Client
- Import: `from google import genai` und `from google.genai import errors, types`.
- Der Client wird lazy erzeugt und gecacht (`get_client`, main.py:26-40). Er liest `GEMINI_API_KEY` aus der Umgebung. Ohne Key antwortet der Healthcheck trotzdem.
- `generate()` (main.py:43-55) ist der einzige Aufrufpunkt:
  - Scheitert die Client-Erzeugung, antwortet die API mit 500.
  - Bei `errors.APIError` antwortet sie mit 502 und gibt Gemini-Code und -Meldung weiter.
- Modell: `GEMINI_MODEL`, Default `gemini-3.8-flash` (main.py:17). Verfügbare Modelle liefert `client.models.list()`.

## Tool-Loop (`GET /agent`, main.py:171-203)
- Automatic Function Calling ist bewusst aus (main.py:139). Der Loop ist manuell, damit jeder Schritt sichtbar und testbar bleibt.
- Tools sind als `FunctionDeclaration` mit `parameters_json_schema` deklariert (main.py:110-131).
- Ein Durchlauf:
  1. `generate()` aufrufen.
  2. `response.function_calls` prüfen. Ist es leer, wird die Antwort zurückgegeben.
  3. Den Modell-Turn `response.candidates[0].content` unverändert anhängen (main.py:185). Gemini-3-Modelle brauchen die Thought-Signatures darin.
  4. `run_tool()` aufrufen (main.py:143-150).
  5. Pro Call einen `FunctionResponse` mit derselben `id` und demselben `name` bauen und als `role="user"` anhängen (main.py:187-199).
- Abbruch nach `MAX_AGENT_STEPS` (main.py:18) mit HTTP 500.
- Antwortformat: `{"answer": str, "steps": [{"tool", "args", "result"}]}`. Die `steps` sind für Debugging und Demo gedacht.
- Tools geben Fehler als `{"error": ...}` zurück, statt zu werfen. Das Modell kann dann reagieren. Siehe `calculator` (main.py:95-103) mit AST-Auswertung ohne `eval`.

## Neues Tool hinzufügen
1. Funktion schreiben, die ein dict zurückgibt.
2. In `TOOLS` eintragen (main.py:108).
3. In `TOOL_DECLARATIONS` mit Beschreibung und JSON-Schema deklarieren (main.py:110).
4. Optional den System-Prompt in `AGENT_CONFIG` ergänzen (main.py:133-140).
5. Tests in `tests/test_tools.py` und einen Loop-Test mit `call_response` schreiben (tests/test_api.py).

## Retry-Logik (main.py:30-39)
- `HttpRetryOptions`: 3 Versuche, Wartezeit 2 s bis 8 s, nur bei HTTP 500/502/503/504. Timeout 60 s pro Request.
- **429 wird nie wiederholt**, weil es meist das Tageslimit ist. Retries würden das Kontingent nur weiter aufbrauchen. Am 2026-11-13 hat genau das das Tageslimit gekostet.
- 503 "high demand" kam bei `gemini-3.8-flash` häufig. Mit Retries kann ein Request dann 30 bis 60 s dauern.

## Quota (Free Tier, beobachtet am 2026-11-13)
- `gemini-3.8-flash`: 20 Requests pro Tag. Reset um Mitternacht Pacific, also gegen 09:00 deutscher Zeit.
- Eine Anfrage mit `gemini-3.7-flash` wurde laut Fehlermeldung auf das 3.8-Kontingent gebucht.
- Ein `/agent`-Aufruf kostet 2 bis 3 Requests (ein Request pro Loop-Schritt).
- Ausweichen: `GEMINI_MODEL=gemini-3.1-flash-lite` hat ein eigenes Kontingent und funktionierte inklusive Tool-Loop. Für die Demo besser einen Key mit Billing oder Credits nutzen.

## Testen ohne Quota
- `tests/conftest.py` blockiert `genai.Client` per autouse-Fixture und entfernt `GEMINI_API_KEY`.
- Die Fixture `fake_gemini([...])` liefert vorbereitete Antworten der Reihe nach. Exceptions in der Liste werden geworfen.
- Antwort-Builder in `tests/fakes.py`: `text_response(text)` und `call_response((name, args), ...)`, mit den IDs `call-0`, `call-1` usw.
- Live-Smoke-Test nur bewusst und einzeln, z. B. `GET /chat` gegen den lokal gestarteten Server.
