"""Expected points, the results files and the rows copied to Supabase, over several mock gameweeks."""

import pytest

from experiment import config, metrics, runner, supabase_sync
from experiment.agents import MockAgent
from experiment.files import read_csv, read_json
from experiment.team import Lineup

EP = {1: 2.0, 2: 3.0, 3: 4.0, 4: 1.0, 5: 5.0}
LINEUP = Lineup(starting_xi=[1, 2, 3], bench_order=[4, 5], captain=3, vice_captain=2)


def test_expected_points_formula():
    assert metrics.expected_points(LINEUP, None, 0, EP) == 2 + 3 + 4 + 4          # captain twice
    assert metrics.expected_points(LINEUP, "3xc", 0, EP) == 2 + 3 + 4 + 4 + 4     # captain three times
    assert metrics.expected_points(LINEUP, "bboost", 4, EP) == 2 + 3 + 4 + 4 + 1 + 5 - 4
    assert metrics.expected_points(None, None, 0, EP) == 0


@pytest.fixture(scope="module")
def season(tmp_path_factory):
    """Three mock gameweeks for all 9 AI teams and both bots."""
    folder = tmp_path_factory.mktemp("mock")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "MOCK_DIR", folder)
        mp.setattr(runner, "MockAgent", lambda model, seed: MockAgent(model, seed, illegal_rate=0.3))
        for gw in (8, 9, 10):
            runner.decide(gw, mock=True)
            runner.score_gameweek(gw, mock=True)
    return folder


def test_results_cover_every_team_and_week(season):
    rows = read_csv(season / "results" / "all_gameweeks.csv")
    assert len(rows) == 3 * 11
    assert {r["team"] for r in rows} >= {"form-bot", "crowd-bot", "O-verified"}
    week8 = read_json(season / "results" / "gw8.json")["teams"]
    assert min(r["rank"] for r in week8) == 1
    assert all(r["captain_changed"] is None for r in week8)          # nothing to compare with yet
    week10 = read_json(season / "results" / "gw10.json")["teams"]
    for r in week10:
        mine = [int(x["net_points"]) for x in rows if x["team"] == r["team"]]
        assert r["season_points"] == sum(mine)
        assert r["luck"] == pytest.approx(r["net_points"] - r["expected_points"])


def test_standings_are_sorted_and_bots_use_no_tokens(season):
    standings = read_json(season / "results" / "standings.json")
    assert [s["points"] for s in standings] == sorted((s["points"] for s in standings), reverse=True)
    bots = [s for s in standings if s["kind"] == "bot"]
    assert len(bots) == 2 and all(s["input_tokens"] == 0 and s["rule_breaks"] == 0 for s in bots)


def test_memory_metrics_present_for_memory_teams(season):
    week9 = {r["team"]: r for r in read_json(season / "results" / "gw9.json")["teams"]}
    assert "notes_detail" in week9["H-self"] and "lessons_detail" in week9["H-verified"]
    assert "notes" not in week9["H-none"]


def test_supabase_rows_match_the_tables(season):
    tables = supabase_sync.experiment_rows(season)
    assert {t: len(rows) for t, (rows, _) in tables.items()} == {
        "teams": 11, "decisions": 33, "results": 33, "standings": 11,
        "memory_notes": 18, "lessons": len(tables["lessons"][0])}
    assert set(tables["results"][0][0]) == supabase_sync.RESULT_COLUMNS | {"players", "transfer_points",
                                                                            "memory_detail"}
