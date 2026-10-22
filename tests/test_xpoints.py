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
