"""One-off check: does our scorer reproduce FPL's official scores for real public teams?

This is the only code in the project that reads individual managers' teams, and it is careful:
- teams are chosen by a random position in the Overall league, never by name
- names are removed the moment a response arrives; only team numbers and picks are kept
- everything goes to data/test_cache/ (git-ignored) and is deleted at the end (unless --keep)
- results are printed as "team #3", never with a team number or name
Player points come from the public `event/{gw}/live/` data, which is saved normally.
"""

import secrets
import shutil
import time
from collections import Counter

import requests

from . import config, fetch
from .files import read_json_gz, write_json_gz
from .rules import MANUAL_RULES, load_rules
from .scorer import live_from_api, score
from .team import Lineup

PAGE_SIZE = 50                      # teams per page of the Overall league table
CHIPS = ("wildcard", "freehit", "bboost", "3xc")


# --- downloading, with names removed ------------------------------------------------------

def _cached(endpoint: str, strip):
    """Read from the test cache, or download (rate-limited, no cookies), strip and save."""
    path = config.TEST_CACHE_DIR / f"{fetch.endpoint_slug(endpoint)}.json.gz"
    if path.exists():
        return read_json_gz(path)
    data = strip(fetch._download(endpoint, requests.get, time.sleep, test_only=True))
    write_json_gz(path, data)
    return data


def _strip_standings(data: dict) -> dict:
    if data["league"]["id"] != 314:
        raise ValueError("Expected the Overall league (id 314).")
    return {"entries": [{"entry": r["entry"], "rank": r["rank"]} for r in data["standings"]["results"]]}


def _strip_history(data: dict) -> dict:
    keep = ("event", "points", "total_points", "event_transfers", "event_transfers_cost", "points_on_bench")
    return {"current": [{k: row.get(k) for k in keep} for row in data["current"]],
            "chips": [{"name": c["name"], "event": c["event"]} for c in data.get("chips", [])]}


def _strip_picks(data: dict) -> dict:
    keep = ("element", "position", "multiplier", "is_captain", "is_vice_captain", "element_type")
    return {"active_chip": data.get("active_chip"),
            "automatic_subs": [{"element_in": s["element_in"], "element_out": s["element_out"]}
                               for s in data.get("automatic_subs", [])],
            "entry_history": {k: data["entry_history"].get(k) for k in ("event", "points", "event_transfers_cost",
                                                                        "points_on_bench")},
            "picks": [{k: p.get(k) for k in keep} for p in data["picks"]]}


# --- choosing teams -----------------------------------------------------------------------

def sample_teams(total_players: int, how_many: int) -> list[int]:
    """Team numbers at random positions in the Overall league table."""
    rng = secrets.SystemRandom()   # not seeded: the choice is never reproducible or recorded
    teams = []
    attempts = 0
    while len(teams) < how_many and attempts < how_many * 3:
        attempts += 1
        rank = rng.randint(1, total_players)
        page, index = (rank - 1) // PAGE_SIZE + 1, (rank - 1) % PAGE_SIZE
        try:
            entries = _cached(f"leagues-classic/314/standings/?page_standings={page}", _strip_standings)["entries"]
        except (requests.RequestException, ValueError) as error:
            print(f"  skipped a page ({error.__class__.__name__})")
            continue
        if index < len(entries) and entries[index]["entry"] not in teams:
            teams.append(entries[index]["entry"])
    return teams


def choose_teams(histories: dict[int, dict], finished: set[int], how_many: int) -> list[int]:
    """Make sure every chip used by any sampled team is covered, then fill up at random."""
    rng = secrets.SystemRandom()
    chosen = []
    for chip in CHIPS:
        users = [t for t, h in histories.items()
                 if t not in chosen and any(c["name"] == chip and c["event"] in finished for c in h["chips"])]
        if users:
            chosen.append(rng.choice(users))
    rest = [t for t in histories if t not in chosen]
    rng.shuffle(rest)
    return (chosen + rest)[:how_many]


# --- the check ----------------------------------------------------------------------------

def check_free_transfers(history: dict, rules, finished: set[int]) -> tuple[int, list[str]]:
    """Replay a team's free transfers week by week with our rules and compare each week's hit
    cost with the official one. Returns (weeks checked, problems)."""
    chips = {c["event"]: c["name"] for c in history["chips"]}
    free = None
    checked, problems = 0, []
    for row in sorted(history["current"], key=lambda r: r["event"]):
        gw, made = row["event"], row["event_transfers"]
        if gw not in finished:
            break
        if free is None:                                  # first week: squad picked for free
            expected, free = 0, MANUAL_RULES["new_team_free_transfers"]["value"]
        elif chips.get(gw) in ("wildcard", "freehit"):    # free transfers kept, none gained
            expected = 0
        else:
            expected = max(0, made - free) * rules.hit_cost
            free = min(rules.max_free_transfers, max(0, free - made) + rules.free_transfers_per_gw)
        checked += 1
        if expected != row["event_transfers_cost"]:
            problems.append(f"GW{gw}: {made} transfers, expected hit {expected}, official {row['event_transfers_cost']}")
    return checked, problems

def _undo_auto_subs(picks: list[dict], subs: list[dict]) -> list[dict]:
    """FPL shows picks AFTER its automatic substitutions. Put the starters back, so our scorer
    has to make the substitutions itself and can be checked.

    FPL swaps each starter with his substitute, then re-sorts the XI by position
    (GK, DEF, MID, FWD). So we swap back and re-sort the XI the same way. What can't be recovered
    is the original order of two starters in the SAME position, so the check compares which
    players came on and the position of each player taken off, not the exact pairs.
    """
    by_element = {p["element"]: dict(p) for p in picks}
    for sub in reversed(subs):
        out, came_in = by_element[sub["element_out"]], by_element[sub["element_in"]]
        out["position"], came_in["position"] = came_in["position"], out["position"]
    restored = sorted(by_element.values(), key=lambda p: p["position"])
    xi = sorted(restored[:11], key=lambda p: p["element_type"])   # stable: keeps order within a position
    for slot, pick in enumerate(xi + restored[11:], start=1):
        pick["position"] = slot
    return xi + restored[11:]


