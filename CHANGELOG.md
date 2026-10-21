# Changelog

## Unreleased

### Added
- Project brief, README, MIT licence, METHODS and CHANGELOG.
- `run.py fetch`: cached, rate-limited, capped download of public FPL data.
- `run.py snapshot`: weekly player table for agents, plus the API's rule settings.
- `run.py sync`: copy of local data to Supabase (warns instead of failing).
- First data: gameweek 8 snapshot.
- Rule checker (`experiment/validator.py`): squads, transfers, money, free transfers, chips and lineups, with error codes and stale-pick tracking.
- Team bookkeeping (`experiment/team.py`) and rule settings (`experiment/rules.py`).
