"""Check an agent's (or bot's) weekly decision against the FPL rules, then apply it.

A decision is the parsed JSON answer:
    first week:  {"squad": [15 ids], "starting_xi": [...], "bench_order": [...], "captain": id,
                  "vice_captain": id, "chip": null}
    later weeks: {"transfers": [{"out": id, "in": id}, ...], "starting_xi": [...], ...same...}

validate() never changes anything. It returns every problem it finds as an error with a
machine-readable code (e.g. CLUB_LIMIT) and a message that can be sent back to the agent.
Illegal answers are results, not just bugs: every error is logged by the runner.
"""

import copy
from collections import Counter
from dataclasses import asdict, dataclass, field

from .rules import MANUAL_RULES, Chip, Rules
from .team import Lineup, Player, TeamState, selling_price


@dataclass
class Error:
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass
class Result:
    errors: list[Error] = field(default_factory=list)
    stale_picks: list[int] = field(default_factory=list)  # players the agent picked who aren't really in the game
    transfers_made: int = 0
    hit_points: int = 0          # points deducted for extra transfers (positive number)
    bank_after: int | None = None
    bench_order: list[int] | None = None   # bench with the goalkeeper moved to the first slot
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error_codes(self) -> list[str]:
        return [e.code for e in self.errors]

    def feedback(self) -> str:
        """The text sent back to the agent when it has to try again."""
        return "\n".join(str(e) for e in self.errors)


def _money(tenths: int) -> str:
    return f"£{tenths / 10:.1f}m"


# --- small checks --------------------------------------------------------------------------

def _is_id_list(value, length: int | None = None) -> bool:
    return (isinstance(value, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in value)
            and (length is None or len(value) == length))


def _check_new_players(ids: list[int], players: dict[int, Player], result: Result) -> None:
    """Players being bought must exist and must not have left (status 'u'). Both count as stale picks."""
    for pid in ids:
        if pid not in players:
            result.errors.append(Error("UNKNOWN_PLAYER", f"Player id {pid} does not exist in the game."))
            result.stale_picks.append(pid)
        elif players[pid].status == "u":
            result.errors.append(Error(
                "UNAVAILABLE_PLAYER",
                f"{players[pid].name} (id {pid}) is unavailable (left the club or the league) and can't be bought."))
            result.stale_picks.append(pid)


def _check_squad(ids: list[int], players: dict[int, Player], rules: Rules, result: Result) -> None:
    """Size, players per position and players per club for a full squad."""
    if len(ids) != rules.squad_size:
        result.errors.append(Error("SQUAD_SIZE", f"Squad has {len(ids)} players; it must have {rules.squad_size}."))
    duplicates = [pid for pid, n in Counter(ids).items() if n > 1]
    if duplicates:
        result.errors.append(Error("DUPLICATE_PLAYER", f"Players listed more than once: {duplicates}."))
    known = [players[pid] for pid in set(ids) if pid in players]
    by_position = Counter(p.position for p in known)
    for pos in rules.positions.values():
        if by_position[pos.id] != pos.squad_count:
            result.errors.append(Error(
                "SQUAD_POSITIONS", f"Squad has {by_position[pos.id]} {pos.short}; it must have exactly {pos.squad_count}."))
    by_club = Counter(p.club for p in known)
    for club, count in by_club.items():
        if count > rules.club_limit:
            ids_from_club = sorted(p.id for p in known if p.club == club)
            result.errors.append(Error(
                "CLUB_LIMIT", f"{count} players from the same club (ids {ids_from_club}); the maximum is {rules.club_limit}."))


def _check_lineup(decision: dict, squad: set[int], players: dict[int, Player], rules: Rules, result: Result) -> None:
    xi, bench = decision.get("starting_xi"), decision.get("bench_order")
    captain, vice = decision.get("captain"), decision.get("vice_captain")

    if not _is_id_list(xi, rules.xi_size) or len(set(xi)) != rules.xi_size:
        result.errors.append(Error("XI_SIZE", f"starting_xi must list {rules.xi_size} different player ids."))
        return
    outside = [pid for pid in xi if pid not in squad]
    if outside:
        result.errors.append(Error("XI_NOT_IN_SQUAD", f"Starting XI players not in the squad: {outside}."))
        return

    by_position = Counter(players[pid].position for pid in xi)
    for pos in rules.positions.values():
        if not pos.min_play <= by_position[pos.id] <= pos.max_play:
            result.errors.append(Error(
                "XI_FORMATION",
                f"Starting XI has {by_position[pos.id]} {pos.short}; allowed is {pos.min_play} to {pos.max_play}."))

    expected_bench = squad - set(xi)
    if not _is_id_list(bench) or len(bench) != len(set(bench)) or set(bench) != expected_bench:
        result.errors.append(Error(
            "BENCH_MISMATCH", f"bench_order must list exactly the {len(expected_bench)} squad players not in the XI: "
                              f"{sorted(expected_bench)}."))
    else:
        # The substitute goalkeeper always sits first; keep the agent's order for the outfield subs.
        goalkeepers = [pid for pid in bench if players[pid].position == rules.position_by_short("GKP").id]
        reordered = goalkeepers + [pid for pid in bench if pid not in goalkeepers]
        if reordered != bench:
            result.notes.append("bench goalkeeper moved to the first bench slot")
        result.bench_order = reordered

    for role, pid in (("captain", captain), ("vice_captain", vice)):
        if pid not in xi:
            result.errors.append(Error(f"{role.upper()}_NOT_IN_XI", f"{role} ({pid}) must be in the starting XI."))
    if captain is not None and captain == vice:
        result.errors.append(Error("CAPTAIN_IS_VICE", "captain and vice_captain must be different players."))


