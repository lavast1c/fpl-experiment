"""The two rule-based bots, using the real gameweek 8 player data."""

import copy

import pytest

from experiment import bots, runner, xpoints
from experiment.rules import load_rules
from experiment.team import TeamState, players_from_bootstrap
from experiment.validator import apply, validate


@pytest.fixture(scope="module")
def week():
    bootstrap, _, _ = runner.gameweek_inputs(8)
    return bootstrap["elements"], players_from_bootstrap(bootstrap), load_rules(), xpoints.for_snapshot(8)


def first_week(bot, week):
    elements, players, rules, projections = week
    state = TeamState(bot.id)
    answer = bots.decide(bot, state, elements, players, rules, projections)
    result = validate(answer, state, players, rules, 8)
    return answer, result, apply(answer, state, players, rules, 8, result) if result.ok else None


def set_chance(elements, pid, status, chance):
    """A copy of the player data with one player's fitness news changed."""
    elements = copy.deepcopy(elements)
    element = next(e for e in elements if e["id"] == pid)
    element["status"], element["chance_of_playing_next_round"] = status, chance
    return elements


def test_score_is_marked_down_by_chance_of_playing():
    news = [("a", None), ("d", 75), ("d", 50), ("d", 25), ("i", 0), ("u", None)]
    elements = [{"id": i, "form": "8.0", "status": status, "chance_of_playing_next_round": chance}
                for i, (status, chance) in enumerate(news, start=1)]
    rank = bots.ranking("form", elements)
    assert [rank[pid][0] for pid in range(1, 7)] == [8.0, 4.0, 2.0, 0.0, 0.0, 0.0]


@pytest.mark.parametrize("bot", bots.BOTS, ids=lambda b: b.id)
def test_first_squad_is_legal_and_captain_is_best_scoring(bot, week):
    elements, players, _, projections = week
    answer, result, _ = first_week(bot, week)
    assert result.ok, result.errors
    assert answer["chip"] is None
    rank = bots.ranking(bot.lineup_by or bot.ranks_by, elements, projections)
    fit = [pid for pid in answer["starting_xi"] if bots.chance_of_playing(next(e for e in elements if e["id"] == pid)) == 100]
    assert answer["captain"] == max(fit, key=lambda pid: rank[pid])
    assert all(bots.fitness_weight(e) > 0 for e in elements if e["id"] in answer["squad"])


@pytest.mark.parametrize("bot", bots.BOTS, ids=lambda b: b.id)
def test_injured_player_is_sold_and_no_hits(bot, week):
    _, players, rules, projections = week
    _, _, state = first_week(bot, week)
    state.free_transfers = 1
    injured = state.lineup.captain
    elements = set_chance(week[0], injured, "i", 0)
    answer = bots.decide(bot, state, elements, players, rules, projections)
    result = validate(answer, state, players, rules, 9)
    assert result.ok, result.errors
    assert answer["transfers"][0]["out"] == injured
    assert len(answer["transfers"]) == 1 and result.hit_points == 0


@pytest.mark.parametrize("chance", [75, 25])
def test_doubtful_player_is_never_captain_while_a_fit_player_starts(chance, week):
    _, players, rules, projections = week
    bot = bots.BOTS[0]
    _, _, state = first_week(bot, week)
    state.free_transfers = 0
    star = state.lineup.captain
    answer = bots.decide(bot, state, set_chance(week[0], star, "d", chance), players, rules, projections)
    assert star not in (answer["captain"], answer["vice_captain"])


def test_no_free_transfers_means_no_transfers(week):
    elements, players, rules, projections = week
    _, _, state = first_week(bots.BOTS[0], week)
    state.free_transfers = 0
    assert bots.decide(bots.BOTS[0], state, elements, players, rules)["transfers"] == []


def test_player_removed_from_the_game_is_replaced(week):
    elements, players, rules, projections = week
    _, _, state = first_week(bots.BOTS[1], week)
    state.free_transfers, state.bank = 1, 20   # enough money for any cheap replacement
    players = copy.deepcopy(players)
    gone = state.lineup.bench_order[1]
    position = players[gone].position
    del players[gone]
    answer = bots.decide(bots.BOTS[1], state, elements, players, rules, projections)
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


def test_a_removed_player_who_cant_be_replaced_doesnt_crash_the_bot(week):
    elements, players, rules, projections = week
    _, _, state = first_week(bots.BOTS[1], week)
    state.free_transfers = 0                   # so he can't be sold
    players = copy.deepcopy(players)
    gone = state.lineup.starting_xi[3]
    del players[gone]
    answer = bots.decide(bots.BOTS[1], state, elements, players, rules, projections)
    assert answer["bench_order"][-1] == gone   # placed last, with no position to go by
    assert not validate(answer, state, players, rules, 9).ok   # so run_bot keeps last week's team


def test_a_team_with_no_decision_scores_zero_even_with_last_weeks_lineup_saved(week):
    _, _, state = first_week(bots.BOTS[0], week)
    assert state.lineup is not None
    nothing = {"decision": None, "chip": None, "hit_points": 0, "outcome": "no_change_failed"}
    row = runner._team_row(bots.BOTS[0].id, 9, nothing, state, {}, {}, {}, load_rules())
    assert row["points"] == row["net_points"] == 0 and row["players"] == []
