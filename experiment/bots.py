"""The two rule-based baseline teams (brief section 3.2). They make no Claude calls.

Both follow the same simple rules and differ only in how they rank players:
    form bot:   FPL's `form` (average points over roughly the last 30 days)
    crowd bot:  `selected_by_percent` (share of real FPL managers who own the player)
Ties are broken by total points, then by the lower player id, so every run is repeatable.

The rules (decided 2026-10-22, see METHODS.md):
- First week: go down the ranking and buy each player who still fits the position counts, the
  club limit and the budget. A player is only bought if enough money is left to fill every
  remaining place with the cheapest available players.
- Later weeks, using at most the free transfers (never a -4 hit, never a chip):
    1. sell players who can't play (injured, suspended, unavailable, or gone from the game)
       for the best-ranked affordable player in the same position;
    2. then make the swap that improves the ranking the most, again and again, while free
       transfers are left and a swap is an improvement. Unused free transfers are saved.
- Only available players (status "a") are bought.
- Lineup: available players first, then by ranking. Best goalkeeper, then the minimum of each
  outfield position, then the best remaining outfield players. Captain and vice-captain are the
  two best-ranked starters.
Each answer goes through the same validator as the AI teams' answers.
"""

from dataclasses import dataclass

from .rules import Rules
from .team import Player, TeamState, selling_price

CANT_PLAY = {"i", "s", "u", "n"}   # injured, suspended, unavailable, not eligible (e.g. loaned out)


@dataclass(frozen=True)
class Bot:
    id: str
    ranks_by: str     # the bootstrap-static field the bot ranks players by
    description: str


BOTS = [
    Bot("form-bot", "form", "ranks players by FPL form"),
    Bot("crowd-bot", "selected_by_percent", "ranks players by ownership (the template team)"),
]


def ranking(bot: Bot, elements: list[dict]) -> dict[int, tuple]:
    """A sort key per player id: higher is better."""
    return {p["id"]: (float(p.get(bot.ranks_by) or 0), p.get("total_points") or 0, -p["id"]) for p in elements}


# --- first week: a full squad -----------------------------------------------------------------

def build_squad(rank: dict, players: dict[int, Player], rules: Rules) -> list[int]:
    buyable = sorted((p for p in players.values() if p.status == "a"), key=lambda p: rank[p.id], reverse=True)
    needed = {pos: position.squad_count for pos, position in rules.positions.items()}
    clubs, chosen, money = {}, [], rules.budget

    def cheapest_fill(still_needed: dict, taken: set) -> int:
        """Money needed to fill every remaining place with the cheapest available players."""
        total = 0
        for pos, count in still_needed.items():
            prices = sorted(p.price for p in buyable if p.position == pos and p.id not in taken)
            total += sum(prices[:count])
        return total

    for p in buyable:
        if needed[p.position] == 0 or clubs.get(p.club, 0) >= rules.club_limit:
            continue
        after = {**needed, p.position: needed[p.position] - 1}
        if p.price + cheapest_fill(after, set(chosen) | {p.id}) > money:
            continue
        chosen.append(p.id)
        needed, money = after, money - p.price
        clubs[p.club] = clubs.get(p.club, 0) + 1
        if len(chosen) == rules.squad_size:
            return chosen
    raise RuntimeError(f"Bot could not build a full squad (still needed: {needed}).")


# --- later weeks: transfers ---------------------------------------------------------------------

