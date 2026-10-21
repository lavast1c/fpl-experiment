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
