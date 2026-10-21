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
