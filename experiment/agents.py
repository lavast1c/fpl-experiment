"""The two kinds of agent: the real one (Claude Code in headless mode) and a mock for testing.

ClaudeAgent runs `claude -p` once per call, following the brief's fairness rules:
- exact model ID and the same --effort for everyone
- no tools (--tools ""), no MCP servers, and --safe-mode (no CLAUDE.md, plugins, hooks or skills)
- our own short system prompt instead of Claude Code's coding-assistant prompt
- a fresh, unsaved session each time (--no-session-persistence; never --continue/--resume)
- run from a new empty temporary folder, so it can't see any project files
- API-key environment variables are removed, so it can only use the user's subscription
- the answer shape is forced with --json-schema
MockAgent returns random answers (mostly legal, sometimes deliberately illegal) without using quota.
"""

import json
import math
import os
import random
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field

from . import config
from .rules import Rules
from .team import Player, TeamState
from .teams import check_model
from .validator import find_chip, validate

# Removing these guarantees `claude` can't fall back to paid API billing or another provider.
BLOCKED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_MODEL")


@dataclass
class CallRecord:
    """Everything logged about one agent call."""
    model_requested: str
    command: list[str]
    duration_ms: int = 0
    raw_stdout: str = ""
    raw_stderr: str = ""
    answer_text: str = ""            # the JSON text of the answer
    answer: dict | list | None = None
    error: str | None = None         # the call itself failed (timeout, CLI error, unreadable output)
    models_used: list[str] = field(default_factory=list)
    model_mismatch: bool = False
    input_tokens: int = 0            # all input, including cached
    cache_read_tokens: int = 0       # part of input_tokens re-read from the prompt cache (counts less)
    cache_creation_tokens: int = 0   # part of input_tokens written to the prompt cache
    output_tokens: int = 0
    num_turns: int = 0               # model turns in the call (the forced answer format adds one)
    api_equivalent_usd: float = 0.0  # what the CLI says the call would cost on the API; NOT billed
    mock: bool = False


@dataclass
class CallContext:
    """What the mock needs to invent an answer. The real agent ignores it (it only sees the prompt)."""
    state: TeamState
    players: dict[int, Player]
    rules: Rules
    gw: int
    is_retry: bool = False


