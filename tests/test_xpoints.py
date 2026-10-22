"""Our expected-points predictor, on the saved gameweek 1-8 data."""

import pytest

from experiment import config, xpoints
from experiment.files import read_json_gz
from experiment.xpoints_check import actual_points


@pytest.fixture(scope="module")
def inputs():
    bootstrap = read_json_gz(config.RAW_DIR / "gw8/bootstrap-static_20261022T143206Z.json.gz")
    fixtures = read_json_gz(config.RAW_DIR / "gw8/fixtures_20261022T143207Z.json.gz")
    return bootstrap, fixtures


def test_every_player_gets_a_prediction_and_injured_players_get_none(inputs):
    bootstrap, fixtures = inputs
    xp = xpoints.predict(8, bootstrap, fixtures)
    assert set(xp) == {p["id"] for p in bootstrap["elements"]}
    for p in bootstrap["elements"]:
        v = xp[p["id"]]
        assert 0 <= v["xp"] <= v["xp_if_fit"] <= v["xp_3gw_if_fit"] + 1e-9
        if p["status"] in {"i", "s", "u"}:
            assert v["xp"] == 0


def test_predicted_totals_are_close_to_real_totals(inputs):
    bootstrap, fixtures = inputs
    xp = xpoints.predict(7, bootstrap, fixtures)          # only gameweeks 1-6 are used
    actual = actual_points(7)
    predicted_total = sum(v["xp_if_fit"] for v in xp.values())
    assert abs(predicted_total - sum(actual.values())) / sum(actual.values()) < 0.15


def test_default_settings_are_the_fixed_version(inputs):
    bootstrap, fixtures = inputs
    assert xpoints.predict(8, bootstrap, fixtures) == xpoints.predict(8, bootstrap, fixtures, settings=xpoints.Settings())
    assert xpoints.Settings() == xpoints.Settings(prior_minutes=450, conceded_all_goals=False, scale_assists=False,
                                                  clean_sheet_on_pitch=False, season_minutes_weight=0.0)


def test_each_option_moves_predictions_the_expected_way(inputs):
    bootstrap, fixtures = inputs
    base = xpoints.load_history(8, bootstrap, fixtures)
    assert base.assists_per_xa["FWD"] > base.assists_per_xa["DEF"] > 1     # FPL is generous with assists
    fixed = xpoints.load_history(8, bootstrap, fixtures, settings=xpoints.Settings(conceded_all_goals=True))
    for pos in ("GKP", "DEF"):                                             # smaller deduction per goal
        assert base.conceded_points[pos] < fixed.conceded_points[pos] < 0
    xp = xpoints.predict(8, bootstrap, fixtures)
    more_assists = xpoints.predict(8, bootstrap, fixtures, settings=xpoints.Settings(scale_assists=True))
    assert all(more_assists[p]["xp_if_fit"] >= xp[p]["xp_if_fit"] for p in xp)


def test_past_season_rows_split_into_the_official_total():
    from experiment.xpoints_past import main_points
    scoring = read_json_gz(config.RAW_DIR / "gw8/bootstrap-static_20261022T143206Z.json.gz")["game_config"]["scoring"]
    # A made-up defender: 90 minutes, 1 goal, conceded 3 (costs 1 point), so 2 + 6 - 1 = 7.
    row = {"position": "DEF", "minutes": "90", "goals_scored": "1", "assists": "0", "clean_sheets": "0",
           "goals_conceded": "3", "total_points": "7"}
    parts = main_points(row, scoring)
    assert parts == {"minutes": 2, "goals_scored": 6, "assists": 0, "clean_sheets": 0, "goals_conceded": -1}
    assert sum(parts.values()) == int(row["total_points"])
