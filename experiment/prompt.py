"""Build the weekly prompt and the answer format (JSON schema) for an agent.

Every agent gets the same template (prompts/{version}/decision.md), the same rules text and
the same player table. Only the "Your team" section (its own squad) and, for memory teams, the
memory section differ. The rules text is generated from experiment/rules.py, so the prompt can
never disagree with the validator.
"""

import json

from . import config
from .rules import Rules
from .team import Player, TeamState, selling_price
from .validator import Result, find_chip

CHIP_TEXT = {
    "wildcard": "unlimited free transfers this gameweek; the new squad is permanent",
    "freehit": "unlimited free transfers for this gameweek only; next gameweek your squad goes back to what it was",
    "bboost": "bench boost: your 4 bench players' points also count this gameweek",
    "3xc": "triple captain: your captain scores triple instead of double this gameweek",
}


def _money(tenths: int) -> str:
    return f"£{tenths / 10:.1f}m"


def load_template(name: str, version: str = config.PROMPT_VERSION) -> str:
    return (config.PROMPTS_DIR / version / name).read_text(encoding="utf-8")


def rules_text(rules: Rules) -> str:
    positions = list(rules.positions.values())
    squad = ", ".join(f"{p.squad_count} {p.short}" for p in positions)
    xi = ", ".join(f"{p.short} {p.min_play}" if p.min_play == p.max_play else f"{p.short} {p.min_play}-{p.max_play}"
                   for p in positions)
    # One copy of each chip per half: e.g. "GW1-19 and GW20-38" (a chip may start later inside its half).
    halves = {}
    for chip in rules.chips:
        halves[chip.stop_gw] = min(chip.start_gw, halves.get(chip.stop_gw, chip.start_gw))
    windows = " and ".join(f"GW{start}-{stop}" for stop, start in sorted(halves.items()))
    chips = "\n".join(f"  - {name}: {text}" for name, text in CHIP_TEXT.items())
    return "\n".join([
        f"- Squad: {rules.squad_size} players ({squad}). At most {rules.club_limit} players from one club.",
        f"- Budget: a new squad can cost at most {_money(rules.budget)}. Money not spent stays in the bank.",
        f"- Each gameweek you choose a starting XI of {rules.xi_size} ({xi}). The other 4 players are the bench: "
        "the substitute goalkeeper first, then the 3 outfield substitutes in your priority order.",
        "- Only the starting XI score. A starter who plays 0 minutes is automatically replaced by the first bench "
        "player in your order who played, as long as the formation stays valid (a goalkeeper only by the "
        "substitute goalkeeper).",
        "- The captain's points count double. If the captain plays 0 minutes, the vice-captain's points count "
        "double instead. Captain and vice-captain must both be in the starting XI and be different players.",
        f"- Transfers: you gain {rules.free_transfers_per_gw} free transfer each gameweek. Unused free transfers "
        f"are saved, up to {rules.max_free_transfers}. Each transfer beyond your free transfers costs "
        f"{rules.hit_cost} points.",
        f"- Selling: if a player's price has risen since you bought him, you get back only "
        f"{int(rules.sell_on_fee * 100)}% of the rise, rounded down to £0.1m. If it has fallen, you get the "
        "current price.",
        "- Players with status u can't be bought. Only player ids in the table below exist.",
        f"- Chips: each chip can be played once in each half of the season ({windows}), and at most one chip "
        "per gameweek. When you play a wildcard or free hit, your saved free transfers are kept, but you gain "
        "no new free transfer that gameweek.\n" + chips,
    ])


def team_text(state: TeamState, players: dict[int, Player], rules: Rules, gw: int) -> str:
    if not state.has_squad:
        return (f"You don't have a squad yet: this is your first gameweek. Pick a full squad of {rules.squad_size} "
                f"players costing at most {_money(rules.budget)}. Transfers are not needed this week, and the "
                "wildcard and free hit can't be played this week (bench boost and triple captain can).")

    available = [name for name in CHIP_TEXT if find_chip(name, state, rules, gw)[0] is not None]
    used = ", ".join(f"{u['name']} (GW{u['gw']})" for u in state.chips_used) or "none"
    lineup = state.lineup
    roles = {}
    if lineup:
        roles = {pid: "XI" for pid in lineup.starting_xi}
        roles.update({pid: f"bench {i}" for i, pid in enumerate(lineup.bench_order, start=1)})
        roles[lineup.captain] += ", C"
        roles[lineup.vice_captain] += ", VC"

    lines = [
        f"Bank: {_money(state.bank)}. Free transfers this gameweek: {state.free_transfers}.",
        f"Chips you can play this gameweek: {', '.join(available) or 'none'}. Chips already used: {used}.",
        "",
        "Your squad (id | name | club | pos | bought for | price now | selling price | last gameweek):",
    ]
    positions = {p.id: p.short for p in rules.positions.values()}
    for pid, bought in sorted(state.squad.items(), key=lambda kv: (players[kv[0]].position if kv[0] in players else 9, kv[0])):
        p = players.get(pid)
        if p is None:
            lines.append(f"{pid} | (no longer in the game) | - | - | {_money(bought)} | - | {_money(bought)} | {roles.get(pid, '-')}")
            continue
        sell = selling_price(bought, p.price, rules.sell_on_fee)
        lines.append(f"{pid} | {p.name} | {p.club_short} | {positions[p.position]} | {_money(bought)} | "
                     f"{_money(p.price)} | {_money(sell)} | {roles.get(pid, '-')}")
    return "\n".join(lines)


