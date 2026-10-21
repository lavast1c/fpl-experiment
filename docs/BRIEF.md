# Project brief: Do AI agents learn from experience, or learn the wrong lessons from luck?

I'm a high school student running a season-long experiment in Fantasy Premier League (FPL), the 2026/27 season, already in progress. I want you to help me build the system that runs it. Read this whole brief, ask me any clarifying questions first, then work through the phases at the end **one at a time**, stopping after each phase so I can review.

## 1. The research question

If you give an AI agent memory of its past decisions, does it actually improve over a season? Or, because FPL is so luck-heavy, does it learn "superstitions" from random outcomes? And does the answer change with model size?

## 2. Hard constraints (do not break these)

- **No paid API usage, ever.** The AI agents run through my existing Claude subscription using Claude Code in headless mode (`claude -p`). No Anthropic API keys, no other paid services.
- **Never use Fable models**, and never use the model aliases `best`, `default`, `opus`, `sonnet` or `haiku`. In headless mode Fable can bill usage credits without asking, and the aliases can silently change model mid-season. Always pass the exact model IDs below.
- **Ask me before running any real `claude -p` agent call.** Real calls use my plan's quota. During development, use a mock agent.
- **Simulated teams only.** Do not log in to the FPL website, create FPL accounts, use a browser to control any FPL team, or submit teams anywhere. All agent teams live in this project and are scored by our own code. FPL's 2026/27 Terms & Conditions allow only one account per person (paragraph 6), forbid registrations made by agents or third parties (paragraph 5), and forbid using automated systems to access the Game and extract information (paragraph 28(d)). So nothing in this project may touch the FPL website or any account.
- **Nothing personal.** This project has nothing to do with my own FPL team or my friends' teams. Never use, read or display any real person's team in the experiment or its results.
- **Keep API reading minimal.** We read the public FPL API only for data the experiment needs, which is a grey area under paragraph 28(d) even though many FPL tools do it. Fetch each endpoint at most a few times per gameweek, cache every response, never poll in a loop, add a delay between requests, and never send logins or cookies.
- **Never hardcode FPL rules from memory.** Rules change between seasons (chips, banked free transfers, etc.). Read them from the API's `game_settings`/`chips` data where possible, and tell me which rules you couldn't verify so I can check them on the FPL site.

## 3. The experiment design

### 3.1 AI agents: 9 teams

Three models × three memory types:

| | No memory | Self-written memory | Verified memory |
|---|---|---|---|
| `claude-haiku-5-5` | H-none | H-self | H-verified |
| `claude-sonnet-5-5` | S-none | S-self | S-verified |
| `claude-opus-5-5` | O-none | O-self | O-verified |

- **No memory:** each week the agent sees only this week's data snapshot, its current squad, bank and transfer situation. Nothing about past weeks.
- **Self-written memory:** same as above, plus last gameweek's results for its team and its own "lessons learned" notes (maximum ~300 words / 8 lessons). In the same call as its weekly decision, it returns updated notes. The agent decides what to remember; we never curate it.
- **Verified memory:** like self-written memory, but each lesson has an ID, and every decision (each transfer in, each transfer out, the captain pick) must cite the lesson IDs that influenced it. **Our code, not the model,** tracks how decisions tied to each lesson performed: compare each decision's actual points with its expected points at decision time. After a lesson has been used at least 3 times, delete it if its decisions averaged below expectation. The agent is told when a lesson was removed and why. Document the exact formula in `METHODS.md` and keep it fixed all season.

Every memory team's prompt must include: *"Your notes are advice, not commitments. Re-evaluate every decision from scratch."* (Feedback from others: memory agents tend to anchor on earlier decisions.)

### 3.2 Baselines: no AI calls

