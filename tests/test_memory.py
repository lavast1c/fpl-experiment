"""Memory: checking the memory part of an answer, updating memory, and checking lessons.

The last tests run the weekly runner with the mock agent over several gameweeks,
writing to a temporary folder instead of data/mock.
"""

import gzip
import json

import pytest

from experiment import config, memory, runner
from experiment.agents import MockAgent
from experiment.files import read_json
from experiment.teams import TEAMS

CODES = lambda errors: [e.code for e in errors]


def verified_with(*texts):
    """Verified memory holding active lessons L1, L2, ... with the given texts."""
    mem = memory.empty_memory("verified")
    return memory.apply_answer("verified", {"lessons": {"keep": [], "new": list(texts)}, "captain": 1,
                                            "captain_lesson_ids": []}, mem, gw=1, expected={})


# --- checking answers --------------------------------------------------------------------------

def test_self_notes_within_limits_are_fine():
    assert memory.check_answer("self", {"updated_notes": ["a note", "another"]}, memory.empty_memory("self")) == []


def test_self_notes_too_many_or_too_long_are_rule_breaks():
    mem = memory.empty_memory("self")
    too_many = {"updated_notes": ["x"] * (config.MEMORY_MAX_LESSONS + 1)}
    too_long = {"updated_notes": [" ".join(["word"] * (config.MEMORY_MAX_WORDS + 1))]}
    assert CODES(memory.check_answer("self", too_many, mem)) == ["MEMORY_TOO_MANY"]
    assert CODES(memory.check_answer("self", too_long, mem)) == ["MEMORY_TOO_LONG"]
    assert CODES(memory.check_answer("self", {"updated_notes": "not a list"}, mem)) == ["MEMORY_FORMAT"]


def test_verified_unknown_lessons_are_rule_breaks():
    mem = verified_with("buy form", "avoid injured")
    answer = {"lessons": {"keep": ["L1", "L7"], "new": []}, "captain_lesson_ids": ["L9"],
              "transfers": [{"out": 1, "in": 2, "out_lesson_ids": ["L2"], "in_lesson_ids": []}]}
    assert CODES(memory.check_answer("verified", answer, mem)) == ["LESSON_UNKNOWN", "LESSON_CITATION_UNKNOWN"]


def test_verified_length_counts_kept_and_new_lessons_together():
    mem = verified_with(" ".join(["word"] * 200))
    answer = {"lessons": {"keep": ["L1"], "new": [" ".join(["word"] * 101)]}, "captain_lesson_ids": []}
    assert CODES(memory.check_answer("verified", answer, mem)) == ["MEMORY_TOO_LONG"]


# --- updating memory -------------------------------------------------------------------------

def test_apply_answer_keeps_drops_adds_and_records_citations():
    mem = verified_with("buy form", "avoid injured")
    answer = {"lessons": {"keep": ["L1"], "new": ["captain at home"]}, "captain": 5, "captain_lesson_ids": ["L1"],
              "transfers": [{"out": 3, "in": 4, "out_lesson_ids": ["L2"], "in_lesson_ids": ["L1"]}]}
    new = memory.apply_answer("verified", answer, mem, gw=2, expected={3: 4.0, 4: 5.5, 5: 6.0})
    assert [(l["id"], l["status"]) for l in new["lessons"]] == [("L1", "active"), ("L2", "dropped_by_agent"),
                                                                ("L3", "active")]
    assert [(p["lesson"], p["decision"], p["player"], p["expected"]) for p in new["pending"]] == [
        ("L2", "sold", 3, 4.0), ("L1", "bought", 4, 5.5), ("L1", "captain", 5, 6.0)]
    assert mem["lessons"][1]["status"] == "active"   # the old memory is not changed


# --- checking lessons after the gameweek ---------------------------------------------------------

def test_values_for_bought_sold_and_captain():
    mem = verified_with("lesson")
    mem["pending"] = [{"gw": 2, "lesson": "L1", "decision": d, "player": p, "expected": 5.0}
                      for d, p in [("bought", 1), ("sold", 2), ("captain", 3)]]
    new = memory.evaluate(mem, 2, points={1: 8, 2: 1, 3: 2})
    assert [u["value"] for u in new["lessons"][0]["uses"]] == [3.0, 4.0, -3.0]   # 8-5, 5-1, 2-5
    assert new["pending"] == []


def test_lesson_removed_only_after_enough_bad_uses(tmp_path):
    mem = verified_with("bad lesson")
    use = {"gw": 2, "lesson": "L1", "decision": "bought", "player": 1, "expected": 5.0}
    mem["pending"] = [use] * (config.LESSON_MIN_USES - 1)
    mem = memory.evaluate(mem, 2, points={1: 0})          # 4 uses averaging -5: kept for now
    assert memory.active_lessons(mem) and mem["removed_notices"] == []
    mem["pending"] = [{**use, "gw": 3}]
    mem = memory.evaluate(mem, 3, points={1: 0}, csv_path=tmp_path / "e.csv")   # 5th use: removed
    assert memory.active_lessons(mem) == [] and mem["lessons"][0]["status"] == "removed"
    assert "L1" in mem["removed_notices"][0] and "5 decisions" in mem["removed_notices"][0]
    assert (tmp_path / "e.csv").exists()


