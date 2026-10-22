"""Test the expected-points predictor on four past seasons (2022/23 to 2025/26).

FPL's API only serves the current season, so past seasons come from a public community dataset:
    Vaastav Anand, "FPL Historical Dataset", https://github.com/vaastav/Fantasy-Premier-League
pinned to one commit so the test can be repeated. The files are saved in data/past_seasons/,
which is git-ignored: we use the dataset, we don't republish it.

The dataset has one row per player per match (minutes, goals, assists, xG, xA, clean sheets,
goals conceded, official points...), but not the official point breakdowns ("explain") that our
predictor learns from. So we rebuild them in the same format: each match's points are split into
appearance, goals, assists, clean sheet, goals conceded, and "other" (whatever is left: bonus,
saves, cards, defensive contributions...). check_rules() confirms on each season's own rows that
the point values we split with really give the official totals.

Then, as in xpoints_check.py, each gameweek from 4 on is predicted from the gameweeks before it
and compared with the official points, for the original version, each candidate change and the
version chosen for the season (xpoints.SEASON).

The dataset also has FPL's own prediction ("xP", from `ep_this`), but fpl_xp_timing() shows it was
saved after the matches were played, so it is not used as a yardstick.
"""

import csv
import io
from collections import defaultdict
from pathlib import Path

import requests

from . import config, xpoints
from .files import read_json_gz, write_json, write_json_gz
from .xpoints import Settings
from .xpoints_check import spearman

SOURCE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League"
SOURCE_COMMIT = "d7b05b51d137bfefef4b692386d18c610975b9b9"     # the dataset as of 22 October 2026
SEASONS = ["2022-23", "2023-24", "2024-25", "2025-26"]          # every season with xG and xA
# FPL only started publishing xG and xA in gameweek 16 of 2022/23 (the dataset has zeros before that),
# so that season is treated as starting at gameweek 16: gameweek 16 becomes "1", 19 becomes "4", ...
XG_FROM = {"2022-23": 16}
FILES = {"merged_gw.csv": "gws/merged_gw.csv", "fixtures.csv": "fixtures.csv", "teams.csv": "teams.csv"}
POSITION_TYPES = {"GK": 1, "GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}   # assistant managers ("AM") are left out
GOALS_PER_DEDUCTION = 2      # this season's breakdowns: 2 or 3 goals conceded cost 1 point, 4 or 5 cost 2
FIRST_TEST_GW = 4


def season_dir(season: str) -> Path:
    return config.PAST_SEASONS_DIR / season


def download(season: str) -> None:
    """Fetch the season's three files once; later runs reuse them."""
    for name, remote in FILES.items():
        path = season_dir(season) / name
        if path.exists():
            continue
        response = requests.get(f"{SOURCE}/{SOURCE_COMMIT}/data/{season}/{remote}", timeout=60)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        print(f"  downloaded {season}/{name} ({len(response.content) / 1e6:.1f} MB)")


def read_rows(path: Path) -> list[dict]:
    # utf-8-sig drops a byte-order mark if the file has one.
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))


def load_season(season: str) -> tuple[list[dict], list[dict], dict[str, int]]:
    """(player-match rows, fixtures in the API's format, team name -> id), from the first gameweek with xG."""
    folder = season_dir(season)
    shift = XG_FROM.get(season, 1) - 1
    team_ids = {t["name"]: int(t["id"]) for t in read_rows(folder / "teams.csv")}
    rows = [{**r, "round": str(int(r["round"]) - shift)} for r in read_rows(folder / "merged_gw.csv")
            if r["position"] in POSITION_TYPES and int(r["round"]) > shift]
    fixtures = [{"id": int(f["id"]), "event": int(f["event"]) - shift,
                 "team_h": int(f["team_h"]), "team_a": int(f["team_a"]), "kickoff_time": f["kickoff_time"],
                 "finished": f["finished"] == "True",
                 "team_h_score": int(f["team_h_score"]) if f["team_h_score"] else None,
                 "team_a_score": int(f["team_a_score"]) if f["team_a_score"] else None}
                for f in read_rows(folder / "fixtures.csv") if f["event"] and int(f["event"]) > shift]
    return rows, fixtures, team_ids


