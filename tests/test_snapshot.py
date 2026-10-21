"""Snapshot columns, fixture text (blanks and doubles), filters and gameweek detection."""

from datetime import datetime, timezone

from experiment import gameweeks, snapshot
from experiment.files import read_csv, read_json


def test_gameweek_detection(bootstrap):
    events = bootstrap["events"]
    assert gameweeks.current_gw(events) == 8
    assert gameweeks.next_gw(events) == 9
    assert gameweeks.decision_gw(events) == 9
    now = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
    assert gameweeks.hours_until_deadline(events, 9, now) == 24


def test_fixture_text_shows_blanks_and_doubles(bootstrap, fixtures):
    rows = {r["id"]: r for r in snapshot.build_rows(bootstrap, fixtures, 9)}
    # AAA: home v BBB in GW9, blank GW10, double GW11 ordered by kickoff.
    assert rows[1]["next_fixtures"] == "GW9 BBB(H,3); GW10 -; GW11 CCC(H,3)+DDD(A,5)"
    assert rows[2]["next_fixtures"] == "GW9 AAA(A,4); GW10 CCC(H,2); GW11 -"


def test_fixtures_stop_at_last_gameweek(bootstrap, fixtures):
    rows = snapshot.build_rows(bootstrap, fixtures, 10)
    assert rows[0]["next_fixtures"].count("GW") == 2  # only GW10 and GW11 exist


def test_row_values(bootstrap, fixtures):
    rows = {r["id"]: r for r in snapshot.build_rows(bootstrap, fixtures, 9)}
    striker = rows[2]
    assert striker["price"] == 10.5
    assert striker["pos"] == "FWD" and striker["club"] == "BBB"
    assert striker["chance_next"] == 75
    assert "|" not in striker["news"]  # would break the pipe-separated table
    assert rows[1]["chance_next"] == ""


def test_filters(bootstrap, fixtures):
    rows = snapshot.build_rows(bootstrap, fixtures, 9)
    ids = lambda name: {r["id"] for r in snapshot.apply_filter(rows, name)}
    assert ids("all") == {1, 2, 3, 4}
    assert ids("played") == {1, 2}
    assert ids("played_or_expected") == {1, 2, 4}  # the 0-minute new signing with ep_next > 0 stays


def test_prompt_table_has_one_line_per_player(bootstrap, fixtures):
    rows = snapshot.build_rows(bootstrap, fixtures, 9)
    lines = snapshot.prompt_table(rows).splitlines()
    assert lines[0] == "|".join(snapshot.COLUMNS)
    assert len(lines) == len(rows) + 1
    assert all(line.count("|") == len(snapshot.COLUMNS) - 1 for line in lines)


def test_save_snapshot(tmp_path, bootstrap, fixtures):
    rows = snapshot.build_rows(bootstrap, fixtures, 9)
    meta = snapshot.save_snapshot(9, rows, "played", {"bootstrap": "x"}, out_dir=tmp_path)
    assert meta["players_in_snapshot"] == 2 and meta["players_in_game"] == 4
    assert len(read_csv(tmp_path / "gw9.csv")) == 2
    assert read_json(tmp_path / "gw9.meta.json")["filter"] == "played"
    table = (tmp_path / "gw9_table.txt").read_text(encoding="utf-8")
    assert meta["est_tokens"] == snapshot.estimate_tokens(table)
