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

## 2026-10-22: Phase 4 real test calls (6 calls, approved by the project owner)

Saved in `data/checks/phase4_test_calls_2026-10-22/`. The account is on the Claude Pro plan.

- **Models.** All three exact model IDs were accepted, and the CLI's `modelUsage` reported exactly the requested model every time (no mismatches). Opus is available on this plan. `--effort medium` was accepted by all three.
- **No tools.** In the probe call, every model reported that its only tool was the structured-output tool used for the forced answer format. None could list files, read files or search the web, and none tried a workaround. No permission requests were made.
- **Isolation.** Each call ran in a new empty temporary folder. The CLI still tells the model the working directory path and today's date. This is the same for every agent and reveals nothing about the project.
- **Real decisions** (gameweek 8 first-week prompt; test only, not part of the experiment):
  - Haiku and Opus gave legal squads first time.
  - Sonnet's answer broke the club limit (4 players from one club, despite its reasoning claiming "max 3"). In a real run it would get a retry.
  - Each call took 17–22 s.
- **Tokens.** Each decision call reported about 64,800 input tokens and 1,400–4,000 output tokens (Haiku used the most). The forced answer format makes each call two model turns, and the input total counts both. So the prompt itself is probably about 32,000 tokens: the earlier estimate of characters ÷ 3.5 (~21,800) was too low, because the number-heavy table packs fewer characters into each token. From now on, cached and uncached input tokens are logged separately, to show how much of the second reading comes from the prompt cache.

## 2026-10-22: Phase 5, memory systems

Decided with the project owner. Code in `experiment/memory.py`. These rules stay fixed all season.

- **What memory teams see.** Each memory team's prompt has a "Your memory" section, which is the only part of the prompt that differs between teams. It contains:
  - Last gameweek's results: the team's net points, any transfer cost, FPL's average manager score (`average_entry_score`), the chip played, each transfer with both players' points, every player's points and role (including who took the captaincy), and the automatic substitutions.
  - The team's notes (self-written) or lessons (verified).
  - The brief's sentence: "Your notes are advice, not commitments. Re-evaluate every decision from scratch."
  - In the first week, the results line says there are none yet.