def answer_text(first_week: bool, memory_fields: str = "") -> str:
    if first_week:
        example = {"squad": ["15 player ids"], "starting_xi": ["11 player ids"], "bench_order": ["4 player ids"],
                   "captain": "player id", "vice_captain": "player id", "chip": None,
                   "reasoning": "at most 80 words"}
        squad_line = "- squad: the ids of all 15 players you buy."
    else:
        example = {"transfers": [{"out": "player id", "in": "player id"}], "starting_xi": ["11 player ids"],
                   "bench_order": ["4 player ids"], "captain": "player id", "vice_captain": "player id",
                   "chip": None, "reasoning": "at most 80 words"}
        squad_line = ("- transfers: a list of {\"out\": id, \"in\": id} pairs, or [] for no transfers. "
                      "The rest of your answer refers to your squad after these transfers.")
    return "\n".join([
        "Reply with only a JSON object with these fields:",
        squad_line,
        "- starting_xi: the 11 starters' ids.",
        "- bench_order: the other 4 ids: the substitute goalkeeper first, then the outfield substitutes in priority order.",
        "- captain, vice_captain: ids of two different starters.",
        '- chip: "wildcard", "freehit", "bboost", "3xc", or null for no chip.',
        "- reasoning: why you made this decision, in at most 80 words.",
    ] + ([memory_fields] if memory_fields else []) + [
        "",
        "Shape (with real ids instead of the descriptions):",
        json.dumps(example),
    ])


def build_prompt(state: TeamState, players: dict[int, Player], rules: Rules, gw: int, deadline: str,
                 players_table: str, memory_section: str = "", memory_fields: str = "") -> str:
    replacements = {
        "gameweek": str(gw),
        "deadline": deadline,
        "rules": rules_text(rules),
        "team": team_text(state, players, rules, gw),
        "memory": f"\n{memory_section}\n" if memory_section else "",
        "players": players_table,
        "answer": answer_text(not state.has_squad, memory_fields),
    }
    text = load_template("decision.md")
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    if "{{" in text.split("## Player data")[0]:
        raise ValueError("A placeholder in the prompt template was not filled in.")
    return text


def retry_text(previous_answer: str, result: Result) -> str:
    """Added to the end of the prompt when the previous answer broke a rule."""
    return "\n".join([
        "",
        "## Your previous answer was not allowed",
        "",
        "Your previous answer:",
        previous_answer.strip(),
        "",
        "Problems:",
        *[f"- {error}" for error in result.errors],
        "",
        "Reply with a corrected JSON object (the whole answer, not only the changes).",
    ])


# --- answer format (forced with the CLI's --json-schema) ------------------------------------

def _ids(description: str) -> dict:
    return {"type": "array", "items": {"type": "integer"}, "description": description}


def answer_schema(first_week: bool, extra_properties: dict | None = None) -> dict:
    """The JSON shape of an answer. It checks types only; FPL rules are checked by the validator."""
    properties = {
        "starting_xi": _ids("ids of the 11 starters"),
        "bench_order": _ids("ids of the 4 substitutes, goalkeeper first"),
        "captain": {"type": "integer"},
        "vice_captain": {"type": "integer"},
        "chip": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    }
    if first_week:
        properties = {"squad": _ids("ids of all 15 players"), **properties}
    else:
        properties = {"transfers": {"type": "array", "items": {
            "type": "object", "properties": {"out": {"type": "integer"}, "in": {"type": "integer"}},
            "required": ["out", "in"], "additionalProperties": False}}, **properties}
    properties.update(extra_properties or {})
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}
