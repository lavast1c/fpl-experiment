"""The weekly runner: `decide` (all teams pick) and `score` (once the gameweek is final).

Real runs save into data/ (the open dataset). Mock runs save into data/mock/ (git-ignored).
Per gameweek N, inside that folder:
    teams/{team}/gw{N}.json and latest.json   each team's state after its decision
    decisions/gw{N}/{team}.json               the decision that was applied, attempts and errors
    logs/gw{N}/{team}/prompt.txt.gz           the exact prompt sent
    logs/gw{N}/{team}/attempt{k}.json         every call: raw output, parsed answer, validator result, tokens
    scores/gw{N}.json and gw{N}.csv           points per team
"""

import random
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config, fetch, memory
from .agents import CallContext, ClaudeAgent, MockAgent
from .files import read_json, read_json_gz, write_csv, write_json, write_json_gz
from .gameweeks import deadline, get_event, hours_until_deadline
from .prompt import answer_schema, build_prompt, load_template, retry_text
from .rules import FIRST_WEEK_EXTRA_RETRIES, MAX_RETRIES, load_rules
from .scorer import LivePlayer, live_from_api, score
from .team import TeamState, players_from_bootstrap
from .teams import TEAMS, Team
from .validator import apply, no_change_decision, start_gameweek, validate


def base_dir(mock: bool) -> Path:
    return config.MOCK_DIR if mock else config.DATA_DIR


# --- team state files ------------------------------------------------------------------------

def load_state(base: Path, team_id: str) -> TeamState:
    path = base / "teams" / team_id / "latest.json"
    return TeamState.load(path) if path.exists() else TeamState(team_id)


def save_state(base: Path, state: TeamState, gw: int) -> None:
    state.save(base / "teams" / state.team_id / f"gw{gw}.json")
    state.save(base / "teams" / state.team_id / "latest.json")


# --- inputs for a gameweek ---------------------------------------------------------------------

def gameweek_inputs(gw: int, mock: bool = False) -> tuple[dict, str, dict]:
    """The bootstrap data the snapshot was built from, the agents' player table, and its meta.

    Mock runs of future gameweeks (to simulate several weeks) reuse the latest real snapshot.
    """
    meta_path = config.SNAPSHOT_DIR / f"gw{gw}.meta.json"
    if not meta_path.exists() and mock:
        meta_path = max(config.SNAPSHOT_DIR.glob("gw*.meta.json"), key=lambda p: int(p.name[2:].split(".")[0]))
        print(f"  (mock) no snapshot for gameweek {gw}; using {meta_path.name}")
    if not meta_path.exists():
        raise SystemExit(f"No snapshot for gameweek {gw}. Run `python run.py fetch` and `python run.py snapshot`.")
    meta = read_json(meta_path)
    bootstrap = read_json_gz(config.RAW_DIR / meta["sources"]["bootstrap"])
    table = (config.SNAPSHOT_DIR / f"gw{meta['gw']}_table.txt").read_text(encoding="utf-8")
    return bootstrap, table, meta


# --- decide ------------------------------------------------------------------------------------

def decide(gw: int, mock: bool, teams: list[Team] = TEAMS, real_calls_confirmed: bool = False) -> None:
    if not mock and not real_calls_confirmed:
        raise SystemExit("Real runs use your Claude plan. Add --yes-real-calls once you have agreed to it.")
    base = base_dir(mock)
    bootstrap, table, meta = gameweek_inputs(gw, mock)
    events = bootstrap["events"]
    hours = hours_until_deadline(events, gw)
    if hours <= 0 and not mock:
        raise SystemExit(f"The gameweek {gw} deadline has passed. Nothing was run.")
    if hours < config.DEADLINE_WARNING_HOURS:
        print(f"WARNING: the deadline is only {hours:.1f} hours away.")
    week = Week(gw=gw, when=f"{deadline(events, gw):%Y-%m-%d %H:%M}", base=base, mock=mock,
                system=load_template("system.txt"), table=table, players=players_from_bootstrap(bootstrap),
                rules=load_rules(),
                expected={p["id"]: float(p.get("ep_next") or 0) for p in bootstrap["elements"]})
    print(f"Gameweek {gw}: {'MOCK' if mock else 'REAL'} run for {len(teams)} teams "
          f"(prompt {config.PROMPT_VERSION}, effort {config.EFFORT}, snapshot filter '{meta['filter']}')")

    summary = []
    for team in teams:   # one at a time, never in parallel
        decision_path = base / "decisions" / f"gw{gw}" / f"{team.id}.json"
        if decision_path.exists():
            print(f"  {team.id}: already decided, skipped")
            continue
        outcome = run_team(team, week)
        if outcome is not None:
            summary.append(outcome)
    print_token_summary(summary)