def choose_transfers(rank: dict, state: TeamState, players: dict[int, Player], rules: Rules) -> list[dict]:
    squad = dict(state.squad)               # player id -> purchase price
    bank, left = state.bank, state.free_transfers
    bought, sold, transfers = set(), set(), []
    worst = (float("-inf"),)

    def club_count(club: int) -> int:
        return sum(1 for pid in squad if pid in players and players[pid].club == club)

    def sale_value(pid: int) -> int:
        current = players[pid].price if pid in players else squad[pid]
        return selling_price(squad[pid], current, rules.sell_on_fee)

    def position_of(pid: int) -> int:
        if pid in players:
            return players[pid].position
        # A player removed from the game: his position is the one the rest of the squad is short of.
        counts = {pos: sum(1 for x in squad if x in players and players[x].position == pos) for pos in rules.positions}
        return next(pos for pos, position in rules.positions.items() if counts[pos] < position.squad_count)

    def best_replacement(out: int, must_beat: tuple) -> int | None:
        position = position_of(out)
        money = bank + sale_value(out)
        out_club = players[out].club if out in players else None
        options = [p for p in players.values()
                   if p.status == "a" and p.id not in squad and p.id not in sold
                   and p.position == position and p.price <= money
                   and club_count(p.club) - (1 if p.club == out_club else 0) < rules.club_limit
                   and rank[p.id] > must_beat]
        return max(options, key=lambda p: rank[p.id]).id if options else None

    def swap(out: int, new: int) -> None:
        nonlocal bank, left
        bank += sale_value(out) - players[new].price
        del squad[out]
        squad[new] = players[new].price
        bought.add(new)
        sold.add(out)
        transfers.append({"out": out, "in": new})
        left -= 1

    # 1. Sell players who can't play.
    for out in sorted(squad, key=lambda pid: rank.get(pid, worst)):
        if left == 0:
            break
        if out not in players or players[out].status in CANT_PLAY:
            new = best_replacement(out, worst)
            if new is not None:
                swap(out, new)

    # 2. The biggest ranking improvements, one at a time.
    while left > 0:
        best = None
        for out in [pid for pid in squad if pid not in bought and pid in players]:
            new = best_replacement(out, rank[out])
            if new is not None:
                gain = rank[new][0] - rank[out][0]
                if best is None or (gain, rank[new]) > best[0]:
                    best = ((gain, rank[new]), out, new)
        if best is None:
            break
        swap(best[1], best[2])
    return transfers


# --- lineup -------------------------------------------------------------------------------------

def choose_lineup(squad: list[int], rank: dict, players: dict[int, Player], rules: Rules) -> dict:
    order = sorted(squad, key=lambda pid: (players[pid].status == "a", rank[pid]), reverse=True)
    goalkeeper = next(pos for pos, p in rules.positions.items() if p.max_play == 1 and p.squad_count == 2)
    xi = [next(pid for pid in order if players[pid].position == goalkeeper)]
    for pos, position in rules.positions.items():
        if pos != goalkeeper:
            xi += [pid for pid in order if players[pid].position == pos][:position.min_play]
    for pid in order:
        pos = players[pid].position
        in_xi = sum(1 for x in xi if players[x].position == pos)
        if len(xi) < rules.xi_size and pid not in xi and pos != goalkeeper and in_xi < rules.positions[pos].max_play:
            xi.append(pid)
    bench = [pid for pid in order if pid not in xi and players[pid].position == goalkeeper]
    bench += [pid for pid in order if pid not in xi and players[pid].position != goalkeeper]
    starters = [pid for pid in order if pid in xi]
    return {"starting_xi": xi, "bench_order": bench, "captain": starters[0], "vice_captain": starters[1]}


def decide(bot: Bot, state: TeamState, elements: list[dict], players: dict[int, Player], rules: Rules) -> dict:
    """The bot's answer, in the same format as an AI team's answer."""
    rank = ranking(bot, elements)
    if not state.has_squad:
        squad = build_squad(rank, players, rules)
        answer = {"squad": squad}
    else:
        transfers = choose_transfers(rank, state, players, rules)
        squad = [pid for pid in state.squad if pid not in {t["out"] for t in transfers}] + [t["in"] for t in transfers]
        answer = {"transfers": transfers}
    return {**answer, **choose_lineup(squad, rank, players, rules), "chip": None,
            "reasoning": f"Rule-based: {bot.description}."}
