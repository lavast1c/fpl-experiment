"""Score a team's gameweek exactly as FPL does.

Player points come straight from FPL (`event/{gw}/live/`, each player's official total_points).
This file only does the team-level part:
- automatic substitutions for starters who played 0 minutes
- captain points (x2, or x3 with triple captain), passed to the vice-captain if the captain didn't play
- bench boost (all 15 players count, so there are no automatic substitutions)
Transfer hits are subtracted by the caller (they come from the validator).

The result was checked against official scores of real public teams (see METHODS.md).
"""

from collections import Counter
from dataclasses import dataclass, field

from .rules import Rules
from .team import Lineup


@dataclass(frozen=True)
class LivePlayer:
    minutes: int
    points: int


def live_from_api(live: dict) -> dict[int, LivePlayer]:
    """Each player's minutes and official points for one gameweek (all fixtures added together)."""
    return {e["id"]: LivePlayer(e["stats"]["minutes"], e["stats"]["total_points"]) for e in live["elements"]}


@dataclass
class ScoreResult:
    points: int                                   # gameweek points before transfer hits
    counted: list[int]                            # players whose points count
    captain: int | None                           # who actually got the armband (None if neither played)
    multiplier: int                               # 2, or 3 with triple captain
    auto_subs: list[tuple[int, int]] = field(default_factory=list)   # (player out, player in)
    bench_points: int = 0                         # points left on the bench


def _played(pid: int, live: dict[int, LivePlayer]) -> bool:
    return pid in live and live[pid].minutes > 0


def _formation_ok(xi: list[int], positions: dict[int, int], rules: Rules) -> bool:
    counts = Counter(positions[pid] for pid in xi)
    return all(p.min_play <= counts[p.id] <= p.max_play for p in rules.positions.values())


def auto_subs(xi: list[int], bench: list[int], positions: dict[int, int], live: dict[int, LivePlayer],
              rules: Rules) -> tuple[list[int], list[tuple[int, int]]]:
    """Replace starters who didn't play, going through the XI in order.

    Each one is replaced by the highest-priority bench player who played and keeps the formation
    valid. A goalkeeper can only be replaced by the bench goalkeeper, and an outfield player only
    by an outfield player.
    """
    goalkeeper = rules.position_by_short("GKP").id
    xi = list(xi)
    used: set[int] = set()
    subs = []
    for starter in list(xi):
        if _played(starter, live):
            continue
        for sub in bench:
            if sub in used or not _played(sub, live):
                continue
            if (positions[starter] == goalkeeper) != (positions[sub] == goalkeeper):
                continue
            trial = [sub if pid == starter else pid for pid in xi]
            if _formation_ok(trial, positions, rules):
                xi, used = trial, used | {sub}
                subs.append((starter, sub))
                break
    return xi, subs


def score(lineup: Lineup, chip: str | None, positions: dict[int, int], live: dict[int, LivePlayer],
          rules: Rules) -> ScoreResult:
    """Points for one team in one gameweek. `positions` maps player id -> position id."""
    points_of = lambda pid: live[pid].points if pid in live else 0

    if chip == "bboost":
        counted, subs = list(lineup.starting_xi) + list(lineup.bench_order), []
    else:
        counted, subs = auto_subs(lineup.starting_xi, lineup.bench_order, positions, live, rules)

    multiplier = 3 if chip == "3xc" else 2
    if _played(lineup.captain, live) and lineup.captain in counted:
        captain = lineup.captain
    elif _played(lineup.vice_captain, live) and lineup.vice_captain in counted:
        captain = lineup.vice_captain
    else:
        captain = None

    points = sum(points_of(pid) for pid in counted)
    if captain is not None:
        points += (multiplier - 1) * points_of(captain)
    squad = set(lineup.starting_xi) | set(lineup.bench_order)
    bench_points = sum(points_of(pid) for pid in squad - set(counted))
    return ScoreResult(points, counted, captain, multiplier, subs, bench_points)
