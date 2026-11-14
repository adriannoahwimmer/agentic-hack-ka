"""Gemini-Zugriff für alle Agenten: Client, Retry/Fallback, Request-Budget, JSONL-Log.

Zweck: einziger Aufrufpunkt für GenAI-Requests. Jeder Versuch wird als JSON-Zeile
geloggt (genai_log) und zählt gegen ein hartes Budget pro Prozess.
Use-Cases:
- Starter-Endpoints /chat und /agent (main.py): generate() mit Retry und Fallback-Modell
- Spiel-Agenten (Polizei, Quest, Maps, TTS): agenerate() mit kurzer Deadline,
  einem Versuch und ohne Fallback-Modell; bei Fehler greift ihr geskripteter Fallback

Modelle, Limits, Timeouts und Budget stehen in config.py. Den API-Key liest nur
get_client() aus der Umgebung; er landet nie im Log.
"""

import asyncio
import logging
import os
import random
import threading
import time
from collections import deque
from functools import lru_cache

from fastapi import HTTPException
from google import genai
from google.genai import errors, types

import config
import genai_log

log = logging.getLogger(__name__)
_sleep = time.sleep  # Tests ersetzen das, damit Backoff nicht wirklich wartet


# --------------------------------------------------------------------------
# Client (lazy, damit der Healthcheck auch ohne API-Key antwortet)
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Gecachter Gemini-Client. Wirft, wenn GEMINI_API_KEY fehlt."""
    # api_key explizit, damit ein evtl. gesetztes GOOGLE_API_KEY nicht gewinnt.
    # SDK-Retries nur für Transportfehler (Timeout, Verbindungsabbruch) und 408.
    # 5xx, Fallback-Modell und 429 behandelt generate() selbst.
    return genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
        http_options=types.HttpOptions(
            timeout=max(config.GEMINI_TIMEOUT_MS, config.GEMINI_MIN_SERVER_DEADLINE_MS),
            retry_options=types.HttpRetryOptions(
                attempts=config.GEMINI_TRANSPORT_ATTEMPTS,
                initial_delay=2.0,
                max_delay=8.0,
                http_status_codes=[408],
            ),
        ),
    )


def backoff_delay(attempt: int) -> float:
    """Wartezeit nach dem Fehlversuch Nr. `attempt` (ab 0): exponentiell, mit Jitter."""
    ceiling = min(
        config.GEMINI_RETRY_MAX_DELAY, config.GEMINI_RETRY_BASE_DELAY * 2**attempt
    )
    return ceiling * random.uniform(0.5, 1.0)


# --------------------------------------------------------------------------
# Budget und Modus
# --------------------------------------------------------------------------
class Budget:
    """Hartes Request-Budget pro Prozess: GENAI_MAX_CALLS_PER_MIN und _TOTAL."""

    def __init__(self) -> None:
        """Leeres Budget anlegen."""
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Zähler auf 0 (Tests, Neustart)."""
        with self._lock:
            self.total = 0
            self._recent: deque[float] = deque()

    def acquire(self) -> str | None:
        """Einen Request reservieren. None = erlaubt, sonst der Grund der Ablehnung."""
        now = time.monotonic()
        with self._lock:
            while self._recent and now - self._recent[0] >= 60:
                self._recent.popleft()
            if self.total >= config.GENAI_MAX_CALLS_TOTAL:
                return f"GENAI_MAX_CALLS_TOTAL={config.GENAI_MAX_CALLS_TOTAL} erreicht"
            if len(self._recent) >= config.GENAI_MAX_CALLS_PER_MIN:
                return (
                    f"GENAI_MAX_CALLS_PER_MIN={config.GENAI_MAX_CALLS_PER_MIN} erreicht"
                )
            self.total += 1
            self._recent.append(now)
            return None


BUDGET = Budget()


def live_enabled() -> bool:
    """True, wenn Spiel-Agenten Gemini aufrufen dürfen (AGENTS_MODE=live)."""
    return config.AGENTS_MODE == "live"


def server_deadline_ms(timeout_ms: int | None) -> int | None:
    """Deadline, die an Gemini geht: nie unter GEMINI_MIN_SERVER_DEADLINE_MS.

    Die API lehnt kürzere Deadlines mit 400 "Minimum allowed deadline is 10s" ab.
    Kürzere Spiel-Deadlines setzt agenerate() lokal durch.
    """
    if timeout_ms is None:
        return None
    return max(config.GEMINI_MIN_SERVER_DEADLINE_MS, timeout_ms)


def _with_timeout(
    gen_config: types.GenerateContentConfig | None, timeout_ms: int | None
) -> types.GenerateContentConfig | None:
    """Server-Deadline pro Request setzen. Das SDK schickt sie als X-Server-Timeout."""
    deadline = server_deadline_ms(timeout_ms)
    if deadline is None:
        return gen_config
    options = types.HttpOptions(timeout=deadline)
    if gen_config is None:
        return types.GenerateContentConfig(http_options=options)
    return gen_config.model_copy(update={"http_options": options})


