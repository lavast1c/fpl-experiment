"""Every validator rule, on a small made-up game (no real players needed)."""

import pytest

from experiment import config
from experiment.rules import load_rules, rules_from_api
from experiment.team import Player, TeamState, selling_price
from experiment.validator import apply, no_change_decision, start_gameweek, validate

GW = 8

API_RULES = {
    "game_settings": {"squad_squadsize": 15, "squad_squadplay": 11, "squad_team_limit": 3,
                      "squad_total_spend": 1000, "transfers_sell_on_fee": 0.5, "max_extra_free_transfers": 4},
    "positions": [
        {"id": 1, "singular_name_short": "GKP", "squad_select": 2, "squad_min_play": 1, "squad_max_play": 1},
        {"id": 2, "singular_name_short": "DEF", "squad_select": 5, "squad_min_play": 3, "squad_max_play": 5},
        {"id": 3, "singular_name_short": "MID", "squad_select": 5, "squad_min_play": 2, "squad_max_play": 5},
        {"id": 4, "singular_name_short": "FWD", "squad_select": 3, "squad_min_play": 1, "squad_max_play": 3},
    ],
    "chips": [
        {"id": 1, "name": "wildcard", "start_event": 2, "stop_event": 19, "chip_type": "transfer"},
        {"id": 2, "name": "wildcard", "start_event": 20, "stop_event": 38, "chip_type": "transfer"},
        {"id": 3, "name": "freehit", "start_event": 2, "stop_event": 19, "chip_type": "transfer"},
        {"id": 4, "name": "bboost", "start_event": 1, "stop_event": 19, "chip_type": "team"},
        {"id": 5, "name": "3xc", "start_event": 1, "stop_event": 19, "chip_type": "team"},
        {"id": 6, "name": "freehit", "start_event": 20, "stop_event": 38, "chip_type": "transfer"},
        {"id": 7, "name": "bboost", "start_event": 20, "stop_event": 38, "chip_type": "team"},
        {"id": 8, "name": "3xc", "start_event": 20, "stop_event": 38, "chip_type": "team"},
    ],
}
RULES = rules_from_api(API_RULES)


def make_players() -> dict[int, Player]:
    players = {}
    def add(pid, pos, club, price, status="a"):
        players[pid] = Player(pid, f"P{pid}", pos, club, price, status)
    for i, club in enumerate([1, 2, 3, 4]):
        add(1 + i, 1, club, 45)                 # goalkeepers 1-4
    for i, club in enumerate(range(1, 9)):
        add(11 + i, 2, club, 50)                # defenders 11-18
        add(21 + i, 3, club, 70)                # midfielders 21-28
    for i, club in enumerate(range(5, 10)):
        add(31 + i, 4, club, 75)                # forwards 31-35
    add(19, 2, 1, 50)                           # a 4th club-1 player
    add(40, 3, 9, 60, status="u")               # left the league
    add(41, 4, 10, 140)                         # expensive forward
    return players


SQUAD = [1, 2, 11, 12, 13, 14, 15, 21, 22, 23, 24, 25, 31, 32, 33]   # costs £91.5m
XI = [1, 11, 12, 13, 21, 22, 23, 24, 25, 31, 32]
BENCH = [2, 14, 15, 33]


def first_week(**changes) -> dict:
    decision = {"squad": list(SQUAD), "starting_xi": list(XI), "bench_order": list(BENCH),
                "captain": 31, "vice_captain": 21, "chip": None}
    decision.update(changes)
    return decision


@pytest.fixture
def players():
    return make_players()


@pytest.fixture
def team(players):
    """A team that already picked SQUAD last week, with 1 free transfer."""
    state = TeamState("T")
    decision = first_week()
    result = validate(decision, state, players, RULES, GW - 1)
    return apply(decision, state, players, RULES, GW - 1, result)


def week(transfers=(), chip=None, xi=None, bench=None, captain=31, vice=21) -> dict:
    return {"transfers": [{"out": o, "in": i} for o, i in transfers], "starting_xi": xi or list(XI),
            "bench_order": bench or list(BENCH), "captain": captain, "vice_captain": vice, "chip": chip}


def codes(decision, state, players, gw=GW):
    return validate(decision, state, players, RULES, gw).error_codes()


# --- rules come from the API ---------------------------------------------------------------

