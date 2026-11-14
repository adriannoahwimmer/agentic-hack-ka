"""Tests für die Browser-Test-Fixes (Endspurt).

Zweck: sichert zwei Bugs aus dem Browser-Test ab.
Use-Cases:
- Polizeifunk auf player_radio erfindet keine Delikte (Prompt-Regel, Fallback-Antwort)
- Quest-Ziele sind nie Behörden/Gerichte (Prompt, Server-Prüfung, Fallback-Quests)
"""

import random

import pytest

import quests
from agents import police, quest
from tests.test_wanted_rules import _snap


def test_police_prompt_forbids_invented_crimes():
    """Der Systemprompt verlangt: nur Delikte aus recent_events, auf die Provokation reagieren."""
    assert "recent_events" in police.SYSTEM_PROMPT
    assert "do not invent" in police.SYSTEM_PROMPT
    assert "reacts to the taunt or excuse" in police.SYSTEM_PROMPT


@pytest.mark.parametrize("tone", ["taunt", "plead"])
def test_fallback_radio_reply_without_crime_names_no_crime(tone):
    """Taunt/Plead bei 0 Sternen ohne Delikt: Standardantwort ohne Schüsse/Diebstahl."""
    snap = _snap(level=0, floor=0, crime_s=None, radio={"tone": tone, "text": "Hey"})
    out = police.clamp(police.fallback(snap), snap)
    radio = [e for e in out if e.type == "radio_message"]
    assert radio, "player_radio braucht immer eine Funkantwort"
    text = radio[-1].payload["text"].lower()
    for word in ("schuss", "schüsse", "diebstahl", "gestohlen", "tote"):
        assert word not in text


def test_court_is_never_a_quest_target():
    """verfassungsgericht ist kein mission-POI mehr, create lehnt es ab, lookup_place auch."""
    ids = {p.id for p in quests.mission_pois()}
    assert "verfassungsgericht" not in ids and ids
    with pytest.raises(quests.QuestError):
        quests.QuestBook().create(
            "verfassungsgericht", "Rowdy judges", "Shoot judges", 3
        )
    assert "error" in quest.lookup_place("verfassungsgericht")


def test_fallback_quests_avoid_authorities_and_name_a_gang():
    """Fallback-Quests nie bei Behörden, Gegner sind eine Schmuggler-Crew."""
    rng = random.Random(1)
    for _ in range(200):
        args = quests.fallback_quest(rng=rng)
        assert args["poi_id"] not in quests.NO_QUEST_POIS
        assert "smugglers" in args["objective"]


def test_quest_prompt_says_enemies_are_a_gang():
    """Der Quest-Systemprompt legt Gegner auf Gang/Schmuggler fest, nie Richter/Beamte."""
    npc = next(iter(quest.load_npcs().values()))
    system = quest.agent_config(npc).system_instruction
    assert "rival gang" in system and "judges" in system
    assert "verfassungsgericht" not in system