def find_chip(name: str, state: TeamState, rules: Rules, gw: int) -> tuple[Chip | None, Error | None]:
    """The unused copy of a chip that can be played this gameweek, or the reason it can't."""
    copies = [c for c in rules.chips if c.name == name]
    if not copies:
        names = sorted({c.name for c in rules.chips})
        return None, Error("CHIP_UNKNOWN", f"Unknown chip {name!r}. Chips are: {names}.")
    used_ids = {u["chip_id"] for u in state.chips_used}
    for chip in copies:
        if chip.start_gw <= gw <= chip.stop_gw:
            if chip.id in used_ids:
                return None, Error("CHIP_ALREADY_USED", f"{name} has already been used (gameweeks {chip.start_gw}-{chip.stop_gw}).")
            return chip, None
    return None, Error("CHIP_NOT_AVAILABLE", f"{name} can't be played in gameweek {gw}.")


# --- the main checks -----------------------------------------------------------------------

def validate(decision, state: TeamState, players: dict[int, Player], rules: Rules, gw: int) -> Result:
    """Check one decision. `players` must come from this gameweek's snapshot data."""
    result = Result()
    if not isinstance(decision, dict):
        result.errors.append(Error("NOT_AN_OBJECT", "The answer must be a single JSON object."))
        return result

    first_week = not state.has_squad

    # Chip (only one per gameweek: the answer has a single `chip` field).
    chip = None
    chip_name = decision.get("chip")
    if chip_name is not None:
        if not isinstance(chip_name, str):
            result.errors.append(Error("CHIP_UNKNOWN", "chip must be a chip name or null."))
        else:
            chip, error = find_chip(chip_name, state, rules, gw)
            if error:
                result.errors.append(error)
            elif first_week and chip.kind == "transfer" and MANUAL_RULES["transfer_chips_not_in_first_week"]["value"]:
                result.errors.append(Error("CHIP_NOT_IN_FIRST_WEEK", f"{chip_name} can't be played in a team's first gameweek."))
                chip = None

    if first_week:
        squad_ids = decision.get("squad")
        if decision.get("transfers"):
            result.errors.append(Error("TRANSFERS_IN_FIRST_WEEK", "First week: give a full `squad`, not `transfers`."))
        if not _is_id_list(squad_ids):
            result.errors.append(Error("SQUAD_MISSING", f"First week: `squad` must be a list of {rules.squad_size} player ids."))
            return result
        _check_new_players(squad_ids, players, result)
        _check_squad(squad_ids, players, rules, result)
        cost = sum(players[pid].price for pid in set(squad_ids) if pid in players)
        if cost > rules.budget:
            result.errors.append(Error("OVER_BUDGET", f"Squad costs {_money(cost)}; the budget is {_money(rules.budget)}."))
        result.bank_after = rules.budget - cost
        new_squad = set(squad_ids)
    else:
        if decision.get("squad") is not None:
            result.errors.append(Error("SQUAD_NOT_EXPECTED", "After the first week, change the squad with `transfers`, not `squad`."))
        transfers = decision.get("transfers", [])
        if not isinstance(transfers, list) or not all(
                isinstance(t, dict) and _is_id_list([t.get("out"), t.get("in")]) for t in transfers):
            result.errors.append(Error("TRANSFERS_FORMAT", 'transfers must be a list like [{"out": 123, "in": 456}].'))
            return result
        outs = [t["out"] for t in transfers]
        ins = [t["in"] for t in transfers]
        current = set(state.squad)
        not_owned = [pid for pid in outs if pid not in current]
        if not_owned:
            result.errors.append(Error("TRANSFER_OUT_NOT_IN_SQUAD", f"Can't sell players not in the squad: {not_owned}."))
        already = [pid for pid in ins if pid in current]
        if already:
            result.errors.append(Error("TRANSFER_IN_ALREADY_IN_SQUAD", f"Already in the squad: {already}."))
        if len(set(outs)) != len(outs) or len(set(ins)) != len(ins):
            result.errors.append(Error("DUPLICATE_TRANSFER", "A player appears in more than one transfer."))
        _check_new_players([pid for pid in ins if pid not in current], players, result)
        if result.errors:
            return result

        new_squad = (current - set(outs)) | set(ins)
        _check_squad(sorted(new_squad), players, rules, result)
        # A player removed from the game entirely (very rare) is sold back at his purchase price.
        income = sum(selling_price(state.squad[pid], players[pid].price if pid in players else state.squad[pid],
                                   rules.sell_on_fee) for pid in outs)
        spend = sum(players[pid].price for pid in ins)
        result.bank_after = state.bank + income - spend
        if result.bank_after < 0:
            result.errors.append(Error(
                "OVER_BUDGET", f"Transfers cost {_money(spend)} but you only have {_money(state.bank + income)} "
                               f"(bank {_money(state.bank)} + sales {_money(income)})."))

        result.transfers_made = len(transfers)
        if chip is None or chip.kind != "transfer":
            extra = max(0, len(transfers) - state.free_transfers)
            result.hit_points = extra * rules.hit_cost

    # The lineup can only be checked against a complete squad of known players.
    missing = sorted(pid for pid in new_squad if pid not in players)
    if missing and not first_week:
        result.errors.append(Error("SQUAD_PLAYER_NOT_IN_GAME",
                                   f"Squad players no longer in the game must be transferred out: {missing}."))
    elif len(new_squad) == rules.squad_size and not missing:
        _check_lineup(decision, new_squad, players, rules, result)
    return result