- **Form bot:** builds a legal squad greedily by `form` within budget and rules, captains the highest-form starter, makes at most its free transfers by greedy swaps.
- **Crowd bot:** same logic but by ownership (`selected_by_percent`), i.e. the template team.
- **Global average:** the average manager score each gameweek from the FPL API (an aggregate number, not any individual's team).

### 3.3 Fairness rules

- Every agent gets the **identical** data snapshot, the identical prompt template (differing only in the memory section), the same deadline and the same effort level.
- Pin exact model IDs and one `--effort` level supported by all three models (check `claude --help` and the docs; don't assume). Record the actual model used from the JSON output's `modelUsage` field on every call, and flag any mismatch.
- **No tools for agents.** Disable web search and all other tools so agents decide only from the prompt. Check `claude --help` for the current way to disallow tools (e.g. `--disallowedTools`) and confirm it works.
- **Isolation:** run each agent call from its own empty temporary directory, so no agent can read project files, other teams' notes, or results.
- Every call is a fresh session (no `--continue`/`--resume`).
- Run calls **sequentially**, not in parallel.

## 4. Technical design

Use **Python 3** and keep it simple and local-first: JSON/CSV files or SQLite, no web server and no database service yet. A website and Supabase come later. My laptop OS is [WINDOWS / MAC / LINUX], so make paths and subprocess calls cross-platform.

### 4.1 Data fetching (`fetch`)

Read-only FPL API endpoints (base `https://fantasy.premierleague.com/api/`):
- `bootstrap-static/`: players, teams, gameweeks (events), game settings, chips
- `fixtures/`
- `event/{gw}/live/`: live player points and stats for scoring
- `event-status/`: whether bonus points and data are final
- `entry/{id}/history/` and `entry/{id}/event/{gw}/picks/`: **only** for the scorer test in 4.6. Never stored in results, never committed, never shown.

Save every raw response to `data/raw/gw{N}/` with a timestamp. Work out the current and next gameweek and its deadline from `events`.

### 4.2 Snapshot (`snapshot`)

Build one compact table that every agent receives. For each player: `id`, name, club, position, price (`now_cost / 10`), form, points per game, total points, minutes, expected goals, expected assists, FPL's expected points (`ep_next`), ownership %, status, chance of playing next round, the injury/news text, and the next 3 fixtures with difficulty. Measure the snapshot's size in tokens and propose a way to keep it reasonable (for example, dropping players with zero minutes who aren't flagged as new signings), but **apply the same filter for everyone and document it**. Save each week's snapshot; it becomes part of the open dataset.

### 4.3 Rules and validator (`rules`)

Validate every agent answer and return machine-readable error codes:
- 15-player squad: 2 GK, 5 DEF, 5 MID, 3 FWD; starting £100.0m budget; max 3 players per club
- Starting XI of 11: exactly 1 GK, at least 3 DEF, 2 MID, 1 FWD; bench order given
- Captain and vice-captain both in the XI and different
- Transfers: free transfers, banked transfers, −4 point hits for extras, and correct **selling prices** (verify the current rule; historically you receive only half of any price rise, rounded down to £0.1m)
- Chips: read availability and rules for the current season from the API, and track each team's chips used
- Every player ID must exist in the current game. If an agent names a player who isn't in the game (left the Premier League, etc.), log it separately as a **stale pick**. That's a metric I want.

Illegal answer → send the validator errors back to the agent and retry, at most 2 retries. Log every failure; rule breaks are results, not just bugs. If all retries fail, the team makes no changes that week (document this rule).

### 4.4 Agent prompt and answer format

Write one prompt template with clear sections: rules summary, snapshot, current squad/bank/free transfers/chips, and (memory teams only) last week's results plus notes. The agent must reply with **only** a JSON object. Design the schema, including at least:
- `transfers` (out/in player IDs)
- `starting_xi`, `bench_order`, `captain`, `vice_captain`, `chip` (or null)
- `reasoning` (short)
- for memory teams: `updated_notes` (self) or `lessons` with IDs plus `lesson_ids_used` on each decision (verified)
- for the first gameweek: a full 15-player squad instead of transfers

Keep the template in a versioned file and never change it mid-season without logging the change.

### 4.5 Runner

Commands like:
- `python run.py decide --gw N`: refuses if the deadline has passed and warns if it's under ~3 hours away; runs all 9 agents plus the bots; validates; saves decisions
- `python run.py score --gw N`: only runs once the gameweek's data is final (check `event-status`)
- `--mock` flag: uses a fake agent that returns random legal (and sometimes deliberately illegal) answers, for testing without using quota

For each call, log: raw output, parsed JSON, validator results, retries, model actually used, tokens used, duration. Show a short token-usage summary at the end of each run so I can see how much of my plan the week used.

### 4.6 Scoring

Compute each simulated team's gameweek points exactly as FPL does: starting XI points, captain ×2 (×3 with triple captain), **automatic substitutions** (a starter who played 0 minutes is replaced in bench order while keeping a valid formation; GK only for GK; vice-captain takes the captaincy if the captain didn't play), transfer hits, and chip effects (bench boost, free hit reverting next week, etc.).

**Critical test:** pick 3–5 public team IDs at random from the API's overall league standings (not mine or my friends'). Run the scorer on their picks for several past gameweeks and confirm our totals **exactly** match their official scores in `entry/{id}/history/`. Try to include gameweeks with auto-subs and chips. Use this data only in a local test cache that is git-ignored and deleted after testing; never publish it or anyone's name. Also write unit tests for auto-subs and chips. Don't move on until this matches.

### 4.7 Metrics (per team, per gameweek and cumulative)

- Actual points and rank among all teams
- **Expected-points score** (luck-adjusted): the expected points of each decision at decision time (e.g. `ep_next` of the XI with captain doubled). Propose a simple formula, document it, keep it fixed
- Points lost to hits, rule violations by type, retries, stale picks
- **Anchoring:** number of transfers and captain changes per week (do memory teams change their minds less?)
- For memory teams: notes per week (with diffs), lessons created/removed, and which lessons survived verification

Output a tidy CSV and JSON per gameweek, plus a cumulative results file.

### 4.8 Repository

This will be a **public GitHub repo**. Include a clear README (what the experiment is, how it works, how to run it), an MIT license, `METHODS.md` for every methodological decision (with dates), and `CHANGELOG.md`. `.gitignore` the raw API cache if it's large. Logs, decisions, snapshots and memory notes **should** be committed: they're the open dataset.

## 5. Phases (stop after each one and report to me)

1. **Setup and data:** project structure, fetch with caching, snapshot builder. Show me a sample snapshot and its token size.
2. **Validator:** all rules with unit tests. List any rules you couldn't verify from the API.
3. **Scorer:** scoring with auto-subs and chips, then the exact-match test against random public teams.
4. **Prompt and runner:** prompt template, JSON schema, runner with `--mock`. Run a full mock gameweek. Then **ask me** before doing one real test call per model to confirm model IDs, effort, tool-blocking and isolation all work.
5. **Memory systems:** self-written and verified memory, including lesson tracking and pruning. Test with mock agents over several simulated gameweeks.
6. **Baselines, metrics and README:** form bot, crowd bot, global average, all metrics, and documentation.

After phase 6, we start for real at the next gameweek deadline: every AI team and both bots pick a fresh £100m squad.

Work in small, readable files with comments, since I'll explain this code in my write-up. If something in this brief is impossible, ambiguous, or a bad idea, tell me instead of guessing.
