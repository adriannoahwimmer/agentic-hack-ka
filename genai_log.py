"""JSONL-Log aller GenAI-Calls (logs/genai.jsonl) und Quelle für das Agent-Log-Overlay.

Zweck: Jeder GenAI-Request (pro tatsächlichem Versuch) und jede Fallback-Entscheidung
wird als eine Zeile im Format protocol.GenaiLogLine geschrieben (Design.md, "Vertrag",
JSONL-Log). Listener (hub.py) schicken jede Zeile als agent_log an die Browser.
Use-Cases: Overlay im Spiel, Request-Zählung (Budget-Kontrolle), Debugging von Prompts.

Regeln: Inline-Daten nur als Platzhalter {mime, bytes}, Prompt gekürzt, nie Keys,
Tokens oder Header. Schreib- und Listener-Fehler werden geloggt, nie weitergereicht.
Thread-sicher: generate() läuft oft in einem Worker-Thread.
"""

import itertools
import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from google.genai import types

import config
from protocol import (
    ErrorInfo,
    GenaiLogLine,
    InlinePlaceholder,
    LogConfig,
    LogOutput,
    Source,
    ToolCall,
)

log = logging.getLogger(__name__)

Listener = Callable[[GenaiLogLine], None]

_write_lock = threading.Lock()
_listeners: list[Listener] = []
_call_numbers = itertools.count(1)


def add_listener(fn: Listener) -> Callable[[], None]:
    """Listener für neue Logzeilen registrieren. Gibt eine Abmeldefunktion zurück."""
    _listeners.append(fn)

    def remove() -> None:
        if fn in _listeners:
            _listeners.remove(fn)

    return remove


def clear_listeners() -> None:
    """Alle Listener entfernen (Tests)."""
    _listeners.clear()


def _now_iso() -> str:
    """Aktuelle Zeit als ISO 8601 UTC mit Millisekunden und 'Z'."""
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return now.replace("+00:00", "Z")


