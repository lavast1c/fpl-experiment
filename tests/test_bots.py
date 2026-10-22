"""The two rule-based bots, using the real gameweek 8 player data."""

import copy

import pytest

from experiment import bots, runner
from experiment.rules import load_rules
from experiment.team import TeamState, players_from_bootstrap
from experiment.validator import apply, validate


@pytest.fixture(scope="module")
def week():
    bootstrap, _, _ = runner.gameweek_inputs(8)
    return bootstrap["elements"], players_from_bootstrap(bootstrap), load_rules()


def first_week(bot, week):
    elements, players, rules = week
    state = TeamState(bot.id)
    answer = bots.decide(bot, state, elements, players, rules)
    result = validate(answer, state, players, rules, 8)
    return answer, result, apply(answer, state, players, rules, 8, result) if result.ok else None


def set_chance(elements, pid, status, chance):
    """A copy of the player data with one player's fitness news changed."""
    elements = copy.deepcopy(elements)
    element = next(e for e in elements if e["id"] == pid)
    element["status"], element["chance_of_playing_next_round"] = status, chance
    return elements


def test_score_is_weighed_by_chance_of_playing():
    elements = [{"id": 1, "form": "8.0", "status": "a", "chance_of_playing_next_round": None},
                {"id": 2, "form": "8.0", "status": "d", "chance_of_playing_next_round": 75},
                {"id": 3, "form": "8.0", "status": "i", "chance_of_playing_next_round": 0},
                {"id": 4, "form": "8.0", "status": "u", "chance_of_playing_next_round": None}]
    rank = bots.ranking(bots.BOTS[0], elements)
    assert [rank[pid][0] for pid in (1, 2, 3, 4)] == [8.0, 6.0, 0.0, 0.0]


@pytest.mark.parametrize("bot", bots.BOTS, ids=lambda b: b.id)
def test_first_squad_is_legal_and_captain_is_best_scoring(bot, week):
    elements, players, _ = week
    answer, result, _ = first_week(bot, week)
    assert result.ok, result.errors
    assert answer["chip"] is None
    rank = bots.ranking(bot, elements)
    assert answer["captain"] == max(answer["starting_xi"], key=lambda pid: rank[pid])
    assert all(bots.chance_of_playing(e) > 0 for e in elements if e["id"] in answer["squad"])


@pytest.mark.parametrize("bot", bots.BOTS, ids=lambda b: b.id)
def test_injured_player_is_sold_and_no_hits(bot, week):
    _, players, rules = week
    _, _, state = first_week(bot, week)
    state.free_transfers = 1
    injured = state.lineup.captain
    elements = set_chance(week[0], injured, "i", 0)
    answer = bots.decide(bot, state, elements, players, rules)
    result = validate(answer, state, players, rules, 9)
    assert result.ok, result.errors
    assert answer["transfers"][0]["out"] == injured
    assert len(answer["transfers"]) == 1 and result.hit_points == 0


def test_slightly_doubtful_star_is_kept_but_benched_if_very_doubtful(week):
    _, players, rules = week
    bot = bots.BOTS[0]
    _, _, state = first_week(bot, week)
    state.free_transfers = 1
    star = state.lineup.captain
    answer = bots.decide(bot, state, set_chance(week[0], star, "d", 75), players, rules)
    assert star not in {t["out"] for t in answer["transfers"]}   # 75% of a top score is still worth keeping
    state.free_transfers = 0
    answer = bots.decide(bot, state, set_chance(week[0], star, "d", 25), players, rules)
    assert answer["captain"] != star


def test_no_free_transfers_means_no_transfers(week):
    elements, players, rules = week
    _, _, state = first_week(bots.BOTS[0], week)
    state.free_transfers = 0
    assert bots.decide(bots.BOTS[0], state, elements, players, rules)["transfers"] == []


def test_player_removed_from_the_game_is_replaced(week):
    elements, players, rules = week
    _, _, state = first_week(bots.BOTS[1], week)
    state.free_transfers, state.bank = 1, 20   # enough money for any cheap replacement
    players = copy.deepcopy(players)
    gone = state.lineup.bench_order[1]
    position = players[gone].position
    del players[gone]
    answer = bots.decide(bots.BOTS[1], state, elements, players, rules)
    result = validate(answer, state, players, rules, 9)
    assert result.ok, result.errors
    assert answer["transfers"][0]["out"] == gone and players[answer["transfers"][0]["in"]].position == position


def test_bot_keeps_last_weeks_team_when_its_answer_is_illegal(tmp_path, monkeypatch):
    from experiment import config
    from experiment.files import read_json
    monkeypatch.setattr(config, "MOCK_DIR", tmp_path)
    bot = bots.BOTS[0]
    runner.decide(8, mock=True, teams=[], bot_list=[bot])
    before = runner.load_state(tmp_path, bot.id)
    monkeypatch.setattr(bots, "decide", lambda *args: {"transfers": [{"out": 1, "in": 1}], "chip": None})
    runner.decide(9, mock=True, teams=[], bot_list=[bot])
    d = read_json(tmp_path / "decisions" / "gw9" / f"{bot.id}.json")
    assert d["outcome"] == "no_change" and d["errors_by_attempt"] != [[]]
    assert runner.load_state(tmp_path, bot.id).squad == before.squad
