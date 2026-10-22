"""Copy the local data files into Supabase (a copy for the future website).

The files in data/ are the source of truth. If Supabase is unreachable, paused or not
configured, sync() prints a warning and returns False; it never stops a run.
`python run.py sync` can be re-run at any time and simply upserts everything again.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from . import config, memory, metrics
from .fetch import latest_bootstrap
from .files import read_csv, read_json, read_json_gz

BATCH_SIZE = 500

INT_COLUMNS = {"id", "total_pts", "minutes"}
FLOAT_COLUMNS = {"price", "form", "ppg", "xg", "xa", "ep_next", "own_pct"}


def _settings() -> tuple[str, str] | None:
    load_dotenv(config.PROJECT_ROOT / ".env")
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    return (url, key) if url and key else None


def _headers(key: str) -> dict:
    headers = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_"):
        # Legacy JWT-style keys must also be sent as a bearer token.
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _upsert(url: str, key: str, table: str, rows: list[dict], conflict: str) -> None:
    for start in range(0, len(rows), BATCH_SIZE):
        response = requests.post(
            f"{url}/rest/v1/{table}",
            params={"on_conflict": conflict},
            headers={**_headers(key), "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=rows[start:start + BATCH_SIZE],
            timeout=60,
        )
        response.raise_for_status()


def _delete(url: str, key: str, table: str, column: str, value) -> None:
    response = requests.delete(f"{url}/rest/v1/{table}", params={column: f"eq.{value}"},
                               headers=_headers(key), timeout=60)
    response.raise_for_status()


def _player_row(gw: int, row: dict) -> dict:
    """CSV values are text; turn them back into numbers (empty -> null)."""
    out = {"gw": gw}
    for column, value in row.items():
        if column in INT_COLUMNS:
            out[column] = int(value)
        elif column in FLOAT_COLUMNS:
            out[column] = float(value)
        elif column == "chance_next":
            out[column] = int(value) if value != "" else None
        else:
            out[column] = value
    return out


def push_everything() -> dict:
    """Upsert every local file into Supabase. Raises on any error. Returns row counts."""
    settings = _settings()
    if settings is None:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SECRET_KEY not set in .env")
    url, key = settings
    counts = {}

    log_path = config.RAW_DIR / "fetch_log.csv"
    if log_path.exists():
        rows = [{**r, "gw": int(r["gw"]), "bytes": int(r["bytes"]), "forced": r["forced"] == "True"}
                for r in read_csv(log_path)]
        _upsert(url, key, "fetches", rows, "file")
        counts["fetches"] = len(rows)

    latest = latest_bootstrap()
    if latest:
        events = read_json_gz(latest[0])["events"]
        rows = [{**{k: e.get(k) for k in ("id", "name", "deadline_time", "is_current", "is_next",
                                          "finished", "data_checked")},
                 # FPL shows 0 for gameweeks not played yet; store "no average" instead.
                 "average_entry_score": e.get("average_entry_score") if e.get("finished") else None}
                for e in events]
        _upsert(url, key, "gameweeks", rows, "id")
        counts["gameweeks"] = len(rows)

    counts["snapshots"] = counts["snapshot_players"] = 0
    for meta_path in sorted(config.SNAPSHOT_DIR.glob("gw*.meta.json")):
        meta = read_json(meta_path)
        gw = meta["gw"]
        _upsert(url, key, "snapshots", [{
            "gw": gw, "built_at": meta["built_at"], "filter": meta["filter"],
            "players_in_game": meta["players_in_game"], "players_in_snapshot": meta["players_in_snapshot"],
            "chars": meta["chars"], "est_tokens": meta["est_tokens"], "sources": meta["sources"],
        }], "gw")
        players = [_player_row(gw, r) for r in read_csv(config.SNAPSHOT_DIR / f"gw{gw}.csv")]
        # Replace the gameweek's rows, so a rebuilt snapshot never leaves old players behind.
        _delete(url, key, "snapshot_players", "gw", gw)
        _upsert(url, key, "snapshot_players", players, "gw,id")
        counts["snapshots"] += 1
        counts["snapshot_players"] += len(players)

    # Teams, decisions, results and memory (real runs only: data/, never data/mock/).
    for table, (rows, conflict) in experiment_rows(config.DATA_DIR).items():
        if rows:
            _upsert(url, key, table, rows, conflict)
        counts[table] = len(rows)
    return counts


def _json_files(folder: Path, pattern: str) -> list[Path]:
    return sorted(folder.glob(pattern)) if folder.exists() else []


def experiment_rows(base: Path) -> dict[str, tuple[list[dict], str]]:
    """Rows for the phase 6 tables, built from the run folder. {table: (rows, conflict columns)}."""
    tables = {"teams": ([{"id": p["team"], "kind": p["kind"], "model": p["model"], "memory": p["memory"]}
                         for p in metrics.participants()], "id")}

    decisions = []
    for path in _json_files(base / "decisions", "gw*/*.json"):
        d = read_json(path)
        answer = d.get("decision") or {}
        state_path = base / "teams" / d["team"] / f"gw{d['gw']}.json"
        squad = sorted(int(pid) for pid in read_json(state_path)["squad"]) if state_path.exists() else None
        decisions.append({
            "team": d["team"], "gw": d["gw"], "decided_at": d["decided_at"], "outcome": d["outcome"],
            "first_week": d["first_week"], "attempts": d["attempts"], "errors_by_attempt": d["errors_by_attempt"],
            "stale_picks": d["stale_picks"], "transfers": answer.get("transfers", []), "squad": squad,
            "starting_xi": answer.get("starting_xi"), "bench_order": answer.get("bench_order"),
            "captain": answer.get("captain"), "vice_captain": answer.get("vice_captain"), "chip": d["chip"],
            "reasoning": answer.get("reasoning"), "transfers_made": d["transfers_made"],
            "hit_points": d["hit_points"], "expected_points": d.get("expected_points"),
            "input_tokens": d["input_tokens"], "output_tokens": d["output_tokens"],
            "model_mismatch": d["model_mismatch"],
        })
    tables["decisions"] = (decisions, "team,gw")

    results = []
    for path in _json_files(base / "results", "gw*.json"):
        week = read_json(path)
        scores = {r["team"]: r for r in read_json(base / "scores" / path.name)["teams"]}
        for r in week["teams"]:
            score = scores[r["team"]]
            results.append({**{k: r.get(k) for k in metrics.CSV_FIELDS if k in RESULT_COLUMNS},
                            "players": score["players"], "transfer_points": score["transfers"],
                            "memory_detail": r.get("notes_detail") or r.get("lessons_detail")})
    tables["results"] = (results, "team,gw")

    standings_path = base / "results" / "standings.json"
    tables["standings"] = (read_json(standings_path) if standings_path.exists() else [], "team")

    notes, lessons = [], []
    for path in _json_files(base / "memory", "*/gw*.json"):
        m = read_json(path)
        notes.append({"team": path.parent.name, "gw": int(path.stem[2:]), "kind": m["kind"],
                      "notes": m.get("notes"), "lessons": m.get("lessons")})
    for path in _json_files(base / "memory", "*/latest.json"):
        m = read_json(path)
        for lesson in m.get("lessons", []):
            uses, average = memory.lesson_record(lesson)
            lessons.append({"team": path.parent.name, "id": lesson["id"], "text": lesson["text"],
                            "created_gw": lesson["created_gw"], "status": lesson["status"],
                            "ended_gw": lesson.get("ended_gw"), "uses": uses,
                            "average": round(average, 2) if average is not None else None,
                            "uses_detail": lesson["uses"]})
    tables["memory_notes"] = (notes, "team,gw")
    tables["lessons"] = (lessons, "team,id")
    return tables


# Columns of the results table that come straight from metrics.py's rows.
RESULT_COLUMNS = {
    "team", "gw", "points", "hit_points", "net_points", "rank", "fpl_average", "vs_average", "expected_points",
    "luck", "season_points", "season_expected", "season_rank", "outcome", "attempts", "rule_breaks",
    "error_codes", "stale_picks", "transfers_made", "captain_changed", "chip", "auto_subs", "bench_points",
}


def sync() -> bool:
    """Push to Supabase, but only warn on failure so a run is never blocked."""
    try:
        counts = push_everything()
    except Exception as error:  # noqa: BLE001 - any failure here must not stop the run
        print(f"  WARNING: Supabase sync failed ({error}). Local files are saved; "
              f"run `python run.py sync` later.")
        return False
    print("  Supabase sync OK: " + ", ".join(f"{t} {n}" for t, n in counts.items()))
    return True