def _lineup(picks: list[dict]) -> Lineup:
    ordered = sorted(picks, key=lambda p: p["position"])
    captain = next(p["element"] for p in ordered if p["is_captain"])
    vice = next(p["element"] for p in ordered if p["is_vice_captain"])
    return Lineup([p["element"] for p in ordered[:11]], [p["element"] for p in ordered[11:]], captain, vice)


def run(sample_size: int, team_count: int, keep: bool) -> bool:
    latest = fetch.latest_bootstrap()
    if latest is None:
        raise SystemExit("Run `python run.py fetch` first.")
    bootstrap = read_json_gz(latest[0])
    finished = {e["id"] for e in bootstrap["events"] if e["finished"] and e["data_checked"]}
    rules = load_rules()
    print(f"Finished gameweeks: {sorted(finished)}")

    # Re-running with --keep reuses the same teams from the cache instead of sampling new ones.
    chosen_file = config.TEST_CACHE_DIR / "chosen.json.gz"
    if chosen_file.exists():
        teams = read_json_gz(chosen_file)
        histories = {t: _cached(f"entry/{t}/history/", _strip_history) for t in teams}
        print(f"Re-using the {len(teams)} teams in the test cache")
    else:
        print(f"Sampling {sample_size} random teams from the Overall league ...")
        sampled = sample_teams(bootstrap["total_players"], sample_size)
        histories = {}
        for team in sampled:
            try:
                histories[team] = _cached(f"entry/{team}/history/", _strip_history)
            except requests.RequestException:
                print("  skipped a team (history unavailable)")
        teams = choose_teams(histories, finished, team_count)
        write_json_gz(chosen_file, teams)
    print(f"Checking {len(teams)} teams")

    lives = {gw: live_from_api(fetch.get(f"event/{gw}/live/", gw)) for gw in sorted(finished)}

    checked, mismatches = 0, []
    coverage = Counter()
    for number, team in enumerate(teams, start=1):
        for row in histories[team]["current"]:
            gw = row["event"]
            if gw not in finished:
                continue
            picks = _cached(f"entry/{team}/event/{gw}/picks/", _strip_picks)
            lineup = _lineup(_undo_auto_subs(picks["picks"], picks["automatic_subs"]))
            positions = {p["element"]: p["element_type"] for p in picks["picks"]}
            chip = picks["active_chip"] if picks["active_chip"] in CHIPS else None
            ours = score(lineup, chip, positions, lives[gw], rules)
            official = picks["entry_history"]["points"]
            official_subs = [(s["element_out"], s["element_in"]) for s in picks["automatic_subs"]]
            checked += 1
            coverage[chip or "no chip"] += 1
            coverage["with auto-subs"] += bool(official_subs)
            coverage["vice-captain promoted"] += ours.captain == lineup.vice_captain
            coverage["with a hit"] += bool(picks["entry_history"]["event_transfers_cost"])
            problems = []
            if ours.points != official:
                problems.append(f"points ours {ours.points} vs official {official}")
            # Same players brought on, and players of the same positions taken off (see _undo_auto_subs).
            same_in = sorted(i for _, i in ours.auto_subs) == sorted(i for _, i in official_subs)
            same_out = (sorted(positions[o] for o, _ in ours.auto_subs)
                        == sorted(positions[o] for o, _ in official_subs))
            exact_pairs = sorted(ours.auto_subs) == sorted(official_subs)
            coverage["auto-subs exact pairs"] += bool(official_subs) and exact_pairs
            if not (same_in and same_out):
                problems.append(f"auto-subs ours {ours.auto_subs} vs official {official_subs}")
            if ours.bench_points != picks["entry_history"]["points_on_bench"]:
                problems.append(f"bench points ours {ours.bench_points} vs official "
                                f"{picks['entry_history']['points_on_bench']}")
            if problems:
                mismatches.append(f"team #{number} GW{gw} (chip {chip}): " + "; ".join(problems))

    print(f"\nTeam-weeks checked: {checked}")
    print("Coverage: " + ", ".join(f"{k} {v}" for k, v in sorted(coverage.items())))
    if mismatches:
        print(f"MISMATCHES ({len(mismatches)}):")
        for line in mismatches:
            print("  " + line)
    else:
        print("All points, auto-subs and bench points match FPL's official figures exactly.")

    # Free transfers and hits, replayed for every team in the cache (histories only, no extra downloads).
    ft_weeks, ft_problems = 0, []
    all_histories = [read_json_gz(p) for p in config.TEST_CACHE_DIR.glob("entry-*-history.json.gz")]
    for number, history in enumerate(all_histories, start=1):
        weeks, problems = check_free_transfers(history, rules, finished)
        ft_weeks += weeks
        ft_problems += [f"history #{number} {p}" for p in problems]
    print(f"\nFree transfers and hits replayed: {ft_weeks} team-weeks from {len(all_histories)} teams, "
          f"{len(ft_problems)} differences")
    for line in ft_problems:
        print("  " + line)
    mismatches += ft_problems

    if not keep:
        shutil.rmtree(config.TEST_CACHE_DIR, ignore_errors=True)
        print("Test cache deleted.")
    return not mismatches