# --------------------------------------------------------------------------
# Aufruf
# --------------------------------------------------------------------------
def generate(
    contents,
    model: str,
    gen_config: types.GenerateContentConfig | None = None,
    *,
    agent: str = "starter",
    attempts: int | None = None,
    timeout_ms: int | None = None,
    use_fallback_model: bool = True,
) -> tuple[types.GenerateContentResponse, str]:
    """Ruft Gemini auf und gibt (Antwort, tatsächlich genutztes Modell) zurück.

    - agent: Name für Log und Overlay.
    - attempts: Versuche pro Modell (Default GEMINI_RETRY_ATTEMPTS), Backoff dazwischen.
    - timeout_ms: Deadline pro Request (Default GEMINI_TIMEOUT_MS des Clients). An Gemini
      geht max(GEMINI_MIN_SERVER_DEADLINE_MS, timeout_ms); kürzer nur lokal über agenerate().
    - use_fallback_model: False für Spiel-Agenten (Fallback-Modell ist zu langsam).

    Fehler (alle als HTTPException):
    - 500/502/503: Retry mit Backoff, danach GEMINI_MODEL_FALLBACK. Beide überlastet: 503.
    - 504 (Deadline): ohne Retry direkt zum Fallback-Modell.
    - 429: sofort 429 mit Spend-Cap-Hinweis. Kein Retry, kein Fallback.
    - andere Gemini-Fehler (400, 403, 404 ...): 502.
    - Budget erschöpft: 503 ohne Request.
    """
    try:
        client = get_client()
    except Exception as e:  # noqa: BLE001 - jede Client-Init-Panne -> 500 statt Crash
        raise HTTPException(
            500, f"Gemini-Client nicht verfügbar (GEMINI_API_KEY gesetzt?): {e}"
        )

    attempts = max(1, attempts or config.GEMINI_RETRY_ATTEMPTS)
    gen_config = _with_timeout(gen_config, timeout_ms)
    models = [model]
    if use_fallback_model and config.GEMINI_MODEL_FALLBACK != model:
        models.append(config.GEMINI_MODEL_FALLBACK)

    last_error: errors.APIError | None = None
    for current in models:
        if current != model:
            log.warning("Gemini: %s überlastet, weiche auf %s aus", model, current)
        for attempt in range(attempts):
            if attempt:
                _sleep(backoff_delay(attempt - 1))
            refused = BUDGET.acquire()
            if refused:
                raise HTTPException(503, f"GenAI-Budget erschöpft: {refused}")
            started = time.perf_counter()

            def _log(response=None, error=None, _started=started, _model=current):
                genai_log.log_call(
                    agent=agent,
                    model=_model,
                    contents=contents,
                    gen_config=gen_config,
                    response=response,
                    error=error,
                    latency_ms=round((time.perf_counter() - _started) * 1000),
                )

            try:
                response = client.models.generate_content(
                    model=current, contents=contents, config=gen_config
                )
            except errors.APIError as e:
                _log(error=e)
                if e.code == 429:
                    raise HTTPException(
                        429,
                        f"Gemini 429 bei {current}: {config.SPEND_CAP_HINT} ({e.message})",
                    ) from e
                if e.code not in config.RETRYABLE_STATUS:
                    raise HTTPException(
                        502, f"Gemini-Fehler {e.code} bei {current}: {e.message}"
                    ) from e
                last_error = e
                log.warning(
                    "Gemini %s bei %s (Versuch %d/%d): %s",
                    e.code,
                    current,
                    attempt + 1,
                    attempts,
                    e.message,
                )
                if e.code in config.FALLBACK_IMMEDIATELY_STATUS:
                    break  # gleiche Deadline am gleichen Modell hilft nicht
            except Exception as e:
                _log(
                    error=e
                )  # Transportfehler (Timeout, Verbindung): loggen, weiterreichen
                raise
            else:
                _log(response=response)
                return response, current

    raise HTTPException(
        503,
        f"Gemini überlastet ({' -> '.join(models)}), "
        f"zuletzt {last_error.code}: {last_error.message}",
    )


async def agenerate(
    *args, timeout_ms: int | None = None, **kwargs
) -> tuple[types.GenerateContentResponse, str]:
    """generate() im Thread-Pool, damit der Event-Loop (Spiel, WebSocket) nie blockiert.

    timeout_ms ist die Spiel-Deadline und wird hier lokal durchgesetzt (asyncio). An Gemini
    geht mindestens GEMINI_MIN_SERVER_DEADLINE_MS. Ist die lokale Deadline um, kommt sofort
    HTTPException 504, damit der Fallback greift; der Request läuft im Thread zu Ende,
    seine Logzeile erscheint später, das Ergebnis wird verworfen.
    """
    call = asyncio.to_thread(generate, *args, timeout_ms=timeout_ms, **kwargs)
    if timeout_ms is None:
        return await call
    try:
        return await asyncio.wait_for(call, timeout_ms / 1000)
    except asyncio.TimeoutError:
        raise HTTPException(
            504,
            f"Lokale Spiel-Deadline {timeout_ms} ms überschritten "
            f"(Server-Deadline {server_deadline_ms(timeout_ms)} ms)",
        ) from None