def main_points(row: dict, scoring: dict) -> dict[str, int]:
    """Points for the five parts the predictor models separately, from one match's stats."""
    pos = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}[POSITION_TYPES[row["position"]]]
    minutes = int(row["minutes"])
    return {
        "minutes": scoring["long_play"] if minutes >= 60 else scoring["short_play"] if minutes > 0 else 0,
        "goals_scored": int(row["goals_scored"]) * scoring["goals_scored"][pos],
        "assists": int(row["assists"]) * scoring["assists"],
        "clean_sheets": int(row["clean_sheets"]) * scoring["clean_sheets"][pos],
        "goals_conceded": int(row["goals_conceded"]) // GOALS_PER_DEDUCTION * scoring["goals_conceded"][pos],
    }


def check_rules(rows: list[dict], scoring: dict) -> dict:
    """Do our point values give the official total? Checked on matches where nothing outside the
    five main parts can have scored: no bonus, cards, own goals, penalties, saves or defensive actions."""
    def quiet(r):
        return (r["bonus"] == r["yellow_cards"] == r["red_cards"] == r["own_goals"] == "0"
                and r["penalties_saved"] == r["penalties_missed"] == r["saves"] == "0"
                and int(r.get("defensive_contribution") or 0) == 0)
    checked = [r for r in rows if quiet(r)]
    wrong = [r for r in checked if sum(main_points(r, scoring).values()) != int(r["total_points"])]
    examples = defaultdict(int)
    for r in wrong:
        examples[(r["position"], int(r["minutes"]) >= 60, r["goals_scored"], r["assists"], r["clean_sheets"],
                  r["goals_conceded"], r["total_points"])] += 1
    return {"matches_checked": len(checked), "mismatches": len(wrong),
            "most_common_mismatches": [list(k) + [n] for k, n in sorted(examples.items(), key=lambda kv: -kv[1])[:8]]}


def convert(season: str, rows: list[dict], scoring: dict) -> Path:
    """Write each gameweek as an official-points file in the API's format (`event/{gw}/live/`),
    so the predictor reads past seasons exactly as it reads this one. Returns the folder."""
    raw_dir = season_dir(season) / "converted"
    by_gw = defaultdict(lambda: defaultdict(list))            # gw -> player -> his rows (2 in a double gameweek)
    for r in rows:
        by_gw[int(r["round"])][int(r["element"])].append(r)
    for gw in range(1, 39):
        elements = []
        for pid, matches in by_gw[gw].items():
            stats = {"minutes": 0, "expected_goals": 0.0, "expected_assists": 0.0, "assists": 0,
                     "goals_conceded": 0, "total_points": 0}
            explain = []
            for r in matches:
                for key in stats:
                    stats[key] += float(r[key]) if key.startswith("expected") else int(r[key])
                parts = main_points(r, scoring)
                other = int(r["total_points"]) - sum(parts.values())
                values = {"minutes": int(r["minutes"]), "goals_scored": int(r["goals_scored"]),
                          "assists": int(r["assists"]), "clean_sheets": int(r["clean_sheets"]),
                          "goals_conceded": int(r["goals_conceded"])}
                # Like FPL's breakdowns: minutes always, other stats only when they scored points.
                listed = [{"identifier": k, "value": values[k], "points": p}
                          for k, p in parts.items() if k == "minutes" or p != 0]
                if other:
                    listed.append({"identifier": "other", "value": 0, "points": other})
                explain.append({"fixture": int(r["fixture"]), "stats": listed})
            stats["expected_goals"] = f"{stats['expected_goals']:.2f}"      # the API sends these as text
            stats["expected_assists"] = f"{stats['expected_assists']:.2f}"
            elements.append({"id": pid, "stats": stats, "explain": explain})
        write_json_gz(raw_dir / f"gw{gw}" / f"event-{gw}-live_converted.json.gz", {"elements": elements})
    return raw_dir


def bootstrap_for(gw: int, rows: list[dict], team_ids: dict[str, int], scoring: dict) -> dict:
    """The parts of `bootstrap-static/` the predictor uses, as they stood at gameweek gw's deadline:
    every player seen so far, at his club in that gameweek (or his last club before it)."""
    latest = {}
    for r in sorted(rows, key=lambda r: int(r["round"])):
        if int(r["round"]) <= gw:
            latest[int(r["element"])] = r
    elements = [{"id": pid, "web_name": r["name"], "team": team_ids[r["team"]],
                 "element_type": POSITION_TYPES[r["position"]], "now_cost": int(r["value"]),
                 "status": "a", "chance_of_playing_next_round": None} for pid, r in latest.items()]
    return {"elements": elements, "teams": [{"id": t} for t in team_ids.values()],
            "game_config": {"scoring": scoring}}