def test_real_saved_rules_load():
    rules = load_rules(config.RULES_DIR / f"{config.SEASON}_api_rules.json")
    assert (rules.squad_size, rules.xi_size, rules.club_limit, rules.budget) == (15, 11, 3, 1000)
    assert rules.max_free_transfers == 5 and rules.sell_on_fee == 0.5
    assert {c.name for c in rules.chips} == {"wildcard", "freehit", "bboost", "3xc"}
    assert [p.squad_count for p in rules.positions.values()] == [2, 5, 5, 3]


# --- first week: building a squad ----------------------------------------------------------

def test_valid_first_squad(players):
    state = TeamState("T")
    result = validate(first_week(), state, players, RULES, GW)
    assert result.ok, result.feedback()
    new = apply(first_week(), state, players, RULES, GW, result)
    assert new.has_squad and new.bank == 85 and new.free_transfers == 1
    assert new.squad[31] == 75   # purchase prices remembered


def test_squad_size_and_positions(players):
    state = TeamState("T")
    assert "SQUAD_SIZE" in codes(first_week(squad=SQUAD[:-1]), state, players)
    swapped = [26 if pid == 15 else pid for pid in SQUAD]   # a defender swapped for a midfielder
    assert "SQUAD_POSITIONS" in codes(first_week(squad=swapped), state, players)
    assert "DUPLICATE_PLAYER" in codes(first_week(squad=SQUAD[:-1] + [32]), state, players)


def test_club_limit(players):
    squad = [19 if pid == 14 else pid for pid in SQUAD]      # 4th player from club 1
    assert "CLUB_LIMIT" in codes(first_week(squad=squad, bench_order=[2, 19, 15, 33]), TeamState("T"), players)


def test_budget(players):
    squad = [41 if pid == 33 else pid for pid in SQUAD]      # +£6.5m -> £98.0m, fine
    assert codes(first_week(squad=squad, bench_order=[2, 14, 15, 41]), TeamState("T"), players) == []
    players[41].price = 160                                  # exactly £100.0m is allowed
    assert codes(first_week(squad=squad, bench_order=[2, 14, 15, 41]), TeamState("T"), players) == []
    players[41].price = 161                                  # £100.1m is over budget
    assert "OVER_BUDGET" in codes(first_week(squad=squad, bench_order=[2, 14, 15, 41]), TeamState("T"), players)


def test_stale_picks(players):
    result = validate(first_week(squad=SQUAD[:-1] + [999]), TeamState("T"), players, RULES, GW)
    assert "UNKNOWN_PLAYER" in result.error_codes() and result.stale_picks == [999]
    result = validate(first_week(squad=[40 if p == 25 else p for p in SQUAD]), TeamState("T"), players, RULES, GW)
    assert "UNAVAILABLE_PLAYER" in result.error_codes() and result.stale_picks == [40]


def test_first_week_needs_squad_not_transfers(players):
    assert "SQUAD_MISSING" in codes(week(), TeamState("T"), players)


def test_transfer_chips_not_in_first_week(players):
    assert "CHIP_NOT_IN_FIRST_WEEK" in codes(first_week(chip="wildcard"), TeamState("T"), players)
    assert codes(first_week(chip="bboost"), TeamState("T"), players) == []


# --- lineup ---------------------------------------------------------------------------------

def test_formation(team, players):
    xi = [1, 11, 12, 21, 22, 23, 24, 25, 31, 32, 33]          # only 2 defenders
    assert "XI_FORMATION" in codes(week(xi=xi, bench=[2, 13, 14, 15]), team, players)


def test_lineup_errors(team, players):
    assert "XI_SIZE" in codes(week(xi=XI[:-1]), team, players)
    assert "XI_NOT_IN_SQUAD" in codes(week(xi=XI[:-1] + [34]), team, players)
    assert "BENCH_MISMATCH" in codes(week(bench=[2, 14, 15]), team, players)
    assert "CAPTAIN_NOT_IN_XI" in codes(week(captain=33), team, players)
    assert "VICE_CAPTAIN_NOT_IN_XI" in codes(week(vice=2), team, players)
    assert "CAPTAIN_IS_VICE" in codes(week(vice=31), team, players)


def test_bench_goalkeeper_moved_first(team, players):
    result = validate(week(bench=[14, 2, 15, 33]), team, players, RULES, GW)
    assert result.ok and result.bench_order == [2, 14, 15, 33] and result.notes


# --- transfers, money and free transfers ----------------------------------------------------

def test_selling_price():
    assert selling_price(50, 53, 0.5) == 51   # rise 0.3 -> keep 0.1 (rounded down)
    assert selling_price(50, 54, 0.5) == 52
    assert selling_price(50, 47, 0.5) == 47   # falls are passed on in full
    assert selling_price(50, 50, 0.5) == 50