def _parse_answer(text: str):
    """Read a JSON object out of the model's text, allowing for ```json fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


class ClaudeAgent:
    def __init__(self, model: str, effort: str = config.EFFORT):
        check_model(model)
        self.model, self.effort = model, effort

    def command(self, system: str, schema: dict) -> list[str]:
        executable = shutil.which("claude")
        if executable is None:
            raise RuntimeError("The `claude` command was not found.")
        return [executable, "-p",
                "--model", self.model,
                "--effort", self.effort,
                "--output-format", "json",
                "--tools", "",
                "--strict-mcp-config",
                "--safe-mode",
                "--no-session-persistence",
                "--disable-slash-commands",
                "--permission-mode", "dontAsk",
                "--system-prompt", system,
                "--json-schema", json.dumps(schema)]

    def call(self, system: str, prompt: str, schema: dict, context: CallContext) -> CallRecord:
        command = self.command(system, schema)
        # The log keeps the command without the (long, already logged) system prompt and schema.
        shown = [c if len(c) < 200 else f"<{len(c)} characters>" for c in command]
        record = CallRecord(self.model, shown)
        env = {k: v for k, v in os.environ.items() if k not in BLOCKED_ENV}
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="fpl-agent-") as empty_folder:
            try:
                process = subprocess.run(command, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                         cwd=empty_folder, env=env, timeout=config.CLAUDE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                record.error = f"timed out after {config.CLAUDE_TIMEOUT_SECONDS} s"
                return record
        record.duration_ms = int((time.monotonic() - start) * 1000)
        record.raw_stdout, record.raw_stderr = process.stdout, process.stderr[-5000:]
        try:
            output = json.loads(process.stdout)
        except json.JSONDecodeError:
            record.error = f"CLI exit code {process.returncode}; output was not JSON"
            return record

        usage = output.get("modelUsage") or {}
        record.models_used = sorted(usage)
        record.model_mismatch = record.models_used != [self.model]
        for numbers in usage.values():
            record.cache_read_tokens += numbers.get("cacheReadInputTokens", 0)
            record.cache_creation_tokens += numbers.get("cacheCreationInputTokens", 0)
            record.input_tokens += (numbers.get("inputTokens", 0) + numbers.get("cacheReadInputTokens", 0)
                                    + numbers.get("cacheCreationInputTokens", 0))
            record.output_tokens += numbers.get("outputTokens", 0)
        record.num_turns = output.get("num_turns") or 0
        record.api_equivalent_usd = output.get("total_cost_usd") or 0.0
        if output.get("is_error"):
            record.error = f"CLI reported an error: {str(output.get('result'))[:500]}"
            return record

        structured = output.get("structured_output")
        if structured is not None:
            record.answer, record.answer_text = structured, json.dumps(structured)
        else:
            record.answer_text = output.get("result") or ""
            try:
                record.answer = _parse_answer(record.answer_text)
            except json.JSONDecodeError:
                record.answer = None   # the validator reports this as NOT_AN_OBJECT
        return record


# --- mock agent ------------------------------------------------------------------------------

class MockAgent:
    """Random answers for testing the whole pipeline without using any quota.

    About `illegal_rate` of first attempts are deliberately broken in one of several ways
    (fewer on retries), so retries, error logging and the no-change fallback all get exercised.
    """

    MISTAKES = ("club_limit", "captain_not_in_xi", "unknown_player", "over_budget", "not_an_object")

    def __init__(self, model: str, seed: int, illegal_rate: float = 0.3, retry_illegal_rate: float = 0.1,
                 chip_rate: float = 0.15):
        check_model(model)
        self.model, self.rng = model, random.Random(seed)
        self.illegal_rate, self.retry_illegal_rate, self.chip_rate = illegal_rate, retry_illegal_rate, chip_rate

    def call(self, system: str, prompt: str, schema: dict, context: CallContext) -> CallRecord:
        answer = self._legal_answer(context)
        rate = self.retry_illegal_rate if context.is_retry else self.illegal_rate
        if answer is None or self.rng.random() < rate:
            answer = self._break(answer or {}, context)
        text = json.dumps(answer)
        return CallRecord(self.model, ["mock"], duration_ms=self.rng.randint(5, 50), raw_stdout=text,
                          answer_text=text, answer=answer, models_used=[self.model], mock=True,
                          input_tokens=math.ceil(len(system + prompt) / config.CHARS_PER_TOKEN),
                          output_tokens=self.rng.randint(300, 2500))

    # A legal answer is found by trying random ones until the validator accepts one.
    def _legal_answer(self, ctx: CallContext) -> dict | None:
        for _ in range(300):
            answer = self._random_first_week(ctx) if not ctx.state.has_squad else self._random_week(ctx)
            if answer and validate(answer, ctx.state, ctx.players, ctx.rules, ctx.gw).ok:
                return answer
        return None

    def _random_first_week(self, ctx: CallContext) -> dict | None:
        pool = [p for p in ctx.players.values() if p.status == "a"]
        self.rng.shuffle(pool)
        squad, clubs, cost = [], Counter(), 0
        need = {pos.id: pos.squad_count for pos in ctx.rules.positions.values()}
        for p in pool:
            if need[p.position] and clubs[p.club] < ctx.rules.club_limit:
                squad.append(p.id)
                need[p.position] -= 1
                clubs[p.club] += 1
                cost += p.price
        if any(need.values()) or cost > ctx.rules.budget:
            return None
        return {"squad": squad, **self._lineup(squad, ctx), "chip": None, "reasoning": "mock"}

    def _random_week(self, ctx: CallContext) -> dict:
        squad = set(ctx.state.squad)
        transfers = []
        for _ in range(self.rng.choice([0, 0, 1, 1, 1, 2])):
            out = self.rng.choice(sorted(squad))
            position = ctx.players[out].position
            options = [p.id for p in ctx.players.values()
                       if p.position == position and p.status == "a" and p.id not in squad]
            new = self.rng.choice(options)
            transfers.append({"out": out, "in": new})
            squad = (squad - {out}) | {new}
        chip = None
        if self.rng.random() < self.chip_rate:
            names = [c.name for c in ctx.rules.chips if find_chip(c.name, ctx.state, ctx.rules, ctx.gw)[0]]
            chip = self.rng.choice(names) if names else None
        return {"transfers": transfers, **self._lineup(sorted(squad), ctx), "chip": chip, "reasoning": "mock"}

    def _lineup(self, squad: list[int], ctx: CallContext) -> dict:
        by_position = {pos.id: [pid for pid in squad if ctx.players[pid].position == pos.id]
                       for pos in ctx.rules.positions.values()}
        for ids in by_position.values():
            self.rng.shuffle(ids)
        gk, df, md, fw = (by_position[i] for i in sorted(by_position))
        d, m, f = self.rng.choice([(3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 3, 2), (5, 4, 1)])
        xi = gk[:1] + df[:d] + md[:m] + fw[:f]
        bench = gk[1:] + [pid for pid in df[d:] + md[m:] + fw[f:]]
        captain, vice = self.rng.sample(xi[1:], 2)
        return {"starting_xi": xi, "bench_order": bench, "captain": captain, "vice_captain": vice}

    def _break(self, answer: dict, ctx: CallContext):
        mistake = self.rng.choice(self.MISTAKES)
        if mistake == "not_an_object" or not answer:
            return ["mock answer that is not an object"]
        answer = json.loads(json.dumps(answer))
        if mistake == "captain_not_in_xi":
            answer["captain"] = answer["bench_order"][-1]
        elif mistake == "unknown_player":
            if "squad" in answer:
                answer["squad"][-1] = 99999
            else:
                answer["transfers"] = [{"out": next(iter(ctx.state.squad)), "in": 99999}]
        elif mistake == "over_budget" and "squad" in answer:
            priciest = sorted(ctx.players.values(), key=lambda p: -p.price)
            answer["squad"] = [p.id for p in priciest[:15]]
        elif mistake == "club_limit" and "squad" in answer:
            first_club = ctx.players[answer["squad"][0]].club
            same = [p.id for p in ctx.players.values() if p.club == first_club and p.id not in answer["squad"]]
            answer["squad"][1:4] = same[:3]
        else:
            answer["vice_captain"] = answer["captain"]
        return answer
