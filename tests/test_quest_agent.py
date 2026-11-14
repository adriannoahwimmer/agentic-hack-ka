"""Tests für agents/quest.py: POST /npc/talk mit Fake-Gemini, Fallbacks, Deadline, 404."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import config
import gemini
import main
import quests
from agents import quest as quest_agent
from tests.fakes import api_error, call_response, text_response

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh_book(monkeypatch, fresh_hub):
    """Eigenes QuestBook und leeres NPC-Gedächtnis pro Test."""
    book = quests.QuestBook()
    monkeypatch.setattr(quests, "BOOK", book)
    monkeypatch.setattr(quest_agent, "MEMORY", {})
    return book


@pytest.fixture
def live(monkeypatch):
    """AGENTS_MODE=live (nur mit fake_gemini verwenden)."""
    monkeypatch.setattr(config, "AGENTS_MODE", "live")


def _talk(**body):
    return client.post("/npc/talk", json={"npc_id": "fixer_karl", **body})


ASSIGN = {
    "place_id": "marktplatz",
    "title": "Pyramid Trouble",
    "objective": "Go to Market Square and take out 3 thugs",
    "enemies": 3,
    "npc_line": "Thugs at the Pyramid. Clear them out.",
    "reason": "Player asked for work",
}


def test_loop_lookup_then_assign_gives_quest_in_two_calls(fake_gemini, live):
    fake = fake_gemini(
        [
            call_response(("lookup_place", {"place_id": "marktplatz", "reason": "r"})),
            call_response(("assign_quest", ASSIGN)),
        ]
    )
    r = _talk(player_text="Got any work?")
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is False
    assert body["text"] == ASSIGN["npc_line"]
    assert body["quest"]["poi_id"] == "marktplatz" and body["quest"]["remaining"] == 3
    assert len(fake.models.calls) == 2
    # Zweiter Request: Modell-Turn unverändert + FunctionResponse mit id
    second = fake.models.calls[1]["contents"]
    assert second[1].parts[0].function_call.name == "lookup_place"
    fr = second[2].parts[0].function_response
    assert fr.id == "call-0" and fr.response["name"] == "Market Square"
    assert quests.BOOK.active.poi.id == "marktplatz"


def test_wrong_place_id_is_retried_in_loop(fake_gemini, live):
    fake = fake_gemini(
        [
            call_response(("assign_quest", {**ASSIGN, "place_id": "mars"})),
            call_response(("assign_quest", ASSIGN)),
        ]
    )
    body = _talk().json()
    assert body["fallback"] is False and body["quest"]["poi_id"] == "marktplatz"
    err = fake.models.calls[1]["contents"][2].parts[0].function_response.response
    assert "unknown place_id" in err["error"]


@pytest.mark.parametrize("error", [api_error(503), api_error(429), api_error(400)])
def test_any_gemini_error_gives_200_fallback(fake_gemini, live, error):
    fake_gemini([error])
    r = _talk()
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True and body["model"] is None
    assert body["quest"]["status"] == "active"


def test_deadline_gives_fallback_with_200(monkeypatch, live):
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(gemini, "agenerate", slow)
    monkeypatch.setattr(config, "QUEST_DEADLINE_MS", 50)
    r = _talk()
    assert r.status_code == 200 and r.json()["fallback"] is True


def test_steps_exhausted_gives_fallback(fake_gemini, live):
    lookup = call_response(("lookup_place", {"place_id": "marktplatz", "reason": "r"}))
    fake = fake_gemini([lookup] * config.QUEST_MAX_STEPS)
    body = _talk().json()
    assert body["fallback"] is True
    assert len(fake.models.calls) == config.QUEST_MAX_STEPS


def test_offline_makes_no_request_and_logs_fallback(fake_gemini, genai_log_lines):
    fake = fake_gemini([])
    body = _talk().json()
    assert body["fallback"] is True and body["quest"] is not None
    assert fake.models.calls == []
    lines = genai_log_lines()
    assert lines[-1]["kind"] == "fallback" and lines[-1]["agent"] == "quest"


def test_active_quest_is_reminded_not_replaced():
    first = _talk().json()["quest"]
    second = _talk(player_text="More work?").json()
    assert second["quest"]["quest_id"] == first["quest_id"]
    assert "still owe" in second["text"]


def test_text_only_answer_has_no_new_quest(fake_gemini, live):
    fake_gemini([text_response("Not now, kid.")])
    body = _talk(player_text="How are you?").json()
    assert body == {
        "npc_id": "fixer_karl",
        "text": "Not now, kid.",
        "quest": None,
        "sources": [],
        "model": config.GEMINI_MODEL_QUEST,
        "fallback": False,
    }


def test_unknown_npc_is_404_and_bad_body_422():
    assert client.post("/npc/talk", json={"npc_id": "nobody"}).status_code == 404
    assert client.post("/npc/talk", json={"player_text": "x"}).status_code == 422


def test_new_quest_is_broadcast_as_quest_update(fresh_hub):
    sent = []

    class _C:
        async def send_text(self, text):
            sent.append(text)

    fresh_hub.add_client(_C())
    _talk()
    assert len(sent) == 1 and '"quest_update"' in sent[0]
