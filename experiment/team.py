"""A simulated team's bookkeeping: squad, purchase prices, money in the bank, free transfers, chips.

One TeamState per team is saved as JSON after every gameweek. All money is in tenths of £m.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .files import read_json, write_json


@dataclass
class Player:
    """The facts about one FPL player that the rules need (from bootstrap-static `elements`)."""
    id: int
    name: str
    position: int       # element_type id (1 GKP, 2 DEF, 3 MID, 4 FWD)
    club: int           # team id
    price: int          # now_cost, tenths of £m
    status: str         # a = available, d = doubtful, i = injured, s = suspended, u = unavailable, n = not eligible
    club_short: str = ""  # e.g. ARS


def players_from_bootstrap(bootstrap: dict) -> dict[int, Player]:
    clubs = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    return {
        p["id"]: Player(p["id"], p["web_name"], p["element_type"], p["team"], p["now_cost"], p.get("status", "a"),
                        clubs.get(p["team"], ""))
        for p in bootstrap["elements"]
    }


@dataclass
class Lineup:
    starting_xi: list[int]
    bench_order: list[int]      # goalkeeper first, then outfield subs in priority order
    captain: int
    vice_captain: int


@dataclass
class TeamState:
    team_id: str
    squad: dict[int, int] = field(default_factory=dict)   # player id -> purchase price
    bank: int = 0
    free_transfers: int = 0
    chips_used: list[dict] = field(default_factory=list)  # [{"chip_id", "name", "gw"}]
    lineup: Lineup | None = None
    # While a free hit is active, the real squad waits here and comes back next gameweek.
    free_hit_backup: dict | None = None
    has_squad: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["squad"] = {str(k): v for k, v in self.squad.items()}  # JSON keys must be strings
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "TeamState":
        data = dict(data)
        data["squad"] = {int(k): v for k, v in data["squad"].items()}
        data["lineup"] = Lineup(**data["lineup"]) if data.get("lineup") else None
        return cls(**data)

    def save(self, path: Path) -> None:
        write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: Path) -> "TeamState":
        return cls.from_dict(read_json(path))


def selling_price(purchase: int, current: int, sell_on_fee: float) -> int:
    """What you get back when selling a player (tenths of £m).

    Price fell or unchanged: you get the current price.
    Price rose: you keep only `sell_on_fee` (0.5) of the rise, rounded down to £0.1m.
    Example: bought at 7.6, now 7.9 -> rise 0.3 -> keep 0.1 (0.15 rounded down) -> sell for 7.7.
    """
    if current <= purchase:
        return current
    return purchase + int((current - purchase) * sell_on_fee)