def apply(decision: dict, state: TeamState, players: dict[int, Player], rules: Rules, gw: int,
          result: Result) -> TeamState:
    """Return the team's new state after a decision that passed validate()."""
    if not result.ok:
        raise ValueError("apply() needs a decision that passed validate().")
    new = copy.deepcopy(state)
    chip = find_chip(decision["chip"], state, rules, gw)[0] if decision.get("chip") else None

    if not state.has_squad:
        new.squad = {pid: players[pid].price for pid in decision["squad"]}
        new.has_squad = True
        new.free_transfers = MANUAL_RULES["new_team_free_transfers"]["value"]
    else:
        if chip is not None and chip.name == "freehit":
            # Keep the real squad aside; start_gameweek() puts it back next week.
            new.free_hit_backup = {"squad": dict(state.squad), "bank": state.bank,
                                   "lineup": asdict(state.lineup) if state.lineup else None}
        for t in decision.get("transfers", []):
            del new.squad[t["out"]]
            new.squad[t["in"]] = players[t["in"]].price
        transfers = len(decision.get("transfers", []))
        if chip is not None and chip.kind == "transfer":
            # Wildcard / free hit week: saved free transfers are kept, but no new one is gained.
            new.free_transfers = state.free_transfers
        else:
            saved = max(0, state.free_transfers - transfers)
            new.free_transfers = min(rules.max_free_transfers, saved + rules.free_transfers_per_gw)

    new.bank = result.bank_after
    new.lineup = Lineup(decision["starting_xi"], result.bench_order, decision["captain"], decision["vice_captain"])
    if chip is not None:
        new.chips_used.append({"chip_id": chip.id, "name": chip.name, "gw": gw})
    return new


def start_gameweek(state: TeamState) -> TeamState:
    """Run before a new gameweek's decision: undo last week's free hit, if there was one."""
    if not state.free_hit_backup:
        return state
    new = copy.deepcopy(state)
    backup = new.free_hit_backup
    new.squad = {int(k): v for k, v in backup["squad"].items()}
    new.bank = backup["bank"]
    new.lineup = Lineup(**backup["lineup"]) if backup["lineup"] else None
    new.free_hit_backup = None
    return new


def no_change_decision(state: TeamState) -> dict | None:
    """What a team does when every attempt failed: no transfers, no chip, last week's lineup.

    Returns None if the team has no squad yet (it then scores 0 and tries again next week).
    """
    if not state.has_squad or state.lineup is None:
        return None
    return {"transfers": [], "starting_xi": list(state.lineup.starting_xi),
            "bench_order": list(state.lineup.bench_order), "captain": state.lineup.captain,
            "vice_captain": state.lineup.vice_captain, "chip": None}
