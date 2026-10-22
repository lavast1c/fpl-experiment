"""Our own expected-points predictor ("xP"), built only from FPL's public API data.

Why: FPL's own `ep_next` is a rough number and FPL doesn't publish how it is made. We need a fairer
yardstick for the luck-adjusted score and the verified-memory lesson checks, and a stronger simple bot.
The predictor is fixed for the season (METHODS.md, 2026-10-22). Agents never see it: their player
table is unchanged.

For one player and one fixture, the prediction adds up:
    appearance points   from how often he played 60+ / 1-59 minutes in his team's last 4 matches
    goals and assists   his expected goals (xG) and assists (xA) per 90 minutes this season,
                        scaled by his expected minutes and by how many goals his team should score
                        in this fixture (its attack vs the opponent's defence, home or away)
    clean sheet         chance his team concedes 0 (Poisson) times the clean-sheet points,
                        if he plays long enough to earn one
    goals conceded      the points per goal conceded seen this season for his position,
                        times the goals his team should concede while he is on the pitch
    everything else     bonus, saves, defensive contributions and cards: his own average per 90
A double gameweek adds two fixtures; a blank gameweek is 0.

Every point value and threshold is read from the API (`game_config.scoring`) or measured from this
season's official point breakdowns (`event/{gw}/live/` "explain"), never typed in from memory.
Rates are shrunk towards the position or league average, so a few early games don't dominate.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .files import read_json, read_json_gz, write_csv

XPOINTS_DIR = config.DATA_DIR / "xpoints"
TEAM_PRIOR_MATCHES = 4     # a team's attack and defence count as if it also played 4 average matches
RECENT_MATCHES = 4         # expected minutes come from the team's last 4 matches
HORIZON = 3                # gameweeks ahead for the 3-week total (used by the stats bot)
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
MAIN_STATS = {"minutes", "goals_scored", "assists", "clean_sheets", "goals_conceded"}
ASSIST_PRIOR_XA = 10       # each position's assists per xA count as if it also had 10 xA at the all-positions rate


@dataclass(frozen=True)
class Settings:
    """Choices inside the predictor. The defaults are the version fixed on 2026-10-22; the other
    options were added for the past-season test (xpoints_past.py) and are off unless chosen."""
    prior_minutes: int = 450              # a player's per-90 rates count as if he also played this many average minutes
    conceded_all_goals: bool = False      # points per goal conceded: divide by every goal conceded,
                                          # not only goals in matches that cost points (breakdowns list only those)
    scale_assists: bool = False           # scale xA by FPL assists per xA for his position this season
                                          # (FPL awards assists more generously, forwards' most of all)
    clean_sheet_on_pitch: bool = False    # clean-sheet chance only for the minutes a 60+ minute player is usually on
    season_minutes_weight: float = 0.0    # blend the last 4 matches' playing time with the whole season's


@dataclass
class PlayerHistory:
    team: int
    position: str
    matches: list = field(default_factory=list)   # (kickoff order, minutes) for each team match he was listed in
    minutes: int = 0
    xg: float = 0.0
    xa: float = 0.0
    other_points: int = 0                         # bonus, saves, defensive contributions, cards...


@dataclass
class History:
    """Everything the predictor learns from finished gameweeks before the one being predicted."""
    players: dict[int, PlayerHistory]
    team_matches: dict[int, list]                 # team -> [(order, fixture id)] finished matches
    attack: dict[int, float]                      # team -> xG per match (shrunk)
    defence: dict[int, float]                     # team -> xG conceded per match (shrunk)
    league_xg: float                              # average xG per team per match
    home_mult: float                              # home teams' xG relative to the average
    away_mult: float
    rates: dict[int, tuple[float, float, float]]  # player -> (xG, xA, other points) per 90, shrunk
    conceded_points: dict[str, float]             # position -> points per goal conceded (measured)
    long_play: int                                # minutes needed for the full appearance points (measured)
    clean_sheet_minutes: int                      # minutes needed for a clean sheet (measured)
    assists_per_xa: dict = field(default_factory=dict)  # position -> FPL assists per expected assist (measured)
    long_play_average: float = 90.0               # average minutes of a 60+ minute appearance (measured)
    settings: Settings = Settings()


def live_file(gw: int, raw_dir: Path = config.RAW_DIR) -> Path | None:
    files = sorted((raw_dir / f"gw{gw}").glob(f"event-{gw}-live_*.json.gz"))
    return files[-1] if files else None


def load_history(before_gw: int, bootstrap: dict, fixtures: list[dict], raw_dir: Path = config.RAW_DIR,
                 settings: Settings = Settings()) -> History:
    scoring = bootstrap["game_config"]["scoring"]
    teams_of = {p["id"]: p["team"] for p in bootstrap["elements"]}
    position_of = {p["id"]: POSITIONS[p["element_type"]] for p in bootstrap["elements"]}
    fixture_by_id = {f["id"]: f for f in fixtures}
    order = {f["id"]: (f["event"] or 99, f["kickoff_time"] or "", f["id"]) for f in fixtures}
    finished = [f for f in fixtures if f["event"] and f["event"] < before_gw and f["finished"]]

    players: dict[int, PlayerHistory] = {}
    team_gw_xg = defaultdict(float)               # (team, gw) -> xG, all that gameweek's fixtures together
    conceded = defaultdict(lambda: [0, 0, 0])     # position -> [points, goals in matches that cost points, all goals]
    fpl_assists = defaultdict(int)                # position -> official assists
    long_play_minutes, clean_sheet_minutes, missing = [], [], []
    for gw in range(1, before_gw):
        path = live_file(gw, raw_dir)
        if path is None:
            missing.append(gw)
            continue
        for e in read_json_gz(path)["elements"]:
            pid = e["id"]
            if pid not in teams_of:
                continue
            h = players.setdefault(pid, PlayerHistory(teams_of[pid], position_of[pid]))
            stats = e["stats"]
            h.minutes += stats["minutes"]
            h.xg += float(stats["expected_goals"])
            h.xa += float(stats["expected_assists"])
            fpl_assists[h.position] += stats["assists"]
            conceded[h.position][2] += stats["goals_conceded"]
            team_gw_xg[(h.team, gw)] += float(stats["expected_goals"])
            for part in e["explain"]:
                if part["fixture"] not in fixture_by_id:
                    continue
                by_stat = {s["identifier"]: s for s in part["stats"]}
                minutes = by_stat.get("minutes", {}).get("value", 0)
                h.matches.append((order[part["fixture"]], minutes))
                h.other_points += sum(s["points"] for k, s in by_stat.items() if k not in MAIN_STATS)
                if by_stat.get("minutes", {}).get("points", 0) == scoring["long_play"]:
                    long_play_minutes.append(minutes)
                if by_stat.get("clean_sheets", {}).get("points", 0) > 0:
                    clean_sheet_minutes.append(minutes)
                if "goals_conceded" in by_stat:
                    conceded[h.position][0] += by_stat["goals_conceded"]["points"]
                    conceded[h.position][1] += by_stat["goals_conceded"]["value"]

    if missing:
        print(f"  xP: no official points saved for gameweek(s) {missing}; they are left out.")

    # Team attack and defence from xG, one row per finished match.
    matches_in_gw = defaultdict(int)
    for f in finished:
        matches_in_gw[(f["team_h"], f["event"])] += 1
        matches_in_gw[(f["team_a"], f["event"])] += 1
    xg_for, xg_against, home_xg, away_xg = defaultdict(list), defaultdict(list), [], []
    team_matches = defaultdict(list)
    for f in finished:
        h_xg = team_gw_xg[(f["team_h"], f["event"])] / matches_in_gw[(f["team_h"], f["event"])]
        a_xg = team_gw_xg[(f["team_a"], f["event"])] / matches_in_gw[(f["team_a"], f["event"])]
        xg_for[f["team_h"]].append(h_xg); xg_against[f["team_h"]].append(a_xg)
        xg_for[f["team_a"]].append(a_xg); xg_against[f["team_a"]].append(h_xg)
        home_xg.append(h_xg); away_xg.append(a_xg)
        team_matches[f["team_h"]].append((order[f["id"]], f["id"]))
        team_matches[f["team_a"]].append((order[f["id"]], f["id"]))
    league_xg = (sum(home_xg) + sum(away_xg)) / max(1, len(home_xg) + len(away_xg))
    shrink = lambda values: (sum(values) + league_xg * TEAM_PRIOR_MATCHES) / (len(values) + TEAM_PRIOR_MATCHES)
    team_ids = {t["id"] for t in bootstrap["teams"]}

    # Player rates per 90, shrunk towards the position average.
    totals = defaultdict(lambda: [0, 0.0, 0.0, 0])
    for h in players.values():
        t = totals[h.position]
        t[0] += h.minutes; t[1] += h.xg; t[2] += h.xa; t[3] += h.other_points
    prior = {pos: (t[1] / t[0] * 90, t[2] / t[0] * 90, t[3] / t[0] * 90) if t[0] else (0, 0, 0)
             for pos, t in totals.items()}
    rates = {}
    prior_90s = settings.prior_minutes / 90
    for pid, h in players.items():
        px, pa, po = prior.get(h.position, (0, 0, 0))
        denominator = h.minutes / 90 + prior_90s
        rates[pid] = ((h.xg + px * prior_90s) / denominator,
                      (h.xa + pa * prior_90s) / denominator,
                      (h.other_points + po * prior_90s) / denominator)

    goals_index = 2 if settings.conceded_all_goals else 1
    # FPL assists per xA: each position's own rate, shrunk towards the rate over all positions.
    all_rate = sum(fpl_assists.values()) / sum(t[2] for t in totals.values()) if totals else 1.0
    assists_per_xa = {pos: (fpl_assists[pos] + all_rate * ASSIST_PRIOR_XA) / (t[2] + ASSIST_PRIOR_XA)
                      for pos, t in totals.items()}
    return History(
        players=players, team_matches=team_matches,
        attack={t: shrink(xg_for[t]) for t in team_ids}, defence={t: shrink(xg_against[t]) for t in team_ids},
        league_xg=league_xg,
        home_mult=(sum(home_xg) / len(home_xg)) / league_xg if home_xg else 1.0,
        away_mult=(sum(away_xg) / len(away_xg)) / league_xg if away_xg else 1.0,
        rates=rates,
        conceded_points={pos: (c[0] / c[goals_index] if c[goals_index] else 0.0) for pos, c in conceded.items()},
        long_play=min(long_play_minutes) if long_play_minutes else 60,
        clean_sheet_minutes=min(clean_sheet_minutes) if clean_sheet_minutes else 60,
        assists_per_xa=assists_per_xa,
        long_play_average=sum(long_play_minutes) / len(long_play_minutes) if long_play_minutes else 90.0,
        settings=settings,
    )


def playing_time(history: History, pid: int) -> tuple[float, float, float]:
    """(chance of a long appearance, chance of a short one, expected minutes) from the team's last matches,
    blended with every match he was listed for this season if Settings.season_minutes_weight is set."""
    h = history.players.get(pid)
    if h is None:
        return 0.0, 0.0, 0.0
    recent_ids = {order for order, _ in sorted(history.team_matches.get(h.team, []))[-RECENT_MATCHES:]}
    minutes_by_match = {order: minutes for order, minutes in h.matches}
    recent = [minutes_by_match.get(order, 0) for order in recent_ids]
    if not recent:
        return 0.0, 0.0, 0.0

    def summary(minutes: list) -> tuple[float, float, float]:
        long_ = sum(m >= history.long_play for m in minutes) / len(minutes)
        any_ = sum(m > 0 for m in minutes) / len(minutes)
        return long_, any_ - long_, sum(minutes) / len(minutes)

    weight = history.settings.season_minutes_weight
    if not weight:
        return summary(recent)
    season = summary([minutes for _, minutes in h.matches])
    return tuple((1 - weight) * r + weight * s for r, s in zip(summary(recent), season))


def fixture_points(history: History, scoring: dict, pid: int, opponent: int, home: bool) -> float:
    """Expected points for one fixture, if the player is fit."""
    h = history.players.get(pid)
    if h is None:
        return 0.0
    p_long, p_short, minutes = playing_time(history, pid)
    if minutes == 0:
        return 0.0
    pos, mu = h.position, history.league_xg
    xg90, xa90, other90 = history.rates[pid]
    venue, opp_venue = (history.home_mult, history.away_mult) if home else (history.away_mult, history.home_mult)
    goals_for = mu * (history.attack[h.team] / mu) * (history.defence[opponent] / mu) * venue
    goals_against = mu * (history.attack[opponent] / mu) * (history.defence[h.team] / mu) * opp_venue
    fixture_factor = goals_for / history.attack[h.team]          # this fixture vs the team's average match
    share = minutes / 90
    settings = history.settings
    assist_scale = history.assists_per_xa.get(pos, 1.0) if settings.scale_assists else 1.0
    # Goals against while he is on the pitch, for the clean sheet (a player subbed off at 70 needs only 70).
    on_pitch = history.long_play_average / 90 if settings.clean_sheet_on_pitch else 1.0

    points = scoring["long_play"] * p_long + scoring["short_play"] * p_short
    points += xg90 * share * fixture_factor * scoring["goals_scored"][pos]
    points += xa90 * share * fixture_factor * assist_scale * scoring["assists"]
    p_clean_sheet_minutes = p_long if history.clean_sheet_minutes >= history.long_play else p_long + p_short
    points += p_clean_sheet_minutes * math.exp(-goals_against * on_pitch) * scoring["clean_sheets"][pos]
    points += history.conceded_points.get(pos, 0.0) * goals_against * share
    points += other90 * share
    return points


def chance_of_playing(element: dict) -> float:
    """FPL's chance of playing next round as a fraction (empty means no news)."""
    chance = element.get("chance_of_playing_next_round")
    if chance is None:
        return 0.0 if element.get("status", "a") in {"i", "s", "u", "n"} else 1.0
    return chance / 100