@dataclass
class Week:
    """Everything that is the same for every team in one gameweek's run."""
    gw: int
    when: str                    # deadline text
    base: Path                   # data/ or data/mock/
    mock: bool
    system: str
    table: str                   # the player table
    players: dict
    rules: object
    expected: dict[int, float]   # ep_next per player at decision time (for verified memory)


def last_week_results(base: Path, team_id: str, gw: int) -> dict | None:
    """This team's results for gameweek gw-1, for the memory section (None if it didn't play then)."""
    if not (base / "decisions" / f"gw{gw - 1}" / f"{team_id}.json").exists():
        return None
    path = base / "scores" / f"gw{gw - 1}.json"
    if not path.exists():
        return {"gw": gw - 1, "missing": True}
    scores = read_json(path)
    row = next((r for r in scores["teams"] if r["team"] == team_id), None)
    return {**row, "average": scores.get("average")} if row else {"gw": gw - 1, "missing": True}


def run_team(team: Team, week: Week) -> dict | None:
    gw, base, players, rules = week.gw, week.base, week.players, week.rules
    state = start_gameweek(load_state(base, team.id))
    first_week = not state.has_squad
    max_attempts = 1 + MAX_RETRIES + (FIRST_WEEK_EXTRA_RETRIES if first_week else 0)
    kind = team.memory
    mem, section = None, ""
    if kind != "none":
        mem = memory.load_memory(base, team.id, kind)
        last = last_week_results(base, team.id, gw)
        if last and last.get("missing"):
            print(f"  WARNING {team.id}: gameweek {gw - 1} has not been scored, so its results can't be shown.")
        section = memory.memory_section(kind, mem, last)
    base_prompt = build_prompt(state, players, rules, gw, week.when, week.table, section, kind)
    schema = answer_schema(first_week, kind)
    if week.mock:
        agent = MockAgent(team.model, seed=zlib.crc32(f"{team.id}-{gw}".encode()))
    else:
        agent = ClaudeAgent(team.model)
    log_dir = base / "logs" / f"gw{gw}" / team.id
    write_json_gz(log_dir / "prompt.txt.gz", {"system": week.system, "prompt": base_prompt, "schema": schema})

    prompt, attempts, accepted = base_prompt, [], None
    for number in range(1, max_attempts + 1):
        context = CallContext(state, players, rules, gw, is_retry=number > 1, memory_kind=kind, memory=mem)
        record = agent.call(week.system, prompt, schema, context)
        result = None if record.error else validate(record.answer, state, players, rules, gw)
        if result is not None and kind != "none":
            result.errors += memory.check_answer(kind, record.answer, mem)   # notes/lessons rules
        log = {"attempt": number, "retry_text": prompt[len(base_prompt):], **asdict(record),
               "errors": [asdict(e) for e in result.errors] if result else [],
               "stale_picks": result.stale_picks if result else [], "notes": result.notes if result else []}
        write_json(log_dir / f"attempt{number}.json", log)
        attempts.append(log)
        if record.model_mismatch:
            print(f"  WARNING {team.id}: asked for {team.model}, but the CLI reports {record.models_used}")
        if record.error:
            # Not the agent's fault (quota, network, CLI): save nothing, so the team can be re-run later.
            print(f"  {team.id}: call failed ({record.error}). Nothing saved; run `decide` again to retry this team.")
            return None
        if result.ok:
            accepted = (record.answer, result)
            break
        print(f"  {team.id} attempt {number}: {', '.join(result.error_codes())}")
        prompt = base_prompt + retry_text(record.answer_text, result)

    if accepted:
        decision, result = accepted
        new_state, outcome = apply(decision, state, players, rules, gw, result), "accepted"
        if kind != "none":
            mem = memory.apply_answer(kind, decision, mem, gw, week.expected)
    else:
        decision = no_change_decision(state)
        result = validate(decision, state, players, rules, gw) if decision else None
        if result is not None and result.ok:
            new_state, outcome = apply(decision, state, players, rules, gw, result), "no_change"
        else:
            decision, new_state, outcome = None, state, "no_squad" if first_week else "no_change_failed"

    save_state(base, new_state, gw)
    if kind != "none":
        memory.save_memory(base, team.id, mem, gw)   # unchanged if every attempt failed
    summary = {
        "team": team.id, "model": team.model, "memory": team.memory, "gw": gw,
        "prompt_version": config.PROMPT_VERSION, "effort": config.EFFORT, "mock": week.mock,
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "first_week": first_week, "outcome": outcome, "attempts": len(attempts), "max_attempts": max_attempts,
        "errors_by_attempt": [[e["code"] for e in a["errors"]] for a in attempts],
        "stale_picks": sorted({pid for a in attempts for pid in a["stale_picks"]}),
        "decision": decision,
        "chip": decision.get("chip") if decision else None,
        "transfers_made": result.transfers_made if result and result.ok else 0,
        "hit_points": result.hit_points if result and result.ok else 0,
        "notes": result.notes if result else [],
        "model_mismatch": any(a["model_mismatch"] for a in attempts),
        "models_used": sorted({m for a in attempts for m in a["models_used"]}),
        "input_tokens": sum(a["input_tokens"] for a in attempts),
        "output_tokens": sum(a["output_tokens"] for a in attempts),
        "duration_ms": sum(a["duration_ms"] for a in attempts),
    }
    write_json(base / "decisions" / f"gw{gw}" / f"{team.id}.json", summary)
    print(f"  {team.id}: {outcome} after {len(attempts)} attempt(s)"
          + (f", hit -{summary['hit_points']}" if summary["hit_points"] else "")
          + (f", chip {summary['chip']}" if summary["chip"] else ""))
    return summary


