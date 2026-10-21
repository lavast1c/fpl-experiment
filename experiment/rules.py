"""The FPL rules the validator and scorer use, and where each one comes from.

Rules come from two places:
1. VERIFIED: read from the API's own settings (data/rules/{season}_api_rules.json, saved by
   `run.py snapshot`). These are loaded by load_rules().
2. MANUAL: rules the API does not publish. They are written once here, in MANUAL_RULES, and were
   confirmed by hand on the FPL website (date in CONFIRMED_ON and METHODS.md). Never hardcode an
   FPL rule anywhere else in the code.

All money is in tenths of £m, as the API uses (1000 = £100.0m), so there are no rounding errors.
"""

from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .files import read_json

# --- Rules the API does not publish (confirmed by hand on the FPL site) ---------------------
CONFIRMED_ON = "2026-10-22"

MANUAL_RULES = {
    "hit_cost": {
        "value": 4,
        "rule": "Each transfer beyond your free transfers costs 4 points.",
    },
    "free_transfers_per_gameweek": {
        "value": 1,
        "rule": "You gain 1 free transfer per gameweek (unused ones are saved, up to the maximum).",
    },
    "max_free_transfers": {
        "value": None,  # filled from the API: 1 + game_settings.max_extra_free_transfers
        "rule": "You can save up to 5 free transfers (we read 1 + max_extra_free_transfers = 1 + 4 from the API, "
                "but the meaning of that setting is not documented).",
    },
    "selling_price_rounding": {
        "value": "down",
        "rule": "When selling after a price rise you keep half the rise (API: transfers_sell_on_fee 0.5), "
                "rounded DOWN to the nearest £0.1m. A price fall is passed on in full.",
    },
    "one_chip_per_gameweek": {
        "value": True,
        "rule": "Only one chip can be played in a gameweek.",
    },
    "chip_week_free_transfers": {
        "value": "kept, none gained",
        "rule": "In a wildcard or free hit week, saved free transfers are kept but no new free transfer is gained "
                "(corrected 2026-10-22).",
    },
    "free_hit_reverts": {
        "value": True,
        "rule": "After a free hit, the squad (and money in the bank) goes back to what it was before.",
    },
    "new_team_free_transfers": {
        "value": 1,
        "rule": "A team that joins mid-season picks its first squad for free, then has 1 free transfer for its next gameweek.",
    },
    "transfer_chips_not_in_first_week": {
        "value": True,
        "rule": "Wildcard and free hit can't be played in a team's first gameweek (its squad is already free to pick).",
    },
    "bench_goalkeeper_first": {
        "value": True,
        "rule": "The substitute goalkeeper always sits in the first bench slot; the order of the 3 outfield subs is the manager's choice.",
    },
}

# How many times an agent may retry after an illegal answer (brief section 4.3, METHODS.md).
MAX_RETRIES = 2
FIRST_WEEK_EXTRA_RETRIES = 3   # extra retries only when building the first squad (decided 2026-10-22)


@dataclass(frozen=True)
class Position:
    id: int
    short: str          # GKP / DEF / MID / FWD
    squad_count: int    # how many the 15-man squad must have
    min_play: int       # minimum in the starting XI
    max_play: int       # maximum in the starting XI


@dataclass(frozen=True)
class Chip:
    id: int             # unique per half-season copy (e.g. first-half wildcard vs second-half wildcard)
    name: str           # wildcard / freehit / bboost / 3xc
    start_gw: int
    stop_gw: int
    kind: str           # "transfer" or "team"


@dataclass(frozen=True)
class Rules:
    squad_size: int
    xi_size: int
    club_limit: int
    budget: int                 # tenths of £m
    sell_on_fee: float          # share of a price rise you keep when selling
    max_free_transfers: int
    positions: dict[int, Position]
    chips: list[Chip] = field(default_factory=list)
    hit_cost: int = MANUAL_RULES["hit_cost"]["value"]
    free_transfers_per_gw: int = MANUAL_RULES["free_transfers_per_gameweek"]["value"]

    def position_by_short(self, short: str) -> Position:
        return next(p for p in self.positions.values() if p.short == short)


def rules_from_api(api: dict) -> Rules:
    """Build Rules from the saved API settings (the dict written by api_rules.extract_rules)."""
    settings = api["game_settings"]
    positions = {
        p["id"]: Position(p["id"], p["singular_name_short"], p["squad_select"], p["squad_min_play"], p["squad_max_play"])
        for p in api["positions"]
    }
    chips = [Chip(c["id"], c["name"], c["start_event"], c["stop_event"], c["chip_type"]) for c in api["chips"]]
    return Rules(
        squad_size=settings["squad_squadsize"],
        xi_size=settings["squad_squadplay"],
        club_limit=settings["squad_team_limit"],
        budget=settings["squad_total_spend"],
        sell_on_fee=settings["transfers_sell_on_fee"],
        max_free_transfers=1 + settings["max_extra_free_transfers"],
        positions=positions,
        chips=chips,
    )


def load_rules(path: Path | None = None) -> Rules:
    path = path or config.RULES_DIR / f"{config.SEASON}_api_rules.json"
    return rules_from_api(read_json(path))


def manual_rules_report() -> str:
    """The rules that came from the FPL website instead of the API."""
    lines = [f"- {key}: {item['rule']}" for key, item in MANUAL_RULES.items()]
    return "\n".join(lines)