- **Limits.** At most 8 notes or lessons and 300 words in total, counting kept and new lessons together. Going over is a **rule break**: the answer is rejected and gets a retry, like an illegal transfer. We never cut or edit the text ourselves, so what the agent remembers is entirely its own choice.
- **Self-written memory.** The answer has `updated_notes`, a list of texts that replaces the old notes completely.
- **Verified memory: lesson format.** The answer has `lessons: {"keep": [ids], "new": [texts]}`. A kept lesson's text can't be changed; to reword one, the agent drops it and adds a new one. New lessons get the next free id (L1, L2, ...), and ids are never reused. Lessons not kept are marked `dropped_by_agent`.
- **Verified memory: citations.** Every transfer has `out_lesson_ids` and `in_lesson_ids`, and the answer has `captain_lesson_ids`. Only lessons that existed before this week's answer can be cited, so a new lesson can be cited from the next week on. Citing a lesson that doesn't exist is a rule break and gets a retry.
- **Formula.** Each cited decision is valued against FPL's `ep_next` for that player, taken from the same snapshot the agent saw at decision time:
  - player bought: value = actual points − ep_next
  - player sold: value = ep_next − actual points (selling someone who then disappoints is good)
  - captain: value = actual points − ep_next (the player's own points, before doubling)

  A lesson's record is the average value over every decision that cited it. Several decisions in one week each count once. Players not in the live data count as 0 points. Every valued decision is saved in `memory/{team}/evaluations.csv`.
- **Removal rule (changed from the brief).** The brief said to remove a lesson after at least 3 uses if its decisions averaged below expectation. We use **at least 5 uses and an average below −1.0 point**. Reason: single FPL scores are very noisy, so with 3 uses and a threshold of 0, roughly half of all lessons would be removed by luck alone, even good ones. That would make the verified-memory teams test our noise rather than their lessons.
- **Telling the agent.** A removed lesson disappears from the list. The next prompt says which lesson was removed, its text, how many decisions cited it and their average. Each notice is shown once.
- **Track record shown.** Verified agents see each active lesson's record, for example "used 4 time(s), average +1.2 points vs expected" or "not used yet". This tells the agent how its lessons are doing. It is part of what makes the memory "verified".
- **When lessons are checked.** Lessons are checked when the gameweek is scored (`run.py score`), so the results are ready before the next decision.
- **Mock test.** Ten mock gameweeks (8–17, fake points) for all nine teams ran without errors. Two lessons were removed by the rule, and the removal notice appeared in the next prompt. 12 new tests cover the limits, citations, the formula, the removal rule, the prompt text and retries.

## 2026-10-22: Phase 6, bots, metrics and website data

Decided with the project owner. Code in `experiment/bots.py`, `experiment/metrics.py` and `experiment/supabase_sync.py`.

- **Bots.** The form bot ranks players by FPL `form`. The crowd bot ranks them by `selected_by_percent` (ownership). Ties go to the higher `total_points`, then the lower id, so runs are repeatable. Both use the same snapshot data as the agents, follow the same rules below, and go through the same validator.
  - *First squad:* go down the ranking and buy each available player (status `a`) who still fits the position counts and the 3-per-club limit. A player is only bought if enough money is left to fill every remaining place with the cheapest available players.
  - *Transfers:* the bots never take a −4 hit and never play chips. First they sell players who can't play (status `i`, `s`, `u`, `n`, or gone from the game) for the best-ranked affordable player in the same position. Then, while free transfers are left, they make the single swap with the biggest ranking gain, as long as the gain is positive. Unused transfers are saved. Doubtful players (status `d`) are not sold.
  - *Lineup:* available players first, then by ranking. The best goalkeeper starts, then the minimum of each outfield position, then the best remaining outfield players. The bench goalkeeper comes first. Captain and vice-captain are the two best-ranked starters.
  - *Fallback:* if a bot's answer breaks a rule (for example, a player left the game and no replacement is affordable), the bot keeps last week's team, the same rule the AI teams follow.
- **Bot chips: never.** The brief doesn't mention them, so we keep the bots as pure baselines. This slightly handicaps them against the FPL average.
- **Global average.** FPL's `average_entry_score` for each finished gameweek. It is shown in the results and the season table as the `fpl-average` row.
- **Expected points (luck-adjusted score), fixed for the season.** The formula is:
  - add up `ep_next` for the starting XI, taken from the snapshot at decision time;
  - count the captain twice, or three times with triple captain;
  - add the bench's `ep_next` with bench boost;
  - subtract transfer hits.

  It is worked out when the decision is made and saved in the decision file, because `ep_next` changes later. **Luck** = actual net points − expected points. A team that kept last week's team gets the expected points of that team.
- **Other metrics,** per team per gameweek in `results/gw{N}.csv`, all rows in `results/all_gameweeks.csv`, and season totals in `results/standings.csv`:
  - rank among the 11 teams (equal points share a rank);
  - the gap to the FPL average;
  - running season points and expected points;
  - outcome, attempts, rejected attempts (`rule_breaks`) and error codes with counts;
  - stale picks;
  - transfers made, and whether the captain changed from the team's previous decision (blank in a team's first week);
  - chip, automatic substitutions, bench points and tokens.
- **Memory metrics.**
  - *Self-written:* the number of notes, total words, and notes added or removed compared with the previous decision. Notes are compared by exact text, and the full lists are kept in the gameweek's JSON.
  - *Verified:* active, new and dropped lessons; lessons removed by the rule after scoring; and "proven" lessons (still active after at least 5 uses).
- **Website data (Supabase).** The website can read these tables publicly (read only):
  - results, standings, decisions (squad, transfers, lineup, captain, chip, reasoning, errors, tokens), notes and lessons;
  - gameweeks, including FPL's average;
  - snapshots and players.

  Only the project's secret key can write. The fetch log stays private. Raw prompts and agent replies stay in this repository only, because they are large (about 32,000 tokens per prompt). Only real runs are copied, never mock runs. Real `decide` and `score` runs sync automatically and only warn if Supabase fails. Migration: `20261022190000_phase6_results_and_public_read.sql`.
- **Mock test.** Eight mock gameweeks (8–15) for all 11 teams ran with no errors. 12 new tests cover the bots, the expected-points formula, the results files and the database rows. 81 tests pass in total. In mock runs the bots make no transfers, because the same snapshot is reused every week, so the rankings never change.
