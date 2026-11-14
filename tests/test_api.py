from fastapi.testclient import TestClient

import config
import main
from tests.fakes import api_error, call_response, text_response

client = TestClient(main.app)


def test_health_without_key():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "models": {
            "agent": config.GEMINI_MODEL_AGENT,
            "chat": config.GEMINI_MODEL_CHAT,
            "fallback": config.GEMINI_MODEL_FALLBACK,
        },
        "gemini_key_configured": False,
    }


def test_health_with_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    assert client.get("/").json()["gemini_key_configured"] is True


def test_chat_returns_answer(fake_gemini):
    fake = fake_gemini([text_response("Hallo!")])
    r = client.get("/chat", params={"q": "Sag Hallo"})
    assert r.status_code == 200
    assert r.json() == {"answer": "Hallo!", "model": config.GEMINI_MODEL_CHAT}
    assert fake.called_models == [config.GEMINI_MODEL_CHAT]


def test_chat_requires_q():
    assert client.get("/chat").status_code == 422


def test_chat_without_client_is_500():
    # get_client nicht gemockt -> echter Client blockiert (conftest) -> 500
    r = client.get("/chat", params={"q": "x"})
    assert r.status_code == 500
    assert "GEMINI_API_KEY" in r.json()["detail"]


def test_chat_maps_client_error_to_502_without_retry(fake_gemini, backoff_sleeps):
    fake = fake_gemini([api_error(400, "bad request")])
    r = client.get("/chat", params={"q": "x"})
    assert r.status_code == 502
    assert "400" in r.json()["detail"]
    assert len(fake.models.calls) == 1
    assert backoff_sleeps == []


def test_agent_answers_without_tools(fake_gemini):
    fake = fake_gemini([text_response("Blau.")])
    r = client.get("/agent", params={"q": "Nenne eine Farbe"})
    assert r.json() == {
        "answer": "Blau.",
        "model": config.GEMINI_MODEL_AGENT,
        "steps": [],
    }
    assert fake.called_models == [config.GEMINI_MODEL_AGENT]


def test_agent_runs_tool_loop(fake_gemini):
    fake = fake_gemini(
        [
            call_response(("calculator", {"expression": "6 * 7"}), ("get_time", {})),
            text_response("42, und es ist spät."),
        ]
    )
    r = client.get("/agent", params={"q": "Was ist 6*7 und wie spät ist es?"})

    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "42, und es ist spät."
    assert [s["tool"] for s in body["steps"]] == ["calculator", "get_time"]
    assert body["steps"][0]["result"]["result"] == 42

    # 2. Request: user-Frage, Modell-Turn (unverändert), Tool-Ergebnisse mit passenden IDs
    second = fake.models.calls[1]["contents"]
    assert [c.role for c in second] == ["user", "model", "user"]
    responses = [p.function_response for p in second[2].parts]
    assert [(fr.id, fr.name) for fr in responses] == [
        ("call-0", "calculator"),
        ("call-1", "get_time"),
    ]
    assert responses[0].response["result"] == 42


def test_agent_stops_at_step_limit(fake_gemini):
    fake_gemini([call_response(("get_time", {}))] * config.MAX_AGENT_STEPS)
    r = client.get("/agent", params={"q": "Endlosschleife"})
    assert r.status_code == 500
    assert "Limit" in r.json()["detail"]
