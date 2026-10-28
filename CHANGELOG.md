# Changelog

## Unreleased

### Fixed
- Wildcard and free hit weeks keep saved free transfers but gain no new one.

### Added
- Project brief, README, MIT licence, METHODS and CHANGELOG.
- `run.py fetch`: cached, rate-limited, capped download of public FPL data.
- `run.py snapshot`: weekly player table for agents, plus the API's rule settings.
- `run.py sync`: copy of local data to Supabase (warns instead of failing).
- `run.py check-xpoints [--past]`: test our expected points on this season's played gameweeks, or on four past seasons from a community dataset (downloaded privately, not republished).
- First data: gameweek 8 snapshot.
- Rule checker (`experiment/validator.py`): squads, transfers, money, free transfers, chips and lineups, with error codes and stale-pick tracking.
- Team bookkeeping (`experiment/team.py`) and rule settings (`experiment/rules.py`).
- Scorer (`experiment/scorer.py`): automatic substitutions, captain/vice-captain, triple captain, bench boost.
- `run.py check-scorer`: one-off check against official scores of random public teams (passed exactly).
- Official player points for GW1-7 (`event/{gw}/live/`).
- Prompt v1, forced answer format, real and mock agents, `run.py decide` / `score` / `test-calls`.
- Memory (`experiment/memory.py`): self-written notes and verified lessons with citations, lesson checks against expected points, removal of lessons that keep underperforming, and last week's results in memory teams' prompts.
- Score files now include each player's points and role, transfers, automatic substitutions and FPL's average score.
- Form bot and crowd bot (`experiment/bots.py`): rule-based baseline teams, run after the AI teams in `decide`.
- Bots mark each player's score down by FPL's chance of playing (75% keeps half, 50% a quarter, 25% or less nothing) and decide for themselves whether to sell doubtful, injured or suspended players. Fully fit players start and captain first.
- Metrics (`experiment/metrics.py`, `run.py metrics`): rank, expected points and luck, gap to the FPL average, hits, rule breaks, stale picks, transfers, captain changes, memory changes, and the season table.
- Supabase tables for the website (teams, decisions, results, standings, notes, lessons), readable by anyone and writable only by the project. Real runs sync automatically.
- Full README.
- First real gameweek (8): all 9 AI teams and both bots picked their first squads.
- Shared start: each model's memory teams start from the squad its no-memory team picked (gameweek 8 redone without new calls; the original picks are archived).
- Our own expected points (`experiment/xpoints.py`), checked on gameweeks 4-7, replace FPL's ep_next for the luck score and lesson checks.
- Stats bot: a third rule-based team that picks by our expected points.
- Prompt v2: FPL's ep_next removed from the agents' player table; the nine AI teams picked their gameweek 8 squads again (earlier picks archived).
- Expected points, season version: assists scaled per position, a stronger pull to the average, and 25% whole-season playing time, chosen on four past seasons. The stats bot picked its gameweek 8 squad again (earlier pick archived); all gameweek 8 expected points recalculated.
- Website (`website/`): season table, team pages with every decision, memory and lessons, and an About page.
- Automatic weekly runs (`run.py auto`, every hour via Windows Task Scheduler): scoring once FPL confirms the points, the weekly picks 24 hours before each deadline, pushes to GitHub and Supabase, phone alerts (ntfy), and a status strip on every page of the website.
- Missed deadlines: teams without a decision keep last week's team (outcome `missed`, counted as `missed_weeks`, not as failed weeks). No decision starts after a deadline.
- `run.py cloud-check`: checks that a cloud session can reach everything the automatic runs need.

### Changed
- The automatic runs moved to a Claude Code scheduled cloud task, every 3 hours (`scripts/cloud_routine.md`), so they keep going while the PC is off. The Windows schedule is now the fallback.

### Fixed
- After a deadline, the download limit for `bootstrap-static/` is counted in the new gameweek's folder.
