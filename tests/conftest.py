"""Small, made-up FPL data for tests. No real teams or managers are used anywhere in the tests."""

import pytest


@pytest.fixture
def bootstrap():
    return {
        "events": [
            {"id": 8, "name": "Gameweek 8", "deadline_time": "2026-10-17T10:00:00Z",
             "is_current": True, "is_next": False, "finished": True, "data_checked": True},
            {"id": 9, "name": "Gameweek 9", "deadline_time": "2026-10-24T10:00:00Z",
             "is_current": False, "is_next": True, "finished": False, "data_checked": False},
            {"id": 10, "name": "Gameweek 10", "deadline_time": "2026-10-31T11:00:00Z",
             "is_current": False, "is_next": False, "finished": False, "data_checked": False},
            {"id": 11, "name": "Gameweek 11", "deadline_time": "2026-11-07T11:00:00Z",
             "is_current": False, "is_next": False, "finished": False, "data_checked": False},
        ],
        "teams": [
            {"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"},
            {"id": 3, "short_name": "CCC"}, {"id": 4, "short_name": "DDD"},
        ],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP", "squad_select": 2},
            {"id": 2, "singular_name_short": "DEF", "squad_select": 5},
            {"id": 3, "singular_name_short": "MID", "squad_select": 5},
            {"id": 4, "singular_name_short": "FWD", "squad_select": 3},
        ],
        "elements": [
            _player(1, "Keeper", 1, 1, 45, minutes=720, ep_next="3.1"),
            _player(2, "Striker", 2, 4, 105, minutes=650, ep_next="6.4", news="Knock | 75% chance", chance=75),
            _player(3, "Benchwarmer", 3, 3, 45, minutes=0, ep_next="0.0"),
            _player(4, "NewSigning", 4, 2, 50, minutes=0, ep_next="2.0"),
        ],
        "game_settings": {"squad_squadsize": 15, "squad_team_limit": 3},
        "chips": [{"name": "wildcard"}],
    }


def _player(pid, name, team, pos, cost, minutes, ep_next, news="", chance=None):
    return {
        "id": pid, "web_name": name, "team": team, "element_type": pos, "now_cost": cost,
        "form": "4.5", "points_per_game": "4.0", "total_points": 30, "minutes": minutes,
        "expected_goals": "1.23", "expected_assists": "0.40", "ep_next": ep_next,
        "selected_by_percent": "12.3", "status": "d" if chance else "a",
        "chance_of_playing_next_round": chance, "news": news,
    }


@pytest.fixture
def fixtures():
    # GW9: AAA v BBB, CCC v DDD.  GW10: AAA blank, BBB v CCC.  GW11: AAA plays twice (double).
    return [
        {"id": 1, "event": 9, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 4,
         "kickoff_time": "2026-10-24T14:00:00Z"},
        {"id": 2, "event": 9, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 2,
         "kickoff_time": "2026-10-24T14:00:00Z"},
        {"id": 3, "event": 10, "team_h": 2, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 3,
         "kickoff_time": "2026-10-31T14:00:00Z"},
        {"id": 4, "event": 11, "team_h": 4, "team_a": 1, "team_h_difficulty": 2, "team_a_difficulty": 5,
         "kickoff_time": "2026-11-07T14:00:00Z"},
        {"id": 5, "event": 11, "team_h": 1, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 4,
         "kickoff_time": "2026-11-04T19:45:00Z"},
        {"id": 6, "event": None, "team_h": 2, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 2,
         "kickoff_time": None},
    ]