# The original version first, then the candidate changes from the 2026-10-22 review, one at a time and together.
VARIANTS = {
    "original version (2026-10-22)": Settings(),
    "conceded fix only": Settings(conceded_all_goals=True),
    "assist fix only": Settings(scale_assists=True),
    "clean-sheet fix only": Settings(clean_sheet_on_pitch=True),
    "stronger pull (900) only": Settings(prior_minutes=900),
    "season minutes 25% only": Settings(season_minutes_weight=0.25),
    "season minutes 50% only": Settings(season_minutes_weight=0.5),
    "pull 900 + season 25%": Settings(prior_minutes=900, season_minutes_weight=0.25),
    "SEASON VERSION: assists + pull 900 + season 25%": xpoints.SEASON,
    "conceded + assists + pull 900 + season 25%": Settings(conceded_all_goals=True, scale_assists=True,
                                                           prior_minutes=900, season_minutes_weight=0.25),
    "all four + pull 900 + season 25%": Settings(conceded_all_goals=True, scale_assists=True,
                                                 clean_sheet_on_pitch=True, prior_minutes=900,
                                                 season_minutes_weight=0.25),
}
FORM = "form (last 4 gameweeks)"


def scores(pred: dict, actual: dict, position: dict) -> dict:
    """Scores for one gameweek. pred and actual: player -> points; position: player -> GKP/DEF/MID/FWD.
        correlation     ranking of players vs ranking of their points (Spearman)
        top-50 actual   average points of the 50 players rated highest (what a picker gets)
        RMSE            typical size of the error; unlike MAE it doesn't reward under-predicting
        bias            average predicted minus actual: all players, the top 50 and top 15, each position"""
    ids = list(pred)
    p, a = [pred[i] for i in ids], [actual[i] for i in ids]
    order = sorted(ids, key=lambda i: -pred[i])
    out = {"correlation": spearman(p, a),
           "top-50 actual": sum(actual[i] for i in order[:50]) / 50,
           "RMSE": (sum((x - y) ** 2 for x, y in zip(p, a)) / len(ids)) ** 0.5,
           "bias": sum(x - y for x, y in zip(p, a)) / len(ids),
           "bias top-50": sum(pred[i] - actual[i] for i in order[:50]) / 50,
           "bias top-15": sum(pred[i] - actual[i] for i in order[:15]) / 15}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        group = [i for i in ids if position[i] == pos]
        out[f"bias {pos}"] = sum(pred[i] - actual[i] for i in group) / len(group)
    return out


def average(per_gw: dict) -> dict:
    """Mean of each score over the gameweeks, per method."""
    weeks = list(per_gw.values())
    return {method: {"gameweeks": len(weeks),
                     **{k: round(sum(w[method][k] for w in weeks) / len(weeks), 3) for k in weeks[0][method]}}
            for method in weeks[0]}


def fpl_xp_timing(rows: list[dict]) -> dict:
    """Was the dataset's FPL xP for gameweek N saved before gameweek N was played? If so, a big score
    in gameweek N could not change it. Compares each player's xP with his xP the gameweek before,
    for players who then scored 10+ points and players who scored 1-2."""
    xp, points = defaultdict(dict), defaultdict(lambda: defaultdict(int))
    for r in rows:
        xp[int(r["round"])].setdefault(int(r["element"]), float(r["xP"]))
        points[int(r["round"])][int(r["element"])] += int(r["total_points"])
    change = {"scored 10+": [], "scored 1-2": []}
    for gw in xp:
        for pid, value in xp[gw].items():
            before = xp.get(gw - 1, {}).get(pid, 0.0)
            if value > 0 and before > 0:
                if points[gw][pid] >= 10:
                    change["scored 10+"].append(value - before)
                elif 1 <= points[gw][pid] <= 2:
                    change["scored 1-2"].append(value - before)
    return {group: {"players": len(v), "average xP change": round(sum(v) / len(v), 2)} for group, v in change.items()}