def predict(gw: int, bootstrap: dict, fixtures: list[dict], raw_dir: Path = config.RAW_DIR,
            settings: Settings = Settings()) -> dict[int, dict]:
    """Per player: xp_if_fit for gameweek gw, xp (times FPL's chance of playing), and the 3-gameweek total if fit."""
    history = load_history(gw, bootstrap, fixtures, raw_dir, settings)
    scoring = bootstrap["game_config"]["scoring"]
    upcoming = defaultdict(list)                  # (team, gw) -> [(opponent, home)]
    for f in fixtures:
        if f["event"] and gw <= f["event"] < gw + HORIZON:
            upcoming[(f["team_h"], f["event"])].append((f["team_a"], True))
            upcoming[(f["team_a"], f["event"])].append((f["team_h"], False))
    out = {}
    for p in bootstrap["elements"]:
        per_gw = [sum(fixture_points(history, scoring, p["id"], opp, home) for opp, home in upcoming[(p["team"], g)])
                  for g in range(gw, gw + HORIZON)]
        out[p["id"]] = {"xp_if_fit": round(per_gw[0], 2), "xp": round(per_gw[0] * chance_of_playing(p), 2),
                        "xp_3gw_if_fit": round(sum(per_gw), 2)}
    return out


def for_snapshot(gw: int, raw_dir: Path = config.RAW_DIR) -> dict[int, dict]:
    """Predictions from exactly the data the agents' snapshot for gameweek gw was built from."""
    meta = read_json(config.SNAPSHOT_DIR / f"gw{gw}.meta.json")
    bootstrap = read_json_gz(raw_dir / meta["sources"]["bootstrap"])
    fixtures = read_json_gz(raw_dir / meta["sources"]["fixtures"])
    return predict(meta["gw"], bootstrap, fixtures, raw_dir)


def save(gw: int, predictions: dict[int, dict], bootstrap: dict, folder: Path = XPOINTS_DIR) -> Path:
    elements = {p["id"]: p for p in bootstrap["elements"]}
    rows = [{"id": pid, "name": elements[pid]["web_name"], **v, "ep_next": float(elements[pid]["ep_next"] or 0)}
            for pid, v in sorted(predictions.items(), key=lambda kv: -kv[1]["xp"])]
    path = folder / f"gw{gw}.csv"
    write_csv(path, rows, ["id", "name", "xp", "xp_if_fit", "xp_3gw_if_fit", "ep_next"])
    return path
