# Do AI agents learn from experience, or learn the wrong lessons from luck?

A season-long experiment in Fantasy Premier League (2026/27). Nine Claude agents (three model sizes × three kinds of memory) and two simple rule-based bots each manage a **simulated** FPL team. Every team is scored by this project's own code, using public FPL data.

> **Status:** the real season has started. Every team picked a fresh £100m squad for gameweek 8.
> Follow it live at **[fpl-experiment.vercel.app](https://fpl-experiment.vercel.app)**.

## The question

If you give an AI agent memory of its past decisions, does it actually improve over a season? FPL is very luck-heavy, so the agent might instead learn "superstitions" from random outcomes. And does the answer change with model size?

## Teams

| | No memory | Self-written memory | Verified memory |
|---|---|---|---|
| `claude-haiku-5-5` | H-none | H-self | H-verified |
| `claude-sonnet-5-5` | S-none | S-self | S-verified |
| `claude-opus-5-5` | O-none | O-self | O-verified |

Each model's three teams start from the same squad: the one its no-memory team picked in gameweek 8. So differences between them come from memory, not from a luckier first squad.

There are also four baselines, none of which uses AI:
- **form-bot:** buys and captains the players in the best recent form.
- **crowd-bot:** copies what most real managers own (the "template" team).
- **stats-bot:** picks by this project's own expected points (below): the toughest simple rule to beat.
- **FPL average:** the official average score of all real managers each gameweek.

All three bots mark a player's score down by FPL's chance of playing (75% keeps half the score, 50% a quarter, 25% or less nothing) and pick transfers by that score. Fully fit players always start and captain ahead of doubtful ones. The bots never take −4 hits or play chips.

### The three kinds of memory

- **No memory.** Each week the agent sees only this week's player data and its own squad, bank, free transfers and chips.
- **Self-written memory.** The agent also sees last week's results and its own notes. It rewrites those notes itself, with up to 8 notes and 300 words. We never edit them.
- **Verified memory.** The notes are numbered lessons. Every transfer and captain pick must cite the lessons behind it. After the gameweek, our code compares each cited pick with this project's expected points for that player at decision time. A lesson cited at least 5 times whose picks average more than 1 point below prediction is removed, and the agent is told why. The agent also sees each lesson's track record.

Every memory team is told: *"Your notes are advice, not commitments. Re-evaluate every decision from scratch."*

## How a gameweek works

1. **Fetch.** We download the public FPL data a few times a week. It is cached and rate-limited, and we never log in.
2. **Snapshot.** We build one table of all players: price, form, expected goals and assists, minutes, ownership, injury news and the next 3 fixtures with difficulty ratings. Every agent gets exactly the same table. FPL's own expected points (`ep_next`) are left out of it, so agents judge players from the underlying numbers; they are still saved in the dataset.
3. **Decide.** Each agent gets one prompt and returns one JSON answer. The answer contains transfers, the starting XI, the bench order, the captain, a chip and a short reasoning, plus notes or lessons for memory teams. Agent calls:
   - run one at a time with `claude -p`, using the exact model ID and effort `medium`;
   - have no tools and no web access;
   - each run from an empty folder;
   - all use the same prompt template.
4. **Validate.** A rule checker enforces every FPL rule: squad shape, budget, the 3-per-club limit, selling prices, free transfers, −4 hits, chips and formations.
   - An illegal answer is sent back with the errors, and the agent gets 2 retries.
   - If every retry fails, the team keeps last week's team.
   - Rule breaks are counted as results.
5. **Score.** Once FPL has finalised the gameweek, our scorer works out each team's points. It handles automatic substitutions, captain and vice-captain, and chips. Before we relied on it, it was checked against official scores of random public teams and matched exactly.
6. **Measure.** For each team we record:
   - points, rank, and the gap to the FPL average;
   - a luck-adjusted **expected points** score;
   - points lost to hits, rule breaks, retries and stale picks;
   - how often the team changes its mind (transfers and captain changes);
   - how its notes and lessons change.

Every methodological decision, with its date and reason, is in [`METHODS.md`](METHODS.md). The original brief is in [`docs/BRIEF.md`](docs/BRIEF.md).

## Expected points (the luck-adjusted score)

For each decision we add up the predicted points of the starting XI at decision time:
- the captain counts twice, or three times with triple captain;
- the bench counts too with bench boost;
- transfer hits are subtracted.

**Luck** = actual points − expected points. A team that scores well with low expected points was lucky. A team with high expected points made good decisions, whatever the result.

The predictions are our own (`experiment/xpoints.py`), not FPL's `ep_next`: FPL doesn't publish how `ep_next` is made, and for gameweek 8 the teams' `ep_next` totals were about double a normal score. For each player and fixture, ours adds appearance points (from recent minutes), goals and assists (his expected goals and assists per 90, scaled by his team's attack against the opponent's defence, home or away), clean-sheet and goals-conceded points, and his usual bonus, saves and defensive points. Point values come from the API, and nothing is tuned by hand. On gameweeks 4–7 it ranked players better than recent form or points per game, and its average error was 0.03 points per player per gameweek (`data/checks/xpoints_backtest.json`). On four past seasons (2022/23–2025/26, 125 test gameweeks, from a community copy of the FPL data) it also ranked players better than form (rank correlation 0.59 vs 0.55), and its average error was under 0.01 points per player per gameweek, with every position within 0.03 (`data/checks/xpoints_past_seasons.json`). That test chose its current settings: assists are scaled by how many FPL assists each position gets per expected assist, player rates are pulled firmly towards their position's average, and playing time mixes the last 4 matches with the whole season. Agents see neither our predictions nor FPL's `ep_next`. The stats bot picks by it, so its expected points are high by design.

## The open dataset

Everything a real run produces is committed to [`data/`](data/):

| Folder | Contents |
|---|---|
| `raw/` | every downloaded FPL response (gzip-compressed, timestamped) |
| `snapshots/` | the weekly player table every agent received |
| `rules/` | the rule settings published by the FPL API |
| `decisions/gw{N}/` | each team's accepted decision, attempts, rule breaks and token use |
| `logs/gw{N}/{team}/` | the exact prompt, and every raw agent reply with its validator result |
| `teams/{team}/` | each team's squad, bank, free transfers and chips after every gameweek |
| `memory/{team}/` | notes and lessons after every gameweek, and every lesson check (`evaluations.csv`) |
| `scores/` | points per team per gameweek, with each player's points and role |
| `xpoints/` | this project's expected points for every player, each gameweek (with FPL's `ep_next` alongside) |
| `archive/` | decisions replaced before a deadline, kept for transparency (see the README inside) |
| `results/` | all metrics per gameweek (`gw{N}.csv`), every row so far (`all_gameweeks.csv`), and the season table (`standings.csv`) |

