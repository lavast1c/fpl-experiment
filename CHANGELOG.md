# Changelog

## Unreleased

### Fixed
- Wildcard and free hit weeks keep saved free transfers but gain no new one.

### Added
- Project brief, README, MIT licence, METHODS and CHANGELOG.
- `run.py fetch`: cached, rate-limited, capped download of public FPL data.
- `run.py snapshot`: weekly player table for agents, plus the API's rule settings.
- `run.py sync`: copy of local data to Supabase (warns instead of failing).
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