def print_token_summary(summaries: list[dict]) -> None:
    if not summaries:
        return
    print("\nToken use this run:")
    for s in summaries:
        print(f"  {s['team']:<11} {s['attempts']} call(s)  in {s['input_tokens']:>8,}  out {s['output_tokens']:>7,}")
    total_in = sum(s["input_tokens"] for s in summaries)
    total_out = sum(s["output_tokens"] for s in summaries)
    print(f"  {'total':<11} {sum(s['attempts'] for s in summaries)} call(s)  in {total_in:>8,}  out {total_out:>7,}")


# --- score -------------------------------------------------------------------------------------

def gameweek_is_final(gw: int) -> tuple[bool, dict]:
    """FPL has finished the gameweek: every day's bonus points added and the event's data checked.
    Also returns the fresh bootstrap data (it holds FPL's average score for the gameweek)."""
    bootstrap, _ = fetch.get_bootstrap()
    status = fetch.get("event-status/", fetch.latest_bootstrap()[1])
    days = [s for s in status.get("status", []) if s.get("event") == gw]
    final = bool(days) and all(s.get("bonus_added") for s in days) and get_event(bootstrap["events"], gw)["data_checked"]
    return final, bootstrap


def fake_live(players: dict, gw: int) -> dict[int, LivePlayer]:
    """Mock scoring before a gameweek has been played: random but repeatable minutes and points."""
    rng = random.Random(gw)
    live = {}
    for pid in players:
        minutes = rng.choice([0, 0, 0, 25, 60, 90, 90, 90])
        live[pid] = LivePlayer(minutes, 0 if minutes == 0 else rng.choice([1, 2, 2, 2, 3, 5, 6, 8, 10]))
    return live


CSV_FIELDS = ["team", "gw", "points", "hit_points", "net_points", "captain", "auto_subs", "bench_points", "chip"]