def test_lesson_with_good_average_is_kept():
    mem = verified_with("good lesson")
    mem["pending"] = [{"gw": 2, "lesson": "L1", "decision": "captain", "player": 1, "expected": 5.0}] * 6
    assert memory.active_lessons(memory.evaluate(mem, 2, points={1: 9}))


def test_memory_section_shows_track_record_and_removals():
    mem = verified_with("buy form", "never used")
    mem["lessons"][0]["uses"] = [{"value": 2.0}, {"value": -1.0}]
    mem["removed_notices"] = ["L9 was removed."]
    last = {"gw": 7, "net_points": 50, "points": 54, "hit_points": 4, "average": 48, "chip": None,
            "transfers": [], "players": [{"name": "Keeper", "points": 3, "role": "starter"}],
            "auto_subs_detail": ["A off, B on"]}
    text = memory.memory_section("verified", mem, last)
    assert "used 2 time(s), average +0.5" in text and "L2: never used [not used yet]" in text
    assert "L9 was removed." in text and "average FPL manager scored 48" in text
    assert "minus a 4-point transfer cost" in text and "A off, B on" in text
    assert memory.REMINDER in text


# --- several mock gameweeks through the runner ---------------------------------------------------

@pytest.fixture
def mock_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MOCK_DIR", tmp_path)
    return tmp_path


def team(team_id):
    return next(t for t in TEAMS if t.id == team_id)


def prompt(base, gw, team_id):
    with gzip.open(base / "logs" / f"gw{gw}" / team_id / "prompt.txt.gz", "rt", encoding="utf-8") as f:
        return json.load(f)["prompt"]


def test_memory_teams_over_several_gameweeks(mock_folder, monkeypatch):
    monkeypatch.setattr(runner, "MockAgent", lambda model, seed: MockAgent(model, seed, illegal_rate=0, chip_rate=0))
    teams = [team("H-self"), team("H-verified")]
    for gw in (8, 9, 10):
        runner.decide(gw, mock=True, teams=teams)
        runner.score_gameweek(gw, mock=True)

    assert "none yet (this is your first gameweek)" in prompt(mock_folder, 8, "H-self")
    assert "Last gameweek (gameweek 9)" in prompt(mock_folder, 10, "H-self")
    notes = read_json(mock_folder / "memory" / "H-self" / "gw9.json")["notes"]
    assert all(f"- {n}" in prompt(mock_folder, 10, "H-self") for n in notes)   # its own notes come back

    verified = read_json(mock_folder / "memory" / "H-verified" / "latest.json")
    assert verified["pending"] == []   # every cited decision has been checked
    assert '"captain_lesson_ids"' in json.dumps(read_json(mock_folder / "decisions" / "gw10" / "H-verified.json"))


def test_removal_notice_reaches_next_prompt(mock_folder, monkeypatch):
    monkeypatch.setattr(runner, "MockAgent", lambda model, seed: MockAgent(model, seed, illegal_rate=0, chip_rate=0))
    t = team("H-verified")
    mem = verified_with("always captain the cheapest player")
    mem["lessons"][0]["uses"] = [{"value": -4.0}] * config.LESSON_MIN_USES
    mem = memory.evaluate(mem, 7, points={})
    memory.save_memory(mock_folder, t.id, mem)
    runner.decide(8, mock=True, teams=[t])
    text = prompt(mock_folder, 8, t.id)
    assert "Lessons removed since your last decision" in text and "cheapest player" in text
    assert read_json(mock_folder / "memory" / t.id / "latest.json")["removed_notices"] == []   # shown once


def test_memory_rule_break_gets_a_retry(mock_folder, monkeypatch):
    monkeypatch.setattr(runner, "MockAgent", lambda model, seed: MockAgent(model, seed, illegal_rate=0, chip_rate=0))
    original = MockAgent._add_memory
    calls = []

    def too_many_notes_once(self, answer, ctx):
        calls.append(1)
        answer = original(self, answer, ctx)
        return {**answer, "updated_notes": ["x"] * (config.MEMORY_MAX_LESSONS + 1)} if len(calls) == 1 else answer
    monkeypatch.setattr(MockAgent, "_add_memory", too_many_notes_once)
    runner.decide(8, mock=True, teams=[team("S-self")])
    d = read_json(mock_folder / "decisions" / "gw8" / "S-self.json")
    assert d["outcome"] == "accepted" and d["attempts"] == 2
