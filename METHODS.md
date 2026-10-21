# Methods

Every methodological decision, with the date it was made. Once the season starts, decisions here stay fixed. Any change is logged as a new dated entry and never edited in place.

## 2026-10-21: Project setup

- **Storage.** Files in `data/` are the source of truth and are committed to this repository as the open dataset. Every run also copies them to a Supabase database (for the future website). If the Supabase write fails, the run carries on, and `python run.py sync` copies the missing data later.
- **Raw API responses** are committed gzip-compressed (`data/raw/gw{N}/{endpoint}_{UTC timestamp}.json.gz`), so anyone can rebuild every snapshot from source.
- **Data access.** Only public, read-only FPL API endpoints. Requests go through one module that caches every response, waits between requests, caps how many times each endpoint can be fetched per gameweek, and never sends cookies or logins.
- **Decision timing.** Each gameweek, all teams decide once, from the same snapshot, about 24 hours before the deadline. There are no mid-week or daily transfers. Transfers use the prices in that snapshot.
- **Token measurement.** In phase 1, snapshot size is estimated as characters ÷ 3.5. Exact token counts are recorded from the real agent calls' usage data from phase 4 onwards.

## 2026-10-21: Phase 1, data and snapshot

- **Endpoints read so far:** `bootstrap-static/`, `fixtures/`, `event-status/` only. Limits: responses reused for 6 h (1 h for `event-status/`), at most 4 downloads per endpoint per gameweek, 3 s between requests.
- **Gameweek folders.** Data is filed under the *decision gameweek*: the next deadline, or the current gameweek if there is no next one.
- **Snapshot columns:** id, name, club, position, price (£m), form, points per game, total points, minutes, xG, xA, `ep_next`, ownership %, status, chance of playing next round, news, and the next 3 gameweeks' fixtures (`GW9 LIV(A,4)`; `-` = blank, `+` = double; the number is FPL's difficulty for that club). News has line breaks collapsed and `|` replaced with `/`. Rows are sorted by position, club, id. Agents receive the pipe-separated table saved as `data/snapshots/gw{N}_table.txt`.
- **Snapshot filter:** `all` (every player in the game), chosen 2026-10-21 for now. It may still change before the first real gameweek, and will then be fixed for the season. Candidates (GW8 data): all 668 players (~21.8k tokens); `played`, minutes > 0, 449 players (~13.9k); `played_or_owned`, also 0-minute available players owned by ≥ 0.5%, 469 players (~14.5k). `played_or_expected` (minutes > 0 or `ep_next` > 0) was identical to `played`, because every 0-minute player has `ep_next` = 0.
- **Rules read from the API** (`data/rules/2026-27_api_rules.json`): squad of 15; max 3 per club; £100.0m budget; 2/5/5/3 by position with XI limits GK 1, DEF 3–5, MID 2–5, FWD 1–3; selling keeps 50% of a price rise (`transfers_sell_on_fee` 0.5); up to 4 extra banked free transfers; vice-captain enabled. Chips come in two sets (one for GW1–19, one for GW20–38): wildcard, free hit, bench boost, triple captain. The full points table is in `game_config.scoring`.

## 2026-10-22: Phase 2, the rule checker (validator)