def _team_row(team: Team, gw: int, decision: dict, state: TeamState, players: dict, positions: dict,
              live: dict, rules) -> dict:
    """One team's score, plus the details memory teams see next week."""
    if not state.has_squad or state.lineup is None:
        return {"team": team.id, "gw": gw, "points": 0, "hit_points": 0, "net_points": 0, "captain": None,
                "auto_subs": 0, "bench_points": 0, "chip": None, "players": [], "transfers": [],
                "auto_subs_detail": []}
    result = score(state.lineup, decision["chip"], positions, live, rules)
    name = lambda pid: players[pid].name if pid in players else str(pid)
    pts = lambda pid: live[pid].points if pid in live else 0
    lineup = state.lineup
    roles = {pid: "starter" for pid in lineup.starting_xi}
    roles.update({pid: f"bench {i}" for i, pid in enumerate(lineup.bench_order, start=1)})
    # Always show the chosen captain and vice-captain, and who actually got the multiplier (if anyone).
    roles[lineup.captain] += (f", captain x{result.multiplier}" if result.captain == lineup.captain
                              else ", captain (didn't play)")
    roles[lineup.vice_captain] += (f", vice-captain, took the armband x{result.multiplier}"
                                   if result.captain == lineup.vice_captain else ", vice-captain")
    for out, came_in in result.auto_subs:
        roles[out] += ", subbed off (didn't play)"
        roles[came_in] += ", came on as automatic sub"
    transfers = [{"out": t["out"], "out_name": name(t["out"]), "out_points": pts(t["out"]),
                  "in": t["in"], "in_name": name(t["in"]), "in_points": pts(t["in"])}
                 for t in (decision["decision"] or {}).get("transfers", [])] if decision["outcome"] == "accepted" else []
    return {"team": team.id, "gw": gw, "points": result.points, "hit_points": decision["hit_points"],
            "net_points": result.points - decision["hit_points"], "captain": result.captain,
            "auto_subs": len(result.auto_subs), "bench_points": result.bench_points, "chip": decision["chip"],
            "players": [{"id": pid, "name": name(pid), "points": pts(pid), "role": roles[pid]}
                        for pid in lineup.starting_xi + lineup.bench_order],
            "transfers": transfers,
            "auto_subs_detail": [f"{name(o)} off, {name(i)} on" for o, i in result.auto_subs]}


def score_gameweek(gw: int, mock: bool) -> list[dict]:
    base = base_dir(mock)
    bootstrap, _, _ = gameweek_inputs(gw, mock)
    players = players_from_bootstrap(bootstrap)
    positions = {pid: p.position for pid, p in players.items()}
    rules = load_rules()
    if mock and not get_event(bootstrap["events"], gw)["finished"]:
        live, source, average = fake_live(players, gw), "fake points (mock)", None
    else:
        final, fresh = gameweek_is_final(gw)
        if not final:
            raise SystemExit(f"Gameweek {gw} is not final yet (bonus points or data checks pending). Try later.")
        live, source = live_from_api(fetch.get(f"event/{gw}/live/", gw)), "official points"
        average = get_event(fresh["events"], gw).get("average_entry_score")

    rows = []
    for team in TEAMS:
        path = base / "decisions" / f"gw{gw}" / f"{team.id}.json"
        if not path.exists():
            continue
        state = TeamState.load(base / "teams" / team.id / f"gw{gw}.json")
        rows.append(_team_row(team, gw, read_json(path), state, players, positions, live, rules))
        if team.memory == "verified":
            # Check the decisions that cited lessons this gameweek; remove lessons that fail the rule.
            mem = memory.load_memory(base, team.id, "verified")
            mem = memory.evaluate(mem, gw, {pid: lp.points for pid, lp in live.items()},
                                  base / "memory" / team.id / "evaluations.csv")
            memory.save_memory(base, team.id, mem)
            for notice in mem["removed_notices"]:
                print(f"  {team.id}: {notice}")

    write_json(base / "scores" / f"gw{gw}.json", {"gw": gw, "source": source, "average": average, "teams": rows})
    write_csv(base / "scores" / f"gw{gw}.csv", [{k: r[k] for k in CSV_FIELDS} for r in rows], CSV_FIELDS)
    print(f"Gameweek {gw} scores ({source}" + (f", FPL average {average}" if average is not None else "") + "):")
    for row in sorted(rows, key=lambda r: -r["net_points"]):
        print(f"  {row['team']:<11} {row['net_points']:>4}" + (f"  (hit -{row['hit_points']})" if row["hit_points"] else ""))
    return rows
