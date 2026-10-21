# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Python bot/automation for Fantasy Premier League (FPL), using the official FPL API. The project is new: no build, test, or lint setup exists yet. Re-run `/init` once it does.

## Git

- Remote is the private GitHub repo `lavast1c/fpl-experiment` (branch `main`).
- Commit after each meaningful change with a short imperative message, then push straight away.

## FPL API gotchas

- Base URL is `https://fantasy.premierleague.com/api/`. Endpoints need the trailing slash (e.g. `bootstrap-static/`, `fixtures/`, `element-summary/{player_id}/`, `event/{gw}/live/`, `entry/{team_id}/event/{gw}/picks/`).
- Public endpoints need no API key. Account actions (my team, transfers) need a logged-in session. Read credentials from environment variables / a `.env` file and never hard-code or commit them.
- `bootstrap-static/` is the main lookup: `elements` = players, `teams`, `events` = gameweeks, `element_types` = positions. Join other responses to it by ID instead of hard-coding names.
- Player, team, and fixture IDs change every season. Never hard-code them.
- Prices (`now_cost`) are in tenths of £m (`55` = £5.5m).
- The API is unofficial and undocumented. Cache responses, keep request rates low, and expect it to be slow or return errors around gameweek deadlines.
