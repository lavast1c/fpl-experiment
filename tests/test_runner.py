"""The weekly runner end to end with the mock agent, using the real gameweek 8 snapshot.

Everything is written to a temporary folder instead of data/mock.
"""

import pytest

from experiment import config, runner
from experiment.agents import MockAgent
from experiment.files import read_json
from experiment.teams import TEAMS

TEAM = TEAMS[0]


@pytest.fixture(autouse=True)
def temporary_mock_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MOCK_DIR", tmp_path)


def use_mock(monkeypatch, **settings):
    monkeypatch.setattr(runner, "MockAgent", lambda model, seed: MockAgent(model, seed, **settings))


def decision(gw):
    return read_json(config.MOCK_DIR / "decisions" / f"gw{gw}" / f"{TEAM.id}.json")


def test_accepted_decision_is_saved_and_scored(monkeypatch):
    use_mock(monkeypatch, illegal_rate=0, chip_rate=0)
    runner.decide(8, mock=True, teams=[TEAM])
    d = decision(8)
    assert d["outcome"] == "accepted" and d["attempts"] == 1 and len(d["decision"]["squad"]) == 15
    assert runner.load_state(config.MOCK_DIR, TEAM.id).has_squad
    rows = runner.score_gameweek(8, mock=True)
    assert rows[0]["team"] == TEAM.id and rows[0]["net_points"] == rows[0]["points"]


def test_every_attempt_illegal_in_first_week_means_no_squad(monkeypatch):
    use_mock(monkeypatch, illegal_rate=1, retry_illegal_rate=1)
    runner.decide(8, mock=True, teams=[TEAM])
    d = decision(8)
    assert d["outcome"] == "no_squad" and d["attempts"] == 6   # 1 + 2 retries + 3 extra in week 1
    assert runner.score_gameweek(8, mock=True)[0]["net_points"] == 0


def test_every_attempt_illegal_later_means_no_changes(monkeypatch):
    use_mock(monkeypatch, illegal_rate=0, chip_rate=0)
    runner.decide(8, mock=True, teams=[TEAM])
    before = runner.load_state(config.MOCK_DIR, TEAM.id)
    use_mock(monkeypatch, illegal_rate=1, retry_illegal_rate=1)
    runner.decide(9, mock=True, teams=[TEAM])
    d = decision(9)
    assert d["outcome"] == "no_change" and d["attempts"] == 3 and d["transfers_made"] == 0
    after = runner.load_state(config.MOCK_DIR, TEAM.id)
    assert after.squad == before.squad and after.lineup == before.lineup
    assert after.free_transfers == min(before.free_transfers + 1, 5)


def test_a_run_out_of_time_starts_no_new_team_but_saves_after_each(monkeypatch):
    from datetime import datetime, timedelta, timezone
    use_mock(monkeypatch, illegal_rate=0, chip_rate=0)
    saves = []
    runner.decide(8, mock=True, teams=TEAMS[:2], after_each=lambda: saves.append(1))
    assert len(saves) == 2                                     # after each team, to push the work so far
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    runner.decide(9, mock=True, teams=TEAMS[:2], stop_at=past, bot_list=[])
    assert all(t.id in runner.undecided(9, mock=True) for t in TEAMS[:2])   # left for the next run


def test_a_memory_team_copies_the_first_squad_but_not_its_chip(monkeypatch):
    from experiment.files import write_json
    use_mock(monkeypatch, illegal_rate=0, chip_rate=0)
    none, self_ = (next(t for t in TEAMS if t.id == i) for i in ("H-none", "H-self"))
    runner.decide(8, mock=True, teams=[none])
    path = config.MOCK_DIR / "decisions" / "gw8" / "H-none.json"
    played = read_json(path)
    played["decision"]["chip"] = "3xc"                         # as if the no-memory team played triple captain
    write_json(path, played)
    runner.decide(8, mock=True, teams=[self_])
    copied = read_json(config.MOCK_DIR / "decisions" / "gw8" / "H-self.json")
    assert copied["copied_from"] == "H-none" and copied["chip"] is None
    assert copied["decision"]["squad"] == played["decision"]["squad"]
    assert runner.load_state(config.MOCK_DIR, "H-self").chips_used == []


def test_already_decided_teams_are_skipped(monkeypatch, capsys):
    use_mock(monkeypatch, illegal_rate=0, chip_rate=0)
    runner.decide(8, mock=True, teams=[TEAM])
    runner.decide(8, mock=True, teams=[TEAM])
    assert "already decided" in capsys.readouterr().out


def test_free_hit_squad_returns_next_week(monkeypatch):
    use_mock(monkeypatch, illegal_rate=0, chip_rate=0)
    runner.decide(8, mock=True, teams=[TEAM])
    original = runner.load_state(config.MOCK_DIR, TEAM.id).squad

    normal_week = MockAgent._random_week

    def free_hit_week(self, ctx):
        return {**normal_week(self, ctx), "chip": "freehit"}
    monkeypatch.setattr(MockAgent, "_random_week", free_hit_week)
    runner.decide(9, mock=True, teams=[TEAM])
    assert decision(9)["chip"] == "freehit"

    monkeypatch.setattr(MockAgent, "_random_week", normal_week)
    use_mock(monkeypatch, illegal_rate=1, retry_illegal_rate=1)   # no changes in GW10
    runner.decide(10, mock=True, teams=[TEAM])
    assert runner.load_state(config.MOCK_DIR, TEAM.id).squad == original


def test_real_run_needs_confirmation():
    with pytest.raises(SystemExit):
        runner.decide(8, mock=False, teams=[TEAM])


def test_missed_deadline_keeps_last_weeks_team(monkeypatch):
    use_mock(monkeypatch, illegal_rate=0, chip_rate=0)
    runner.decide(8, mock=True, teams=[TEAM], bot_list=[])
    before = runner.load_state(config.MOCK_DIR, TEAM.id)
    assert TEAM.id in runner.record_missed(9, mock=True)
    d = decision(9)
    assert d["outcome"] == "missed" and d["attempts"] == 0 and d["transfers_made"] == 0
    after = runner.load_state(config.MOCK_DIR, TEAM.id)
    assert after.squad == before.squad and after.lineup == before.lineup
    assert after.free_transfers == min(before.free_transfers + 1, 5)
    assert runner.record_missed(9, mock=True) == []   # nothing left to record
    rows = runner.score_gameweek(9, mock=True)
    assert any(r["team"] == TEAM.id for r in rows)
    standing = next(s for s in read_json(config.MOCK_DIR / "results" / "standings.json") if s["team"] == TEAM.id)
    assert standing["missed_weeks"] == 1 and standing["failed_weeks"] == 0


def test_no_decision_starts_after_the_deadline(bootstrap):
    events = bootstrap["events"]   # made-up data: gameweek 9's deadline was 24 Oct 2026
    assert runner.deadline_passed(events, 9, mock=False)
    assert not runner.deadline_passed(events, 9, mock=True)