def _truncate(text: str, limit: int) -> str:
    """Text auf limit Zeichen kürzen, mit Hinweis auf die Originallänge."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [gekürzt, {len(text)} Zeichen]"


def _describe_part(part: types.Part) -> str:
    """Einen Content-Part lesbar machen; Binärdaten nur als Platzhalter."""
    if part.text is not None:
        return part.text
    if part.function_call is not None:
        fc = part.function_call
        return f"<function_call {fc.name} {json.dumps(fc.args or {}, ensure_ascii=False, default=str)}>"
    if part.function_response is not None:
        fr = part.function_response
        return f"<function_response {fr.name} {json.dumps(fr.response or {}, ensure_ascii=False, default=str)}>"
    if part.inline_data is not None:
        data = part.inline_data.data or b""
        return f"<inline_data mime={part.inline_data.mime_type} bytes={len(data)}>"
    if part.file_data is not None:
        return (
            f"<file_data mime={part.file_data.mime_type} uri={part.file_data.file_uri}>"
        )
    return "<part>"


def summarize_contents(contents: Any) -> str:
    """contents (str, Part, Content oder Liste davon) als gekürzter Text fürs Log."""
    items = contents if isinstance(contents, list) else [contents]
    lines = []
    for item in items:
        if isinstance(item, str):
            lines.append(item)
        elif isinstance(item, types.Content):
            body = " ".join(_describe_part(p) for p in item.parts or [])
            lines.append(f"[{item.role}] {body}")
        elif isinstance(item, types.Part):
            lines.append(_describe_part(item))
        else:
            lines.append(str(item))
    return _truncate("\n".join(lines), config.GENAI_LOG_MAX_PROMPT_CHARS)


def _enum_value(value: Any) -> str | None:
    """Enum oder String als kleingeschriebener String, None bleibt None."""
    if value is None:
        return None
    return str(getattr(value, "value", value)).lower()


def summarize_config(
    gen_config: types.GenerateContentConfig | None,
) -> LogConfig | None:
    """GenerateContentConfig zusammenfassen: Tool-Namen, Modus, Thinking, Länge des Systemprompts."""
    if gen_config is None:
        return None
    tools: list[str] = []
    for tool in gen_config.tools or []:
        if isinstance(tool, types.Tool):
            tools += [fd.name for fd in tool.function_declarations or []]
            tools += [
                name
                for name in (
                    "google_maps",
                    "google_search",
                    "code_execution",
                    "url_context",
                )
                if getattr(tool, name, None) is not None
            ]
        else:
            tools.append(getattr(tool, "__name__", type(tool).__name__))
    tool_mode = None
    if gen_config.tool_config and gen_config.tool_config.function_calling_config:
        tool_mode = _enum_value(gen_config.tool_config.function_calling_config.mode)
    thinking = (
        gen_config.thinking_config.thinking_level
        if gen_config.thinking_config
        else None
    )
    instruction = gen_config.system_instruction
    if isinstance(instruction, types.Content):
        instruction_chars = sum(len(p.text or "") for p in instruction.parts or [])
    else:
        instruction_chars = len(str(instruction)) if instruction else 0
    modalities = gen_config.response_modalities
    return LogConfig(
        tools=tools,
        tool_mode=tool_mode,
        thinking_level=_enum_value(thinking),
        system_instruction_chars=instruction_chars,
        response_modalities=[_enum_value(m) for m in modalities]
        if modalities
        else None,
    )


def summarize_output(response: types.GenerateContentResponse | None) -> LogOutput:
    """Antwort zusammenfassen: Text, Function-Calls, Inline-Platzhalter, Grounding-Quellen."""
    if response is None or not response.candidates:
        return LogOutput()
    candidate = response.candidates[0]
    texts: list[str] = []
    calls: list[ToolCall] = []
    inline: list[InlinePlaceholder] = []
    for part in (candidate.content.parts if candidate.content else None) or []:
        if part.thought:
            continue
        if part.text is not None:
            texts.append(part.text)
        elif part.function_call is not None:
            calls.append(
                ToolCall(
                    tool=part.function_call.name or "?",
                    args=dict(part.function_call.args or {}),
                )
            )
        elif part.inline_data is not None:
            data = part.inline_data.data or b""
            inline.append(
                InlinePlaceholder(
                    mime=part.inline_data.mime_type or "?", bytes=len(data)
                )
            )
    sources: list[Source] = []
    metadata = candidate.grounding_metadata
    for chunk in (metadata.grounding_chunks if metadata else None) or []:
        ref = chunk.maps or chunk.web
        if ref is not None and ref.uri:
            sources.append(Source(title=ref.title or ref.uri, uri=ref.uri))
    text = "".join(texts) or None
    return LogOutput(
        text=_truncate(text, config.GENAI_LOG_MAX_PROMPT_CHARS) if text else None,
        calls=calls,
        inline=inline,
        sources=sources,
    )


def _first_reason(calls: list[ToolCall]) -> str | None:
    """Begründungszeile: args.reason des ersten Calls, der eine hat."""
    for call in calls:
        reason = call.args.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
    return None


def _error_info(error: BaseException) -> ErrorInfo:
    """Fehler als {code, message}: HTTP-Code bei Gemini-Fehlern, sonst Typname."""
    code = getattr(error, "code", None)
    message = getattr(error, "message", None) or str(error)
    return ErrorInfo(
        code=code if isinstance(code, int | str) else type(error).__name__,
        message=str(message)[:500],
    )


def _emit(line: GenaiLogLine) -> GenaiLogLine:
    """Zeile anhängen (JSONL) und an alle Listener geben."""
    path = config.GENAI_LOG_PATH
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line.model_dump_json() + "\n")
    except OSError:
        log.exception("GenAI-Log nicht schreibbar: %s", path)
    listeners = _listeners.copy()  # Kopie: Listener dürfen sich beim Aufruf abmelden
    for fn in listeners:
        try:
            fn(line)
        except Exception:  # ein kaputter Listener darf den GenAI-Call nicht stören
            log.exception("GenAI-Log-Listener fehlgeschlagen")
    return line


def log_call(
    *,
    agent: str,
    model: str,
    contents: Any,
    gen_config: types.GenerateContentConfig | None,
    response: types.GenerateContentResponse | None = None,
    error: BaseException | None = None,
    latency_ms: int,
) -> GenaiLogLine:
    """Einen GenAI-Request (einen Versuch) loggen. Wird von gemini.generate() aufgerufen."""
    output = summarize_output(response)
    return _emit(
        GenaiLogLine(
            ts=_now_iso(),
            call_no=next(_call_numbers),
            kind="genai",
            agent=agent,
            model=model,
            status="error" if error is not None else "ok",
            error=_error_info(error) if error is not None else None,
            latency_ms=max(0, latency_ms),
            output=output,
            reason=_first_reason(output.calls),
            prompt=summarize_contents(contents),
            config=summarize_config(gen_config),
        )
    )


def log_fallback(
    *, agent: str, actions: list[ToolCall | dict], reason: str | None = None
) -> GenaiLogLine:
    """Eine geskriptete Fallback-Entscheidung loggen (kein GenAI-Request, model=None)."""
    calls = [
        a if isinstance(a, ToolCall) else ToolCall.model_validate(a) for a in actions
    ]
    return _emit(
        GenaiLogLine(
            ts=_now_iso(),
            kind="fallback",
            agent=agent,
            model=None,
            status="ok",
            output=LogOutput(calls=calls),
            reason=reason or _first_reason(calls),
        )
    )
