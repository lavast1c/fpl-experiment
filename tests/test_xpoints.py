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


def test_points_saved_after_the_snapshot_are_left_out(inputs, tmp_path):
    # The gameweek 1-7 points were saved on 2026-10-21, before the gameweek 8 snapshot (2026-10-22).
    bootstrap, fixtures = inputs
    raw = tmp_path / "raw"
    for gw in range(1, 8):
        source = xpoints.live_file(gw)
        (raw / f"gw{gw}").mkdir(parents=True)
        (raw / f"gw{gw}" / source.name).write_bytes(source.read_bytes())
    as_of = "20261022T143206Z"
    pinned = xpoints.predict(8, bootstrap, fixtures, raw, as_of=as_of)
    assert pinned == xpoints.predict(8, bootstrap, fixtures)
    # Gameweek 7's points saved again after the snapshot (say, by a later scoring run) change nothing...
    late = raw / "gw7" / "event-7-live_20261023T090000Z.json.gz"
    late.write_bytes(xpoints.live_file(6).read_bytes())    # different numbers, so a change would show
    assert xpoints.predict(8, bootstrap, fixtures, raw, as_of=as_of) == pinned
    # ...while without as_of the newest file is used.
    assert xpoints.predict(8, bootstrap, fixtures, raw) != pinned


def test_the_season_version_is_the_default(inputs):
    bootstrap, fixtures = inputs
    assert xpoints.predict(8, bootstrap, fixtures) == xpoints.predict(8, bootstrap, fixtures, settings=xpoints.SEASON)
    assert xpoints.SEASON == xpoints.Settings(prior_minutes=900, conceded_all_goals=False, scale_assists=True,
                                              clean_sheet_on_pitch=False, season_minutes_weight=0.25)
    # Settings() is still the original version of 2026-10-22, for comparison.
    assert xpoints.Settings() == xpoints.Settings(prior_minutes=450, conceded_all_goals=False, scale_assists=False,
                                                  clean_sheet_on_pitch=False, season_minutes_weight=0.0)


def test_each_option_moves_predictions_the_expected_way(inputs):
    bootstrap, fixtures = inputs
    original = xpoints.Settings()
    base = xpoints.load_history(8, bootstrap, fixtures, settings=original)
    assert base.assists_per_xa["FWD"] > base.assists_per_xa["DEF"] > 1     # FPL is generous with assists
    fixed = xpoints.load_history(8, bootstrap, fixtures, settings=xpoints.Settings(conceded_all_goals=True))
    for pos in ("GKP", "DEF"):                                             # smaller deduction per goal
        assert base.conceded_points[pos] < fixed.conceded_points[pos] < 0
    xp = xpoints.predict(8, bootstrap, fixtures, settings=original)
    more_assists = xpoints.predict(8, bootstrap, fixtures, settings=xpoints.Settings(scale_assists=True))
    assert all(more_assists[p]["xp_if_fit"] >= xp[p]["xp_if_fit"] for p in xp)
    # The stronger pull towards the average lowers the very top predictions.
    pulled = xpoints.predict(8, bootstrap, fixtures, settings=xpoints.Settings(prior_minutes=900))
    top = sorted(xp, key=lambda p: -xp[p]["xp_if_fit"])[:15]
    assert sum(pulled[p]["xp_if_fit"] for p in top) < sum(xp[p]["xp_if_fit"] for p in top)


def test_past_season_rows_split_into_the_official_total():
    from experiment.xpoints_past import main_points
    scoring = read_json_gz(config.RAW_DIR / "gw8/bootstrap-static_20261022T143206Z.json.gz")["game_config"]["scoring"]
    # A made-up defender: 90 minutes, 1 goal, conceded 3 (costs 1 point), so 2 + 6 - 1 = 7.
    row = {"position": "DEF", "minutes": "90", "goals_scored": "1", "assists": "0", "clean_sheets": "0",
           "goals_conceded": "3", "total_points": "7"}
    parts = main_points(row, scoring)
    assert parts == {"minutes": 2, "goals_scored": 6, "assists": 0, "clean_sheets": 0, "goals_conceded": -1}
    assert sum(parts.values()) == int(row["total_points"])