- **Where rules come from.** Rules the API publishes are read from `data/rules/2026-27_api_rules.json`. Rules it doesn't publish are written once, in `experiment/rules.py` (`UNVERIFIED_RULES`), and must be confirmed by hand on the FPL site (list below). No other code may hardcode an FPL rule.
- **Money** is handled in tenths of £m (whole numbers), as the API does, so there are no rounding errors.
- **All or nothing.** An answer with any error is rejected as a whole: no part of it is applied. Every error has a code (e.g. `CLUB_LIMIT`, `OVER_BUDGET`, `XI_FORMATION`) and a message that is sent back to the agent.
- **Retries.** After an illegal answer the agent gets the error messages and may try again, up to 2 more times. When building its **first squad**, a team gets 3 extra retries (6 attempts in total), because picking 15 players from scratch is harder. If every attempt fails, the team makes no changes: no transfers, no chip, last week's lineup. A team that fails its first squad scores 0 that week and tries again the next week.
- **Stale picks.** Buying a player whose id doesn't exist (`UNKNOWN_PLAYER`), or who has status `u` (unavailable: left the club or the league; `UNAVAILABLE_PLAYER`), is rejected and also counted as a stale pick. A player already in a squad who later becomes unavailable is not a stale pick; the team can keep him.
- **Hits.** No limit beyond FPL's own rules. Each transfer beyond the free transfers costs the hit cost (4 points, unverified). Wildcard and free hit weeks have no hits.
- **Bench.** If the agent doesn't put the substitute goalkeeper first on the bench, the checker moves him there and keeps the agent's order for the outfield subs. This is recorded as a note, not an error.
- **First week.** A new team gives a full 15-player `squad` instead of transfers. It can't play a wildcard or free hit that week, but bench boost and triple captain are allowed.
- **Players removed from the game** (very rare): a team must transfer them out, and they sell for their purchase price.
- **Rules the API does not publish (to be confirmed on the FPL site):** a hit costs 4 points; you gain 1 free transfer per gameweek; you can save up to 5 (read from `max_extra_free_transfers` = 4, whose exact meaning isn't documented); selling price is rounded down to £0.1m; only one chip per gameweek; wildcard and free hit don't use up saved free transfers; the free hit squad reverts the next week; a new mid-season team has 1 free transfer after its first week; no wildcard or free hit in a team's first week; the substitute goalkeeper always sits first on the bench. Also unexplained: the API's `transfers_cap` = 20 (not used).

## 2026-10-22: Manual rules confirmed, one correction

- The project owner checked the rules listed above on the FPL site and confirmed them, with **one correction**: in a wildcard or free hit week, saved free transfers are kept but **no new free transfer is gained** (not "+1 as usual"). The code now does this. The rule list now lives in `MANUAL_RULES` in `experiment/rules.py`, marked as confirmed on 2026-10-22.
- **Formations.** The starting XI limits come from the API (GK exactly 1, DEF 3–5, MID 2–5, FWD 1–3, 11 players). That allows exactly 8 formations: 3-4-3, 3-5-2, 4-3-3, 4-4-2, 4-5-1, 5-2-3, 5-3-2 and 5-4-1. A test checks that every one of them passes and every other combination fails.

## 2026-10-22: Phase 3, the scorer and its check against official scores

- **Player points are FPL's own.** Each player's gameweek points and minutes come from the public `event/{gw}/live/` data (now an allowed endpoint, saved like other raw data). Our code only does the team-level part (`experiment/scorer.py`).
- **Automatic substitutions** (not on bench boost weeks): the starters are gone through in XI order (GK, DEF, MID, FWD). Each one who played 0 minutes is replaced by the highest-priority bench player who played and keeps a valid formation. The goalkeeper can only be replaced by the bench goalkeeper, and outfield players only by outfield players.
- **Captain:** ×2, or ×3 with triple captain. If the captain played 0 minutes, the vice-captain gets the multiplier; if neither played, nobody does.
- **Bench boost:** all 15 players' points count and no substitutions are made. Transfer hits are taken off separately.
- **Check against real teams** (`python run.py check-scorer`, run once on 2026-10-22):
  - *Choosing teams.* Teams were chosen at random positions in the Overall league (unseeded, never recorded). Names were removed as soon as each response arrived. Everything was kept only in the git-ignored `data/test_cache/` and deleted afterwards. No team number or name is published.
  - *Requests.* 81 league-table pages, 80 team histories and 98 team-week lineups (259 requests), plus the 7 public `live` files.
  - *Scoring:* **98 team-weeks from 16 teams across GW1–7: every gameweek total and every bench total matched FPL exactly**, as did the players brought on by automatic substitution. This covered triple captain 6 times, bench boost 4, wildcard 5 and free hit 1, plus 43 weeks with automatic subs and 3 where the vice-captain took the armband.
  - *How subs were tested.* FPL's lineup pages already show the lineup after substitutions, so the check first undoes them and lets our scorer redo them. Because FPL re-sorts the XI afterwards, the original order of two starters in the *same* position can't be recovered. So the check compares the players brought on and the positions of the players taken off; the exact pairs also matched in 39 of the 43 weeks.
  - *Free transfers and hits:* **518 team-weeks from 80 teams were replayed with our rules, with 0 differences** from the official hit costs. This includes 25 wildcard or free hit weeks and 54 weeks with a hit. The check is sensitive: a 3-point hit would have caused 54 differences, and gaining a free transfer in wildcard or free hit weeks would have caused 6. The 5-transfer maximum was not exercised (no team saved 5 in seven weeks).

## 2026-10-22: Phase 4, prompt, answer format and runner

- **Framing.** Agents are told only that they manage an FPL team for the rest of the 2026/27 season and should score as many points as possible. They are not told about the experiment, other agents or the bots, so that nothing nudges their behaviour.
- **Prompt v1** (`prompts/v1/`): a short system prompt that *replaces* Claude Code's own coding-assistant prompt. The weekly template has these sections:
  - the rules, generated from `experiment/rules.py`, so the prompt can't disagree with the validator
  - the team's squad, bank, free transfers and available chips
  - (memory teams only, from phase 5) the memory section
  - the full player table
  - the answer format

  Every team gets identical text apart from its own squad and memory. Templates are versioned and never edited once the season starts. A change means a new version folder, logged here.
- **Answer format.** The format is forced with the CLI's `--json-schema`. The schema checks only the *shape* (which fields, numbers vs text); every FPL rule is checked by our validator. The answer also includes a short `reasoning` (at most 80 words).
- **Each real call** is `claude -p` with:
  - the exact model ID and `--effort medium` (the same for all)
  - `--tools ""` (no tools), `--strict-mcp-config` (no MCP servers), `--safe-mode` (no CLAUDE.md, plugins, hooks or skills) and `--disable-slash-commands`
  - `--no-session-persistence` (a fresh session every time; never `--continue` or `--resume`)
  - `--output-format json`, with the prompt sent on standard input
  - a run from a new empty temporary folder
  - API-key environment variables removed, so only the subscription can be used

  Model aliases and Fable models are refused in code. The models the CLI reports in `modelUsage` are logged for every call, and any mismatch is flagged.
- **Retries.** A retry is a new fresh call: the original prompt plus the rejected answer and the validator's error messages. If a call *itself* fails (usage limit, network, CLI error), that is not counted as the agent's attempt. Nothing is saved for that team, and re-running `decide` continues with the teams not yet decided. Teams are always run one at a time.
- **Logged per call:** the exact prompt, raw output, parsed answer, validator errors, stale picks, models used, input and output tokens, duration, and the CLI's API-equivalent cost figure (not billed; for information only). A token summary is printed after each run.
- **Mock runs** use a fake agent (random legal answers, with deliberate mistakes on about 30% of first attempts) and are saved in `data/mock/`, which is git-ignored and never part of the dataset. A six-gameweek mock season (54 team-weeks) ran without problems. It covered retries, eight kinds of rule errors, stale picks, 45 transfers, 32 hit points and all four chips. Tests also cover the no-squad and no-change fallbacks and the free hit reverting.
- **Scoring** (`run.py score`) only runs once FPL marks the gameweek final: bonus points added for every day of the gameweek, and the gameweek's data checked.