The same results, decisions and memory are copied to a Supabase database. Anyone can read it, but only the project can write to it, and it will power the website. Raw prompts and replies stay in this repository only.

## Running it

You need Python 3.11+ and, for real runs, the [Claude Code](https://claude.com/claude-code) CLI logged in to a Claude subscription. No API key is used.

```
pip install -r requirements.txt
copy .env.example .env               # optional: Supabase credentials (cp on macOS/Linux)

python run.py fetch                  # download this gameweek's public data (cached, rate-limited)
python run.py snapshot               # build the player table every agent receives
python run.py decide --gw 9 --mock   # practice run with a fake agent (no Claude usage), saved in data/mock/
python run.py score --gw 9 --mock    # score the practice run (made-up points if not played yet)
python run.py metrics --mock         # rebuild the results files

python run.py decide --gw 9 --yes-real-calls   # real run: 9 agents + 3 bots (uses your Claude plan)
python run.py score --gw 9                     # after FPL has finalised the gameweek
python run.py sync                             # copy local data to Supabase (also done after real runs)

python -m pytest                     # run the tests
```

`decide` refuses to run after the deadline and warns when the deadline is less than 3 hours away. `--teams H-none,form-bot` limits a run to some teams.

### Automatic runs

Since gameweek 9 the weekly routine runs by itself (`experiment/automation.py`, decided 2026-10-27 in [`METHODS.md`](METHODS.md)). Windows Task Scheduler starts `python run.py auto` every hour and at log-on. Each run checks the saved files and does whatever is due:
- **Scoring:** from 18 hours after a gameweek's last match, it asks FPL at most every 12 hours whether the points are final, and scores the gameweek once they are.
- **Picks:** from 24 hours before each deadline, it downloads the data and runs every team's decision. It waits for last week's scores until 6 hours before the deadline.
- **Afterwards:** it pushes the new data to GitHub, copies it to Supabase, updates the status strip on the website and shows a pop-up.

If the computer is off until a deadline, the teams keep last week's team (outcome `missed`).

```
powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1   # set up the schedule (once)
python run.py auto --dry-run         # what is due now, from saved files only
python run.py auto                   # one run by hand (real downloads and calls if due)
```

## Code map

| File | What it does |
|---|---|
| `run.py` | the command line |
| `experiment/fetch.py` | the only code that talks to the FPL API (cache, limits, delay, no cookies) |
| `experiment/snapshot.py` | the weekly player table |
| `experiment/rules.py`, `validator.py`, `team.py` | FPL rules and team bookkeeping |
| `experiment/scorer.py` | points, auto-subs, captaincy, chips |
| `experiment/prompt.py`, `prompts/v2/` | the prompt template and answer format (`v1` was replaced before any gameweek was scored) |
| `experiment/agents.py` | the real Claude agent and the fake one used for testing |
| `experiment/memory.py` | self-written notes and verified lessons |
| `experiment/bots.py` | the form bot and the crowd bot |
| `experiment/runner.py` | the weekly `decide` and `score` |
| `experiment/metrics.py` | results, expected points and the season table |
| `experiment/xpoints.py`, `xpoints_check.py`, `xpoints_past.py` | this project's expected points, and its checks on this season's past gameweeks and on four past seasons |
| `experiment/automation.py`, `notify.py`, `scripts/schedule_windows.ps1` | the automatic weekly routine, its pop-ups and its schedule |
| `experiment/supabase_sync.py`, `supabase/migrations/` | the database copy |
| `website/` | the public website (Next.js on Vercel), reading the database with the read-only key |

## What this project does not do

- No FPL accounts, logins or submitted teams.
- No real person's team in the results.
- No paid API usage.

## Licence

Code: MIT (see [`LICENSE`](LICENSE)). FPL data belongs to the Premier League.
