"""Results and metrics per team, per gameweek and for the season so far (brief section 4.7).

Everything is rebuilt from the saved files (decisions, team states, scores, memory), so it can be
re-run at any time with `python run.py metrics`. Output, inside the run folder (data/ or data/mock/):
    results/gw{N}.json and gw{N}.csv     one row per team for gameweek N
    results/all_gameweeks.csv            every team-gameweek row so far
    results/standings.json and .csv      season totals per team, best first

Expected points (luck-adjusted score), fixed for the season (METHODS.md, 2026-10-22):
    sum of our own expected points (xP, see xpoints.py) for the starting XI, from the same data as
    the snapshot at decision time, with the captain counted twice (three times with triple captain),
    plus the bench's xP with bench boost,
    minus transfer hits.
    "Luck" = actual net points - expected points.
"""

from collections import Counter
from pathlib import Path

from . import config, memory
from .bots import BOTS
from .files import read_json, write_csv, write_json
from .teams import TEAMS
from .team import Lineup


def expected_points(lineup: Lineup | None, chip: str | None, hit_points: int, ep: dict[int, float]) -> float:
    if lineup is None:
        return 0.0
    total = sum(ep.get(pid, 0.0) for pid in lineup.starting_xi)
    total += ((3 if chip == "3xc" else 2) - 1) * ep.get(lineup.captain, 0.0)
    if chip == "bboost":
        total += sum(ep.get(pid, 0.0) for pid in lineup.bench_order)
    return round(total - hit_points, 2)


def participants() -> list[dict]:
    return ([{"team": t.id, "kind": "ai", "model": t.model, "memory": t.memory} for t in TEAMS]
            + [{"team": b.id, "kind": "bot", "model": "rule-based", "memory": "none"} for b in BOTS])


CSV_FIELDS = [
    "team", "kind", "model", "memory", "gw", "points", "hit_points", "net_points", "rank", "fpl_average",
    "vs_average", "expected_points", "luck", "season_points", "season_expected", "season_rank",
    "outcome", "attempts", "rule_breaks", "error_codes", "stale_picks", "transfers_made", "captain_changed",
    "chip", "auto_subs", "bench_points", "input_tokens", "output_tokens", "model_mismatch",
    "notes", "memory_words", "notes_added", "notes_removed",
    "lessons_active", "lessons_new", "lessons_dropped", "lessons_removed", "lessons_proven",
]


def _memory_metrics(base: Path, team: str, kind: str, gw: int, previous_gw: int | None) -> dict:
    """How the team's notes or lessons changed with this gameweek's decision (and its lesson checks)."""
    folder = base / "memory" / team
    path = folder / f"gw{gw}.json"
    if kind == "none" or not path.exists():
        return {}
    now = read_json(path)
    before_path = folder / f"gw{previous_gw}.json" if previous_gw else None
    before = read_json(before_path) if before_path and before_path.exists() else memory.empty_memory(kind)
    if kind == "self":
        added = [n for n in now["notes"] if n not in before["notes"]]
        removed = [n for n in before["notes"] if n not in now["notes"]]
        return {"notes": len(now["notes"]), "memory_words": sum(len(n.split()) for n in now["notes"]),
                "notes_added": len(added), "notes_removed": len(removed),
                "notes_detail": {"notes": now["notes"], "added": added, "removed": removed}}
    # Verified: latest.json also has lesson checks made after scoring; use it for removals.
    latest = read_json(folder / "latest.json")
    active = memory.active_lessons(now)
    return {"notes": len(active), "memory_words": sum(len(l["text"].split()) for l in active),
            "lessons_active": len(active),
            "lessons_new": sum(1 for l in now["lessons"] if l["created_gw"] == gw),
            "lessons_dropped": sum(1 for l in now["lessons"] if l.get("ended_gw") == gw
                                   and l["status"] == "dropped_by_agent"),
            "lessons_removed": sum(1 for l in latest["lessons"] if l.get("ended_gw") == gw and l["status"] == "removed"),
            "lessons_proven": sum(1 for l in memory.active_lessons(latest)
                                  if memory.lesson_record(l)[0] >= config.LESSON_MIN_USES),
            "lessons_detail": [{"id": l["id"], "text": l["text"], "status": l["status"],
                                "uses": memory.lesson_record(l)[0], "average": memory.lesson_record(l)[1]}
                               for l in latest["lessons"]]}


def _rank(values: dict[str, float]) -> dict[str, int]:
    """1 = best; equal values share a rank."""
    return {team: 1 + sum(1 for other in values.values() if other > value) for team, value in values.items()}


