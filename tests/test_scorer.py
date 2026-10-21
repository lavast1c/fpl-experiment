"""Scoring: captain, vice-captain, automatic substitutions and chips, on made-up points."""

from test_validator import BENCH, RULES, XI, make_players

from experiment.scorer import LivePlayer, auto_subs, live_from_api, score
from experiment.team import Lineup

POSITIONS = {pid: p.position for pid, p in make_players().items()}


def live(points=None, did_not_play=()):
    """Everyone plays 90 minutes and scores 2, unless told otherwise."""
    points = points or {}
    return {pid: LivePlayer(0 if pid in did_not_play else 90, points.get(pid, 0 if pid in did_not_play else 2))
            for pid in POSITIONS}


def lineup(xi=XI, bench=BENCH, captain=31, vice=21):
    return Lineup(list(xi), list(bench), captain, vice)


def test_everyone_plays_captain_doubled():
    result = score(lineup(), None, POSITIONS, live({31: 10}), RULES)
    assert result.points == 10 * 2 + 2 * 10 and result.captain == 31 and result.auto_subs == []
    assert result.bench_points == 8


def test_vice_captain_takes_over():
    result = score(lineup(), None, POSITIONS, live({21: 6}, did_not_play={31}), RULES)
    assert result.captain == 21
    # 31 is replaced by the first outfield sub (14, a defender: 4-5-1 is valid), who scores 2.
    assert result.auto_subs == [(31, 14)]
    assert result.points == 6 * 2 + 2 * 9 + 2


def test_neither_captain_played():
    result = score(lineup(), None, POSITIONS, live(did_not_play={31, 21}), RULES)
    assert result.captain is None
    assert result.points == 11 * 2                     # two subs came on, nobody doubled


def test_triple_captain():
    assert score(lineup(), "3xc", POSITIONS, live({31: 10}), RULES).points == 10 * 3 + 2 * 10
    result = score(lineup(), "3xc", POSITIONS, live({21: 5}, did_not_play={31}), RULES)
    assert result.captain == 21 and result.multiplier == 3


def test_bench_boost_counts_all_fifteen_without_subs():
    result = score(lineup(), "bboost", POSITIONS, live({31: 10}, did_not_play={11}), RULES)
    assert result.auto_subs == [] and len(result.counted) == 15
    assert result.points == 10 * 2 + 2 * 13 + 0         # 11 didn't play: 0 points, still "counted"
    assert result.bench_points == 0


def test_goalkeeper_only_replaced_by_goalkeeper():
    xi, subs = auto_subs(XI, BENCH, POSITIONS, live(did_not_play={1}), RULES)
    assert subs == [(1, 2)] and xi[0] == 2
    xi, subs = auto_subs(XI, BENCH, POSITIONS, live(did_not_play={1, 2}), RULES)
    assert subs == []                                   # outfield subs can't go in goal


def test_subs_in_priority_order_skipping_non_players():
    # 21 (MID) doesn't play; first sub 14 also didn't play, so 15 comes on.
    xi, subs = auto_subs(XI, BENCH, POSITIONS, live(did_not_play={21, 14}), RULES)
    assert subs == [(21, 15)]


def test_sub_must_keep_a_valid_formation():
    # XI is 3-5-2. A defender (11) doesn't play. Bench order puts a forward (33) first:
    # 2-5-3 is invalid, so the defender 14 comes on instead.
    xi, subs = auto_subs(XI, [2, 33, 14, 15], POSITIONS, live(did_not_play={11}), RULES)
    assert subs == [(11, 14)]


def test_no_valid_sub_leaves_the_starter():
    # A defender misses out and the only subs who played are forwards: no change possible.
    xi, subs = auto_subs(XI, [2, 33, 14, 15], POSITIONS, live(did_not_play={11, 14, 15}), RULES)
    assert subs == [] and 11 in xi


def test_each_sub_used_once():
    xi, subs = auto_subs(XI, BENCH, POSITIONS, live(did_not_play={21, 22, 23, 24}), RULES)
    assert [s for _, s in subs] == [14, 15, 33]          # only 3 outfield subs exist
    assert 24 in xi


def test_live_from_api():
    data = {"elements": [{"id": 5, "stats": {"minutes": 90, "total_points": 7}, "explain": []}]}
    assert live_from_api(data) == {5: LivePlayer(90, 7)}
