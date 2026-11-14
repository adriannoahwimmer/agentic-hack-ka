"""Tests des JSONL-Logs (genai_log.py): eine Zeile pro Versuch, Format nach Vertrag,
Platzhalter statt Binärdaten, keine Secrets, Listener fürs Overlay. Nie live.
"""

import pytest
from google.genai import types

import config
import gemini
import genai_log
from protocol import GenaiLogLine
from tests.fakes import (
    api_error,
    audio_response,
    call_response,
    grounded_response,
    text_response,
)

MODEL = "primary-test"


def test_one_line_per_attempt_with_reason(fake_gemini, genai_log_lines):
    fake_gemini(
        [
            api_error(503, "high demand"),
            call_response(("set_wanted_level", {"level": 2, "reason": "Shots fired"})),
        ]
    )
    gemini.generate("snapshot", MODEL, agent="police")

    first, second = genai_log_lines()
    for line in (first, second):
        GenaiLogLine.model_validate(line)
        assert line["agent"] == "police"
        assert line["kind"] == "genai"
        assert line["model"] == MODEL
    assert first["status"] == "error"
    assert first["error"] == {"code": 503, "message": "high demand"}
    assert second["status"] == "ok"
    assert second["output"]["calls"] == [
        {"tool": "set_wanted_level", "args": {"level": 2, "reason": "Shots fired"}}
    ]
    assert second["reason"] == "Shots fired"
    assert second["call_no"] > first["call_no"]
    assert second["prompt"] == "snapshot"


def test_config_is_summarized(fake_gemini, genai_log_lines):
    fake_gemini([text_response("ok")])
    gen_config = types.GenerateContentConfig(
        system_instruction="abcdef",
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(name="spawn_units"),
                    types.FunctionDeclaration(name="radio_message"),
                ]
            )
        ],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="ANY")
        ),
        thinking_config=types.ThinkingConfig(thinking_level="low"),
    )
    gemini.generate("x", MODEL, gen_config)
    [line] = genai_log_lines()
    assert line["config"] == {
        "tools": ["spawn_units", "radio_message"],
        "tool_mode": "any",
        "thinking_level": "low",
        "system_instruction_chars": 6,
        "response_modalities": None,
    }


def test_inline_data_only_as_placeholder(fake_gemini, genai_log_lines):
    audio = b"RIFF" + b"\x00" * 96
    fake_gemini([audio_response(audio, "audio/wav")])
    image = types.Part(inline_data=types.Blob(data=b"\x89PNG", mime_type="image/png"))
    gemini.generate([types.Content(role="user", parts=[image])], MODEL, agent="tts")

    [line] = genai_log_lines()
    assert line["output"]["inline"] == [{"mime": "audio/wav", "bytes": 100}]
    assert "<inline_data mime=image/png bytes=4>" in line["prompt"]
    raw = config.GENAI_LOG_PATH.read_text(encoding="utf-8")
    assert "RIFF" not in raw and "PNG" not in raw


def test_grounding_sources_are_logged(fake_gemini, genai_log_lines):
    fake_gemini(
        [grounded_response("Built 1715.", [("Schloss", "https://maps.example/1")])]
    )
    gemini.generate("fact", MODEL, agent="maps")
    [line] = genai_log_lines()
    assert line["output"]["text"] == "Built 1715."
    assert line["output"]["sources"] == [
        {"title": "Schloss", "uri": "https://maps.example/1"}
    ]


def test_prompt_is_truncated(fake_gemini, genai_log_lines, monkeypatch):
    monkeypatch.setattr(config, "GENAI_LOG_MAX_PROMPT_CHARS", 100)
    fake_gemini([text_response("ok")])
    gemini.generate("x" * 500, MODEL)
    [line] = genai_log_lines()
    assert line["prompt"].startswith("x" * 100)
    assert "gekürzt, 500 Zeichen" in line["prompt"]
    assert len(line["prompt"]) < 150


def test_api_key_never_in_log(fake_gemini, monkeypatch):
    secret = "dummy-secret-key-for-log-test-123"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    fake_gemini([api_error(400, "bad"), text_response("ok")])
    with pytest.raises(Exception):  # noqa: B017 - 400 -> HTTPException 502
        gemini.generate("x", MODEL)
    gemini.generate("x", MODEL)
    assert secret not in config.GENAI_LOG_PATH.read_text(encoding="utf-8")


def test_listener_gets_line_and_errors_are_isolated(fake_gemini):
    seen = []
    genai_log.add_listener(lambda line: (_ for _ in ()).throw(RuntimeError("kaputt")))
    remove = genai_log.add_listener(seen.append)
    fake_gemini([text_response("ok"), text_response("ok")])

    gemini.generate("x", MODEL, agent="quest")
    assert [line.agent for line in seen] == ["quest"]

    remove()
    gemini.generate("x", MODEL)
    assert len(seen) == 1


def test_log_fallback(genai_log_lines):
    line = genai_log.log_fallback(
        agent="police",
        actions=[{"tool": "set_wanted_level", "args": {"level": 1, "reason": "rules"}}],
    )
    assert line.kind == "fallback"
    assert line.model is None
    assert line.call_no is None
    assert line.reason == "rules"
    assert genai_log_lines()[0]["kind"] == "fallback"
    assert "prompt" not in line.to_agent_log().model_dump()


def test_unwritable_log_does_not_break_calls(fake_gemini, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GENAI_LOG_PATH", tmp_path)  # Verzeichnis, nicht Datei
    seen = []
    genai_log.add_listener(seen.append)
    fake_gemini([text_response("ok")])
    response, _ = gemini.generate("x", MODEL)
    assert response.text == "ok"
    assert len(seen) == 1
