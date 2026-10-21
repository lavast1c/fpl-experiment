"""Build the weekly player table ("snapshot") that every agent receives, identically.

One row per player, built only from saved API responses (no network access here).
The same filter is applied for every team, and recorded in the snapshot's meta file.
"""

import math
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .files import write_csv, write_json

# Column order, used for the CSV file and the prompt table.
COLUMNS = [
    "id", "name", "club", "pos", "price", "form", "ppg", "total_pts", "minutes",
    "xg", "xa", "ep_next", "own_pct", "status", "chance_next", "news", "next_fixtures",
]

# Candidate filters for which players go into the snapshot. One is chosen and then fixed
# for the season (config.SNAPSHOT_FILTER, documented in METHODS.md).
FILTERS = {
    "all": lambda row: True,
    "played": lambda row: row["minutes"] > 0,
    "played_or_expected": lambda row: row["minutes"] > 0 or row["ep_next"] > 0,
    # Also keeps 0-minute players who are available and owned by at least 0.5% of managers
    # (often new signings, which the API does not flag).
    "played_or_owned": lambda row: row["minutes"] > 0 or (row["status"] == "a" and row["own_pct"] >= 0.5),
}


def _number(value) -> float:
    """The API sends most stats as strings like '5.2', and sometimes null."""
    return float(value) if value not in (None, "") else 0.0


def next_fixtures(team_id: int, fixtures: list[dict], short_names: dict[int, str],
                  from_gw: int, count: int, last_gw: int) -> str:
    """Describe a club's fixtures in the next `count` gameweeks.

    Example: 'GW9 ARS(H,4); GW10 -; GW11 CHE(A,3)+LIV(H,5)'
    '-' is a blank gameweek; '+' joins the games of a double gameweek.
    The number is FPL's difficulty rating (1 = easiest, 5 = hardest) for this club.
    """
    parts = []
    for gw in range(from_gw, min(from_gw + count, last_gw + 1)):
        games = sorted(
            (f for f in fixtures if f.get("event") == gw and team_id in (f["team_h"], f["team_a"])),
            key=lambda f: f.get("kickoff_time") or "",
        )
        described = []
        for f in games:
            if f["team_h"] == team_id:
                described.append(f"{short_names[f['team_a']]}(H,{f['team_h_difficulty']})")
            else:
                described.append(f"{short_names[f['team_h']]}(A,{f['team_a_difficulty']})")
        parts.append(f"GW{gw} " + ("+".join(described) if described else "-"))
    return "; ".join(parts)


def build_rows(bootstrap: dict, fixtures: list[dict], gw: int) -> list[dict]:
    """One row per player in the game, before any filter."""
    short_names = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    positions = {p["id"]: p["singular_name_short"] for p in bootstrap["element_types"]}
    last_gw = max(e["id"] for e in bootstrap["events"])
    fixture_text = {
        team_id: next_fixtures(team_id, fixtures, short_names, gw, config.FIXTURES_AHEAD, last_gw)
        for team_id in short_names
    }

    rows = []
    for p in bootstrap["elements"]:
        chance = p.get("chance_of_playing_next_round")
        rows.append({
            "id": p["id"],
            "name": p["web_name"],
            "club": short_names[p["team"]],
            "pos": positions[p["element_type"]],
            "price": p["now_cost"] / 10,
            "form": _number(p.get("form")),
            "ppg": _number(p.get("points_per_game")),
            "total_pts": p.get("total_points", 0),
            "minutes": p.get("minutes", 0),
            "xg": _number(p.get("expected_goals")),
            "xa": _number(p.get("expected_assists")),
            "ep_next": _number(p.get("ep_next")),
            "own_pct": _number(p.get("selected_by_percent")),
            "status": p.get("status", ""),
            "chance_next": "" if chance is None else chance,
            # Keep the table one line per player.
            "news": " ".join((p.get("news") or "").split()).replace("|", "/"),
            "next_fixtures": fixture_text[p["team"]],
        })
    # Goalkeepers, defenders, midfielders, forwards (the API's position order), then club, then id.
    position_order = {short: pos_id for pos_id, short in positions.items()}
    rows.sort(key=lambda r: (position_order[r["pos"]], r["club"], r["id"]))
    return rows


def apply_filter(rows: list[dict], filter_name: str) -> list[dict]:
    keep = FILTERS[filter_name]
    return [row for row in rows if keep(row)]


def prompt_table(rows: list[dict]) -> str:
    """The compact text form agents see: a header line, then one pipe-separated line per player."""
    lines = ["|".join(COLUMNS)]
    for row in rows:
        lines.append("|".join(_cell(row[c]) for c in COLUMNS))
    return "\n".join(lines) + "\n"


def _cell(value) -> str:
    """5.0 -> '5.0', 1.234 -> '1.23' (two decimals is plenty for these stats)."""
    if isinstance(value, float):
        return str(round(value, 2))
    return str(value)


def estimate_tokens(text: str) -> int:
    """Rough estimate only (see METHODS.md). Exact counts are recorded from real agent calls."""
    return math.ceil(len(text) / config.CHARS_PER_TOKEN)


def compare_filters(rows: list[dict]) -> list[dict]:
    """Player count and estimated size of the prompt table under each candidate filter."""
    results = []
    for name in FILTERS:
        kept = apply_filter(rows, name)
        table = prompt_table(kept)
        results.append({"filter": name, "players": len(kept),
                        "chars": len(table), "est_tokens": estimate_tokens(table)})
    return results


def save_snapshot(gw: int, rows: list[dict], filter_name: str, sources: dict,
                  out_dir: Path = config.SNAPSHOT_DIR) -> dict:
    """Write gw{N}.csv (data), gw{N}_table.txt (exact text agents get) and gw{N}.meta.json."""
    kept = apply_filter(rows, filter_name)
    table = prompt_table(kept)
    write_csv(out_dir / f"gw{gw}.csv", kept, COLUMNS)
    (out_dir / f"gw{gw}_table.txt").write_text(table, encoding="utf-8", newline="\n")
    meta = {
        "gw": gw,
        "season": config.SEASON,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filter": filter_name,
        "players_in_game": len(rows),
        "players_in_snapshot": len(kept),
        "chars": len(table),
        "est_tokens": estimate_tokens(table),
        "token_method": f"characters / {config.CHARS_PER_TOKEN} (estimate)",
        "fixtures_ahead": config.FIXTURES_AHEAD,
        "sources": sources,
    }
    write_json(out_dir / f"gw{gw}.meta.json", meta)
    return meta
