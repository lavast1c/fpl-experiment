# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A season-long research experiment (FPL 2026/27): 9 Claude agents (Haiku/Sonnet/Opus 5.5 × no / self-written / verified memory) plus two rule-based bots manage **simulated** FPL teams scored by our own code. The full brief is @docs/BRIEF.md. Every methodological decision goes in `METHODS.md` with a date; user-visible changes go in `CHANGELOG.md`.

Work through the brief's phases one at a time and stop after each for review. The website (Vercel, reading Supabase) comes after phase 6.

## Hard constraints

- No paid API usage. Agents run only via `claude -p` on the user's subscription; no Anthropic API keys.
- Exact model IDs only: `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`. Never Fable, never aliases (`best`, `default`, `opus`, `sonnet`, `haiku`).
- Ask the user before every real `claude -p` agent call. The one exception is the weekly picks made by the automatic routine (`python run.py auto`, run every 3 hours by a scheduled cloud task since 2026-10-28, see `scripts/cloud_routine.md`; Windows Task Scheduler is the fallback): the user gave standing approval for those on 2026-10-27, and for running them in the cloud on 2026-10-28. Any other real call (tests, re-runs, extra calls) still needs asking. Use the mock agent during development.
- Never log in to, scrape, or control anything on the FPL website or any FPL account. Never use or show a real person's team (except the git-ignored scorer test cache in phase 3).
- Read the public API minimally: only through `experiment/fetch.py` (cache, per-gameweek cap, delay, no cookies). Never poll in a loop.
- Never hardcode FPL rules from memory. Read them from `bootstrap-static/` `game_settings`/`chips`, and list anything unverified for the user.

## Data and storage

- Files in `data/` are the source of truth and are committed (raw responses as `.json.gz`). Supabase is a copy: a failed Supabase write must warn, not stop a run; `python run.py sync` fills gaps.
- Supabase project: `fpl-agents-experiment` (ref `adijcrtvxrnvalezelhg`, org "FPL Experiment", free plan, ap-south-1). Never touch the user's other Supabase projects.
- Supabase schema changes go in new timestamped files in `supabase/migrations/` and are applied with the MCP `apply_migration` tool; never edit an applied migration.
- Secrets live in `.env` (see `.env.example`), never committed.

## FPL API gotchas

- Base URL `https://fantasy.premierleague.com/api/`; endpoints need the trailing slash.
- `bootstrap-static/`: `elements` = players, `teams`, `events` = gameweeks, `element_types` = positions. Join by ID; IDs change every season.
- Prices (`now_cost`) are in tenths of £m (`55` = £5.5m).

## Code and git

- Python 3, small commented files. The user explains this code in a write-up, so favour readability over cleverness.
- Cross-platform: `pathlib` paths and list-form `subprocess` calls.
- Run tests with `python -m pytest`.
- Commit after each meaningful change with a short imperative message, then push to `origin main` (public repo `lavast1c/fpl-experiment`).
- The automatic routine (`experiment/automation.py`) commits and pushes changes in `data/` to `main` by itself, so pull before pushing, and don't leave half-finished edits in `data/`. Its lock, status and log are in the git-ignored `automation/` folder; `python run.py auto --dry-run` shows what is due.
