"""Copy the local data files into Supabase (a copy for the future website).

The files in data/ are the source of truth. If Supabase is unreachable, paused or not
configured, sync() prints a warning and returns False; it never stops a run.
`python run.py sync` can be re-run at any time and simply upserts everything again.
"""

import os

import requests
from dotenv import load_dotenv

from . import config
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
        rows = [{k: e.get(k) for k in ("id", "name", "deadline_time", "is_current", "is_next",
                                       "finished", "data_checked")} for e in events]
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
    return counts


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