def build_all(base: Path) -> list[dict]:
    score_files = sorted((base / "scores").glob("gw*.json"), key=lambda p: int(p.stem[2:]))
    season = {p["team"]: {"points": 0, "expected": 0.0} for p in participants()}
    last_decided = {}            # team -> last gameweek it made a decision
    all_rows = []
    for score_file in score_files:
        scores = read_json(score_file)
        gw, average = scores["gw"], scores.get("average")
        rows = []
        for who in participants():
            team = who["team"]
            score = next((r for r in scores["teams"] if r["team"] == team), None)
            decision_path = base / "decisions" / f"gw{gw}" / f"{team}.json"
            if score is None or not decision_path.exists():
                continue
            decision = read_json(decision_path)
            previous = last_decided.get(team)
            captain_changed = None
            state_path = base / "teams" / team / f"gw{gw}.json"
            if previous is not None and state_path.exists():
                now, before = read_json(state_path), read_json(base / "teams" / team / f"gw{previous}.json")
                if now.get("lineup") and before.get("lineup"):
                    captain_changed = now["lineup"]["captain"] != before["lineup"]["captain"]
            errors = Counter(code for attempt in decision.get("errors_by_attempt", []) for code in attempt)
            expected = decision.get("expected_points")
            season[team]["points"] += score["net_points"]
            season[team]["expected"] += expected or 0
            row = {
                **who, "gw": gw, "points": score["points"], "hit_points": score["hit_points"],
                "net_points": score["net_points"], "fpl_average": average,
                "vs_average": score["net_points"] - average if average is not None else None,
                "expected_points": expected,
                "luck": round(score["net_points"] - expected, 2) if expected is not None else None,
                "season_points": season[team]["points"], "season_expected": round(season[team]["expected"], 2),
                "outcome": decision["outcome"], "attempts": decision["attempts"],
                "rule_breaks": sum(1 for attempt in decision.get("errors_by_attempt", []) if attempt),
                "error_codes": ";".join(f"{code}:{n}" for code, n in sorted(errors.items())),
                "stale_picks": len(decision.get("stale_picks", [])),
                "transfers_made": decision["transfers_made"], "captain_changed": captain_changed,
                "chip": decision["chip"], "auto_subs": score["auto_subs"], "bench_points": score["bench_points"],
                "input_tokens": decision.get("input_tokens", 0), "output_tokens": decision.get("output_tokens", 0),
                "model_mismatch": decision.get("model_mismatch", False),
                **_memory_metrics(base, team, who["memory"], gw, previous),
            }
            rows.append(row)
            last_decided[team] = gw
        week_rank = _rank({r["team"]: r["net_points"] for r in rows})
        season_rank = _rank({r["team"]: r["season_points"] for r in rows})
        for r in rows:
            r["rank"], r["season_rank"] = week_rank[r["team"]], season_rank[r["team"]]
        write_json(base / "results" / f"gw{gw}.json", {"gw": gw, "fpl_average": average, "teams": rows})
        write_csv(base / "results" / f"gw{gw}.csv", [_flat(r) for r in rows], CSV_FIELDS)
        all_rows += rows

    write_csv(base / "results" / "all_gameweeks.csv", [_flat(r) for r in all_rows], CSV_FIELDS)
    standings = _standings(all_rows)
    write_json(base / "results" / "standings.json", standings)
    write_csv(base / "results" / "standings.csv", standings, list(standings[0]) if standings else ["team"])
    print(f"Results for {len(score_files)} gameweek(s) saved in {base.name}/results/")
    return all_rows


def _flat(row: dict) -> dict:
    return {k: row.get(k) for k in CSV_FIELDS}


def _standings(rows: list[dict]) -> list[dict]:
    """Season totals per team, best first, plus FPL's average manager as a reference row."""
    table = []
    for who in participants():
        mine = [r for r in rows if r["team"] == who["team"]]
        if not mine:
            continue
        table.append({
            "team": who["team"], "kind": who["kind"], "model": who["model"], "memory": who["memory"],
            "gameweeks": len(mine), "points": sum(r["net_points"] for r in mine),
            "expected_points": round(sum(r["expected_points"] or 0 for r in mine), 2),
            "luck": round(sum(r["luck"] or 0 for r in mine), 2),
            "hit_points": sum(r["hit_points"] for r in mine),
            "rule_breaks": sum(r["rule_breaks"] for r in mine),
            # Missed deadlines (runner.record_missed) are the computer's fault, not the team's.
            "failed_weeks": sum(1 for r in mine if r["outcome"] not in ("accepted", "missed")),
            "missed_weeks": sum(1 for r in mine if r["outcome"] == "missed"),
            "stale_picks": sum(r["stale_picks"] for r in mine),
            "transfers": sum(r["transfers_made"] for r in mine),
            "captain_changes": sum(1 for r in mine if r["captain_changed"]),
            "chips": ",".join(r["chip"] for r in mine if r["chip"]),
            "input_tokens": sum(r["input_tokens"] for r in mine),
            "output_tokens": sum(r["output_tokens"] for r in mine),
        })
    averages = {r["gw"]: r["fpl_average"] for r in rows}
    if averages and all(a is not None for a in averages.values()):
        table.append({"team": "fpl-average", "kind": "reference", "model": "-", "memory": "-",
                      "gameweeks": len(averages), "points": sum(averages.values())})
    keys = list(table[0]) if table else []   # the first row is a team, so it has every column
    table.sort(key=lambda r: -r["points"])
    return [{k: r.get(k) for k in keys} for r in table]