def test_season(season: str, scoring: dict, variants: dict = VARIANTS) -> dict:
    """Scores for every test gameweek of the season, for each variant and for form as a simple yardstick."""
    download(season)
    rows, fixtures, team_ids = load_season(season)
    check = check_rules(rows, scoring)
    if check["mismatches"]:
        raise ValueError(f"{season}: our point values don't match the official totals: {check}")
    raw_dir = convert(season, rows, scoring)
    points = defaultdict(lambda: defaultdict(int))             # gw -> player -> official points
    minutes_before = defaultdict(set)                          # gw -> players who played before it
    for r in rows:
        gw, pid = int(r["round"]), int(r["element"])
        points[gw][pid] += int(r["total_points"])
        if int(r["minutes"]) > 0:
            for later in range(gw + 1, 39):
                minutes_before[later].add(pid)

    per_gw = {}                                                # gw -> method -> scores
    for gw in range(FIRST_TEST_GW, 39):
        bootstrap = bootstrap_for(gw, rows, team_ids, scoring)
        playing = {t for f in fixtures if f["event"] == gw for t in (f["team_h"], f["team_a"])}
        # Players who had already played and whose club plays this gameweek (blank gameweeks are left out).
        # Their prediction is "if fit": we have no past injury news.
        candidates = {p["id"]: xpoints.POSITIONS[p["element_type"]] for p in bootstrap["elements"]
                      if p["id"] in minutes_before[gw] and p["team"] in playing}
        if not candidates:
            continue
        actual = {pid: points[gw].get(pid, 0) for pid in candidates}
        per_gw[gw] = {}
        for name, settings in variants.items():
            xp = xpoints.predict(gw, bootstrap, fixtures, raw_dir, settings)
            per_gw[gw][name] = scores({pid: xp[pid]["xp_if_fit"] for pid in candidates}, actual, candidates)
        form = {pid: sum(points[g].get(pid, 0) for g in range(gw - 4, gw)) / 4 for pid in candidates}
        per_gw[gw][FORM] = scores(form, actual, candidates)
    return {"test_gameweeks": sorted(per_gw), "rules_check": check, "fpl_xp_timing": fpl_xp_timing(rows),
            "average": average(per_gw)}


def run(seasons: list[str] = SEASONS, bootstrap_file: str = "gw8/bootstrap-static_20261022T143206Z.json.gz") -> dict:
    """Test every season, save data/checks/xpoints_past_seasons.json and print the results."""
    # Point values come from this season's API settings; check_rules() confirms them for each past season.
    scoring = read_json_gz(config.RAW_DIR / bootstrap_file)["game_config"]["scoring"]
    result = {"source": f"{SOURCE}/{SOURCE_COMMIT}", "seasons": {}}
    for season in seasons:
        print(f"Testing {season}...", flush=True)
        result["seasons"][season] = test_season(season, scoring)
    # All seasons together: every test gameweek counts the same.
    weeks = {s: len(result["seasons"][s]["test_gameweeks"]) for s in seasons}
    total = sum(weeks.values())
    result["all_seasons"] = {
        method: {"gameweeks": total,
                 **{k: round(sum(result["seasons"][s]["average"][method][k] * weeks[s] for s in seasons) / total, 3)
                    for k in m if k != "gameweeks"}}
        for method, m in result["seasons"][seasons[0]]["average"].items()}
    write_json(config.DATA_DIR / "checks" / "xpoints_past_seasons.json", result)
    for season in seasons:
        print_table(result["seasons"][season]["average"], season)
    print_table(result["all_seasons"], f"All {len(seasons)} seasons")
    print("Dataset's FPL xP vs the gameweek before, by what the player then scored (saved after the matches?):")
    for season in seasons:
        print(f"  {season}: {result['seasons'][season]['fpl_xp_timing']}")
    return result


def print_table(averages: dict, title: str) -> None:
    columns = ["correlation", "top-50 actual", "RMSE", "bias", "bias top-50", "bias top-15",
               "bias GKP", "bias DEF", "bias MID", "bias FWD"]
    print(f"{title} ({next(iter(averages.values()))['gameweeks']} test gameweeks)")
    print(f"  {'method':<44}" + "".join(f"{c:>14}" for c in columns))
    for name, m in averages.items():
        print(f"  {name:<44}" + "".join(f"{m[c]:>14.3f}" for c in columns))
