"""Phase 4 check with REAL calls (one probe + one real decision per model), run only with the user's OK.

It confirms, for each of the three models:
- the exact model ID is accepted, and the CLI reports that same model was used
- the effort level is accepted
- the agent has no tools (it is asked to list files, read a file and search the web)
- the agent runs in an empty folder and can't see project files
- a full gameweek prompt works end to end, and how many tokens it really uses
Results go to data/checks/ (committed), never into the experiment's decisions.
"""

import json
from datetime import datetime, timezone

from . import config
from .agents import CallContext, ClaudeAgent
from .files import write_json
from .prompt import answer_schema, build_prompt, load_template
from .rules import load_rules
from .runner import gameweek_inputs
from .team import TeamState, players_from_bootstrap
from .validator import validate
from .gameweeks import deadline

PROBE_PROMPT = """This is a short technical check, not a gameweek decision.
Try to do each of these three things, and report honestly what happened:
1. List the files in your current working directory.
2. Read the contents of a file called CLAUDE.md or README.md.
3. Search the web for today's date.
Then reply with the JSON object described."""

PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "could_list_files": {"type": "boolean"},
        "could_read_files": {"type": "boolean"},
        "could_search_web": {"type": "boolean"},
        "files_seen": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["could_list_files", "could_read_files", "could_search_web", "files_seen", "explanation"],
    "additionalProperties": False,
}


def _summary(record) -> dict:
    output = {}
    try:
        output = json.loads(record.raw_stdout)
    except json.JSONDecodeError:
        pass
    return {
        "model_requested": record.model_requested, "models_used": record.models_used,
        "model_mismatch": record.model_mismatch, "error": record.error,
        "num_turns": output.get("num_turns"), "permission_denials": output.get("permission_denials"),
        "input_tokens": record.input_tokens, "output_tokens": record.output_tokens,
        "duration_ms": record.duration_ms, "api_equivalent_usd_not_billed": record.api_equivalent_usd,
        "answer": record.answer, "command": record.command, "stderr_tail": record.raw_stderr[-1000:],
    }


def run(gw: int) -> None:
    out_dir = config.DATA_DIR / "checks" / f"phase4_test_calls_{datetime.now(timezone.utc):%Y-%m-%d}"
    bootstrap, table, meta = gameweek_inputs(gw)
    players, rules = players_from_bootstrap(bootstrap), load_rules()
    system = load_template("system.txt")
    when = f"{deadline(bootstrap['events'], gw):%Y-%m-%d %H:%M}"
    prompt = build_prompt(TeamState("test"), players, rules, gw, when, table)
    schema = answer_schema(first_week=True)

    for model in config.MODELS.values():
        agent = ClaudeAgent(model)
        print(f"{model}: probe call ...")
        probe = agent.call(system, PROBE_PROMPT, PROBE_SCHEMA, CallContext(TeamState("test"), players, rules, gw))
        probe_info = _summary(probe)
        write_json(out_dir / f"{model}_probe.json", probe_info)
        print(f"  models used {probe.models_used}, turns {probe_info['num_turns']}, error {probe.error}")
        print(f"  answer: {probe.answer}")

        print(f"{model}: full gameweek {gw} decision call ...")
        decision = agent.call(system, prompt, schema, CallContext(TeamState("test"), players, rules, gw))
        info = _summary(decision)
        if decision.error is None:
            result = validate(decision.answer, TeamState("test"), players, rules, gw)
            info["validator_errors"] = [str(e) for e in result.errors]
        write_json(out_dir / f"{model}_decision.json", info)
        print(f"  models used {decision.models_used}, tokens in {decision.input_tokens:,} out "
              f"{decision.output_tokens:,}, {decision.duration_ms / 1000:.0f} s, error {decision.error}")
        print(f"  validator: {info.get('validator_errors') or 'legal answer'}")
    print(f"\nSaved to {out_dir.relative_to(config.PROJECT_ROOT).as_posix()}")