def test_one_free_transfer_no_hit(team, players):
    result = validate(week([(33, 34)], bench=[2, 14, 15, 34]), team, players, RULES, GW)
    assert result.ok and result.hit_points == 0 and result.bank_after == 85
    new = apply(week([(33, 34)], bench=[2, 14, 15, 34]), team, players, RULES, GW, result)
    assert 34 in new.squad and 33 not in new.squad and new.free_transfers == 1


def test_extra_transfer_costs_a_hit(team, players):
    decision = week([(33, 34), (15, 16)], bench=[2, 14, 16, 34])
    result = validate(decision, team, players, RULES, GW)
    assert result.ok and result.hit_points == 4


def test_free_transfers_are_saved_up_to_five(team, players):
    state = team
    for gw in range(GW, GW + 6):
        result = validate(week(), state, players, RULES, gw)
        state = apply(week(), state, players, RULES, gw, result)
    assert state.free_transfers == 5


def test_selling_after_price_rise(team, players):
    players[33].price = 78                                     # bought at 7.5, now 7.8 -> sells for 7.6
    players[35].price = 80
    decision = week([(33, 35)], bench=[2, 14, 15, 35])
    result = validate(decision, team, players, RULES, GW)
    assert result.bank_after == 85 + 76 - 80


def test_transfer_over_budget(team, players):
    players[41].price = 170
    assert "OVER_BUDGET" in codes(week([(33, 41)], bench=[2, 14, 15, 41]), team, players)


def test_bad_transfers(team, players):
    assert "TRANSFER_OUT_NOT_IN_SQUAD" in codes(week([(34, 35)]), team, players)
    assert "TRANSFER_IN_ALREADY_IN_SQUAD" in codes(week([(33, 32)]), team, players)
    assert "TRANSFERS_FORMAT" in codes({**week(), "transfers": [{"out": "33"}]}, team, players)
    assert "UNAVAILABLE_PLAYER" in codes(week([(25, 40)]), team, players)
    assert "SQUAD_NOT_EXPECTED" in codes({**week(), "squad": SQUAD}, team, players)


def test_transfer_must_keep_positions(team, players):
    assert "SQUAD_POSITIONS" in codes(week([(33, 26)], bench=[2, 14, 15, 26]), team, players)


# --- chips ----------------------------------------------------------------------------------

def test_wildcard_no_hits_and_keeps_saved_transfers(team, players):
    decision = week([(33, 34), (15, 16), (14, 17)], chip="wildcard", bench=[2, 16, 17, 34])
    result = validate(decision, team, players, RULES, GW)
    assert result.ok and result.hit_points == 0
    new = apply(decision, team, players, RULES, GW, result)
    assert new.free_transfers == 2 and new.chips_used == [{"chip_id": 1, "name": "wildcard", "gw": GW}]


def test_free_hit_reverts_next_week(team, players):
    decision = week([(33, 34), (15, 16)], chip="freehit", bench=[2, 14, 16, 34])
    result = validate(decision, team, players, RULES, GW)
    assert result.ok and result.hit_points == 0
    during = apply(decision, team, players, RULES, GW, result)
    assert 34 in during.squad
    after = start_gameweek(TeamState.from_dict(during.to_dict()))   # also survives saving to JSON
    assert after.squad == team.squad and after.bank == team.bank and after.lineup == team.lineup
    assert after.free_hit_backup is None


def test_chip_rules(team, players):
    used = TeamState.from_dict({**team.to_dict(), "chips_used": [{"chip_id": 5, "name": "3xc", "gw": 7}]})
    assert "CHIP_ALREADY_USED" in codes(week(chip="3xc"), used, players)
    assert codes(week(chip="3xc"), used, players, gw=20) == []          # second-half copy is fresh
    assert "CHIP_UNKNOWN" in codes(week(chip="manager"), team, players)
    assert "CHIP_NOT_AVAILABLE" in codes(week(chip="wildcard"), TeamState.from_dict(
        {**team.to_dict()}), players, gw=39)


# --- when every attempt fails ----------------------------------------------------------------

def test_no_change_decision(team, players):
    decision = no_change_decision(team)
    assert decision["transfers"] == [] and decision["chip"] is None
    assert validate(decision, team, players, RULES, GW).ok
    assert no_change_decision(TeamState("new")) is None


def test_not_a_json_object(team, players):
    assert codes(["not", "an", "object"], team, players) == ["NOT_AN_OBJECT"]
