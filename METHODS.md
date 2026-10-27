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
  - *First squad:* go down the ranking and buy each player with a chance of playing above 0% who still fits the position counts and the 3-per-club limit. A player is only bought if enough money is left to fill every remaining place with the cheapest such players. (Changed the same day, see below.)
  - *Transfers:* the bots never take a −4 hit and never play chips. While free transfers are left, they make the single swap with the biggest ranking gain, as long as the gain is positive. Unused transfers are saved. (Changed the same day, see below.)
  - *Lineup:* by ranking. The best goalkeeper starts, then the minimum of each outfield position, then the best remaining outfield players. The bench goalkeeper comes first. Captain and vice-captain are the two best-ranked starters. (Changed the same day, see below.)
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

## 2026-10-22: Bots weigh fitness themselves

Decided with the project owner, before the season starts. Code in `experiment/bots.py`.

- **Rule.** Each bot's ranking number (form or ownership) is marked down by FPL's `chance_of_playing_next_round` to give the player's score. FPL leaves that field empty when there is no news; we then use 100%, or 0% if the status is `i`, `s`, `u` or `n`. The mark-down is steeper than the chance itself, because doubtful players often miss out or play only a few minutes: 100% keeps the whole score, 75% half, 50% a quarter, and 25% or 0% nothing.
- **Revised the same day.** A first version kept a 75% player at 75% of his score. The project owner pointed out that 75% players often don't start, or play only briefly, so we switched to the steeper mark-down above before any real gameweek was run.
- **No forced sales.** Earlier the same day, the bots always sold injured, suspended and unavailable players and never sold doubtful ones. Now the normal "biggest positive gain" rule decides: a player is sold only when an affordable replacement scores higher than what is left of his score. So a star at 75% (half his score) may still be kept if no affordable replacement beats that, while a cheap injured bench player may stay if there are better uses for the free transfer.
- **The one exception.** A player missing from FPL's data altogether can't be scored or fielded, so he is replaced first. Players who leave their club usually stay in the data with a 0% chance, and the bots weigh those like anyone else.
- **Buying.** Bots never buy a player whose score is marked down to nothing (25% chance or less). They may buy a 50% or 75% player if his marked-down score is still high enough.
- **Lineup and captain.** Fully fit players start ahead of doubtful ones, whatever the score; then players are ordered by score. A doubtful player starts only when no fit player can fill the place, and the captain and vice-captain are the first two starters in that order, so a doubtful player is never captain while fit players start.
- **Why.** The bots stay simple, fully repeatable and limited to the same snapshot data as the AI teams (no web news, which the agents don't get either), but they no longer need a hand-picked list of which statuses to sell.

## 2026-10-22: Snapshot filter fixed for the season

- **All players.** Decided with the project owner before the first real gameweek: every agent sees every player in the game (`SNAPSHOT_FILTER = "all"`), as in the phase 4 test calls. Nothing is hidden from the agents (new signings included), at the cost of a larger prompt. This stays fixed all season.

## 2026-10-22: Shared starting squad per model

Decided with the project owner, before the gameweek 8 deadline. Code in `experiment/runner.py` (`copy_first_squad`) and `experiment/teams.py`.

- **Problem.** There is one team per model and memory type. In the first week, a model's three memory types differ in nothing that matters (every memory starts empty), so their three different first squads were three random draws of the same model. That randomness would last all season and blur the memory comparison.
- **Rule.** Each model's no-memory team picks its first squad as before. Its self-written and verified teams then copy that squad, starting eleven, captain and vice-captain, with no Claude call. Their memory starts empty, and they first write notes or lessons in their next decision. If the no-memory team had no legal squad to copy, a memory team would pick its own.
- **Not changed.** The three models still pick their own first squads, so the model comparison includes squad building. The bots still build their own squads.
- **Gameweek 8.** The six memory teams had already picked their own squads in a real run earlier the same day (one extra retry for S-self). Those decisions, team states, memory and raw logs are kept unchanged in `data/archive/gw8_own_squads/`, and play no part in the scores.

## 2026-10-22: Our own expected points replace FPL's ep_next

Decided with the project owner, before any gameweek was scored. Code in `experiment/xpoints.py`; check in `experiment/xpoints_check.py`.

- **Why.** FPL doesn't publish how `ep_next` is calculated, and many managers treat it as crude. For gameweek 8 the teams' starting elevens added up to 92–110 `ep_next` points, about double a normal score. Two parts of the experiment depend on it: the luck-adjusted score, and verified memory's lesson checks. Paid projections (Opta, FPL Review) were ruled out, because the project only uses free public FPL data and must be able to publish everything.
- **The model (fixed for the season; three settings were changed on 2026-10-23, before any gameweek was scored, see below).** For each player and fixture it adds up:
  - appearance points, from how often he played 60+ or 1–59 minutes in his team's last 4 matches;
  - goals and assists: his season expected goals and expected assists per 90, times his expected minutes, times this fixture's expected team goals relative to his team's average. Expected team goals = league average × team attack × opponent defence × home or away factor, all measured from this season's xG;
  - clean-sheet points, using a Poisson chance of conceding 0;
  - goals-conceded points per goal, measured from this season's official point breakdowns;
  - everything else (bonus, saves, defensive contributions, cards), from his own average per 90.

  Doubles add fixtures and blanks score 0. Player rates are shrunk towards the position average as if he had also played 450 average minutes. Team ratings are shrunk towards the league average as if the team had also played 4 average matches. Point values come from `game_config.scoring`, and the minute thresholds are measured from the breakdowns (both 60 this season). Next gameweek's value is multiplied by FPL's chance of playing (`xp`), and the bots use the value if fit.
- **Check (gameweeks 4–7, each predicted only from earlier gameweeks).** Average over the four weeks:

  | Method | Rank correlation | Error (points) | Points of top 50 picks |
  |---|---|---|---|
  | Our xP | 0.501 | 1.82 | 4.03 |
  | Recent form | 0.461 | 1.96 | 3.89 |
  | Points per game | 0.463 | 1.95 | 3.87 |

  Total predicted points (players expected to play) against the real total: 858 vs 890, 857 vs 941, 860 vs 871 and 861 vs 851. That is 3% low overall, and 1–9% off in any single week. (Corrected the same day; this first said "within about 5% each week", which was wrong for gameweek 5.) FPL's past `ep_next` values were never saved, so it can't be part of this check. From gameweek 8 on, both are saved every week (`data/xpoints/`), so the two can be compared during the season. The settings (450 minutes, 4 matches) were chosen before the check. Trying 180–450 minutes and 2–4 matches changed the results by less than the week-to-week noise, so they were left as chosen.
- **Where it's used.** The expected points of every decision (and so luck), and verified memory's lesson checks. The verified teams' instructions now describe the check this way; their earlier wording, naming `ep_next`, was never used for a counted decision. Agents don't see our predictions, and their player table (which includes `ep_next`) is unchanged.
- **Gameweek 8.** Decided before the switch. The expected points were recalculated with `runner.recompute_expected_points(8)`, using only data from before the deadline.

## 2026-10-22: Stats bot

- A third rule-based team, `stats-bot`, gives a stronger simple yardstick than form or ownership. It follows the same bot rules (fitness mark-down, fit players start first, free transfers only, no hits, no chips). It ranks players by our expected points if fit: the next 3 gameweeks' total for buying and selling, and next gameweek's value for the lineup and captain. It started in gameweek 8 like every other team.
- Its expected points are high by design, because it picks by the same predictions that measure expected points. So its luck score shows how the predictions performed rather than its decision-making.
- The bots don't affect the AI teams; they only answer the side question of whether the AI teams beat simple rules.

## 2026-10-22: FPL's expected points removed from the agents' table (prompt v2)

Decided with the project owner, before the gameweek 8 deadline and before any points were scored.

- **Why.** FPL doesn't publish how `ep_next` is calculated. In the first picks it echoed short hot streaks: Chelsea's Henderson had 270 minutes, form 10.5 and `ep_next` 10.5, against 3.0 in our prediction. Haiku captained him over Haaland because his `ep_next` was higher. We want each model's own judgement from the underlying numbers, not how far it trusts FPL's headline figure.
- **Change.** Prompt `v2` is identical to `v1` except that the player table, and its description, no longer include `ep_next`. Everything else is unchanged: form, points per game, total points, minutes, xG, xA, ownership, status, chance of playing, news, and fixtures with difficulty. `ep_next` is still saved in the snapshot CSV, the database and `data/xpoints/` for comparison. `prompts/v1/` stays unchanged. This is a small loss of realism, because real managers can see `ep_next`.
- **Gameweek 8 redone.** The nine AI teams' earlier picks (prompt v1) were archived unchanged in `data/archive/gw8_with_fpl_predictions/`. The three no-memory teams then picked again with prompt v2, and their memory teams copied those squads (shared start). The redo applies to every AI team because the input changed, not because of any particular pick. The player data was the same download as before (14:32 UTC, under the project's 6-hour cache limit, so not downloaded again). The three bots were not re-run: they never used `ep_next`, and their data had not changed.
- **Tokens.** The table is about 3.5% shorter (estimate ~21,000 tokens instead of ~21,800).

## 2026-10-23: Expected points tested on four past seasons

Asked for by the project owner after a line-by-line review of the predictor. Code in `experiment/xpoints_past.py` (`python run.py check-xpoints --past`); results in `data/checks/xpoints_past_seasons.json`.

- **Why.** The first check had only 4 test gameweeks (4-7 of this season), too few to tell real flaws from luck. The review of those weeks suggested several changes; this test decides which ones hold up.
- **Data.** FPL's API only serves the current season. Past seasons come from Vaastav Anand's "FPL Historical Dataset" (https://github.com/vaastav/Fantasy-Premier-League), a community copy of the public FPL API with one row per player per match. It is pinned to commit `d7b05b5` (22 October 2026) so the test can be repeated. GitHub doesn't recognise its licence, so the files are downloaded into the git-ignored `data/past_seasons/` and not republished; only our summary numbers are committed. Seasons 2022/23 to 2025/26, the ones with xG and xA. FPL only published xG from gameweek 16 of 2022/23, so that season is treated as starting there. 125 test gameweeks in all.
- **Method.** The dataset has no official point breakdowns, so the test rebuilds them from each match's stats in the API's format, using this season's point values from `game_config`. On about 93,000 matches where only appearance, goals, assists, clean sheets and goals conceded could score, these values gave the official total every time, in every season (0 mismatches). Each gameweek from 4 on is then predicted by the predictor's own code from the earlier gameweeks only. Every player who had already played and whose club played that week is included, predicted "if fit" because we have no past injury news. Scores: rank correlation; actual points of the 50 players rated highest; RMSE, which replaces MAE because MAE rewards predicting too low when most players score 1-2 and a few score a lot; and average bias (predicted minus actual) overall, for the top 50 and top 15, and by position.
- **FPL's own predictions can't be used as a yardstick here.** The dataset's `xP` (FPL's `ep_this`) was saved after the matches: players who scored 10+ in a gameweek had that gameweek's `xP` about 3 points higher than the week before, while players who scored 1-2 had it 0.3-0.5 lower. The dataset's own documentation says its timing is uncertain. Recent form (average of the last 4 gameweeks) is the simple yardstick instead.
- **Results, all four seasons (points per player per gameweek):**

| Version | Correlation | Top-50 actual | RMSE | Bias | Top-50 bias | Top-15 bias | GKP bias | DEF bias |
|---|---|---|---|---|---|---|---|---|
| Original version (2026-10-22) | 0.593 | 4.30 | 2.452 | -0.06 | +0.21 | +0.26 | +0.02 | -0.05 |
| Goals-conceded change only | 0.591 | 4.32 | 2.455 | -0.02 | +0.24 | +0.30 | +0.12 | +0.04 |
| Assists-by-position change only | 0.593 | 4.31 | 2.454 | -0.01 | +0.34 | +0.41 | +0.02 | -0.03 |
| Clean-sheet change only | 0.592 | 4.30 | 2.453 | -0.04 | +0.25 | +0.29 | +0.06 | -0.02 |
| Stronger pull to average (900 minutes) only | 0.593 | 4.32 | 2.453 | -0.06 | +0.09 | +0.09 | +0.02 | -0.05 |
| 25% whole-season minutes only | 0.594 | 4.32 | 2.439 | -0.04 | +0.07 | +0.06 | +0.03 | -0.04 |
| **Season version:** assists + pull 900 + season 25% | 0.595 | 4.32 | 2.442 | -0.00 | +0.10 | +0.06 | +0.03 | -0.03 |
| Goals conceded + assists + pull 900 + season 25% | 0.593 | 4.34 | 2.444 | +0.04 | +0.14 | +0.10 | +0.13 | +0.06 |
| Form (last 4 gameweeks) | 0.550 | 3.71 | 2.670 | -0.05 | +1.97 | +3.14 | -0.01 | -0.05 |

- **What it shows.**
  - The original version holds up: it ranks players clearly better than form in every season (0.58-0.61 against 0.53-0.57), its overall bias is -0.06 points per player per gameweek, and no position is off by more than 0.07.
  - Two of the three "mistakes" found on this season's four weeks were mostly chance. Over four seasons clean sheets are not under-predicted (a team's predicted clean-sheet chance averaged 25.1%, actual 23.6%), so the clean-sheet change makes predictions worse. The goals-conceded deduction really is too large (keepers and defenders: -8.3k points predicted against -6.4k actual), but it cancels a similar-sized over-estimate of their clean sheets, goals and appearances, so correcting it on its own leaves keepers 0.12 too high.
  - Assists are under-predicted because FPL awards more assists than expected-assist (xA) data counts, and by a stable amount per position: about 1.35 FPL assists per xA for midfielders, 2.1 for forwards and 1.1-1.3 for defenders in every season. Scaling each position's xA by its rate, measured each week from the season so far, removes the midfield and forward bias.
  - Over-confidence about the highest-rated players is real in every season (+0.21 points for the top 50 each week, +0.26 for the top 15). Pulling each player's rates harder towards his position's average (as if he had also played 900 average minutes, not 450) and mixing 25% of his whole-season playing time into the last-4-match figure fix most of it. The season mix also has the lowest RMSE. Mixing in 50% lowers the ranking quality, so it is not proposed.
  - No change improves the ranking much: every version's correlation is 0.592-0.595, and its top 50 scored 4.30-4.35 points.
- **Scoring rules in each tested season.** Checked on the web on 2026-10-23, because the test uses this season's point values for every season:
  - 2022/23: no change to how points were scored. It was the World Cup season, with unlimited transfers during the break. Five substitutes became permanent in the Premier League. ([AllAboutFPL](https://allaboutfpl.com/2022/07/2022-23-fpl-season-launch-new-rules-prices-positions-chips-in-fpl/))
  - 2023/24: the scoring system was the same as 2022/23. ([Fantasy Football Scout](https://www.fantasyfootballscout.co.uk/2023/07/05/fpl-2023-24-is-live))
  - 2024/25: a goalkeeper's goal went from 6 to 10 points. The bonus points system (BPS) changed, and the Assistant Manager chip was added. ([Yahoo Sport](https://uk.sports.yahoo.com/news/fpl-2024-25-changes-fantasy-104219212.html), [Fantasy Football Scout](https://www.fantasyfootballscout.co.uk/2024/08/20/the-new-bonus-points-system-how-did-it-affect-fpl-gameweek-1/))
  - 2025/26: defensive contribution points were added (2 points for 10 clearances, blocks, interceptions and tackles for defenders, or 12 including recoveries for midfielders and forwards). Assist rules were relaxed; FPL estimated this would have given 41 more assists in 2024/25. There were more BPS changes. ([Fantasy Football Scout](https://www.fantasyfootballscout.co.uk/2025/07/19/fpl-2025-26-more-assists-to-come-as-rules-are-relaxed), [Rotowire](https://www.rotowire.com/soccer/article/fpl-rule-changes-2025-26-season-assists-defensive-contributions-fantasy-premier-league-double-chips-94629))
  - 2026/27 (now): point values unchanged and defensive contributions kept. Only BPS changed (no BPS lost for being tackled, 1 BPS per 3 clearances, blocks and interceptions instead of per 2, and new save scoring), and scores now become final at 09:00 UK time the next day. ([Fantasy Football Scout](https://www.fantasyfootballscout.co.uk/2026/07/20/fpl-2026-27-5-rule-changes-new-features-announced), [Premier League](https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627))

  **Effect on the test: none on its conclusions.**
  - The five point values the test splits off (appearance, goals, assists, clean sheets, goals conceded) gave the official totals in every season. The keeper-goal change could not matter, because no keeper scored in any tested match.
  - Bonus, saves and defensive contributions fall in "everything else", which the predictor learns per player from the same season, so BPS changes and the new defensive points are learned, not assumed.
  - The 2025/26 assist change hardly moved FPL assists per xA (2025/26: defenders 1.29, midfielders 1.32, forwards 2.11, in line with earlier seasons). The predictor measures this rate from the current season each week anyway.
  - 2025/26 is the season closest to this one's rules, and there the season version also beats the original: bias -0.06 to +0.01, top-50 bias +0.29 to +0.16, top-15 bias +0.57 to +0.36, with the same ranking (0.584 to 0.587).
- **Decision (2026-10-23, with the project owner, before the gameweek 8 deadline and before any points were scored).** The predictor's season version is `xpoints.SEASON`: FPL assists per xA by position, the stronger pull (900 minutes) and 25% whole-season playing time. The goals-conceded and clean-sheet options stay off, because they made predictions worse over four seasons. `Settings()` keeps the original version for comparison. The season version is fixed from now on.
  - **Stats bot re-run.** It picks by these predictions, so it picked its gameweek 8 squad again (6 of 15 players changed, captain still Haaland). Its original pick is archived unchanged in `data/archive/gw8_stats_bot_original_xp/`. The AI teams and the other two bots were not re-run, because they never see our predictions.
  - **Expected points recalculated.** Every team's gameweek 8 expected points were recalculated with `runner.recompute_expected_points(8)`, using only data from before the deadline.
  - **This season's check.** `xpoints_check.py` now reports RMSE and bias instead of MAE. For gameweeks 4-7, the season version scores correlation 0.504, RMSE 2.69 and bias -0.03 points, against 0.461, 2.90 and +0.06 for recent form (`data/checks/xpoints_backtest.json`).


## 2026-10-27: Automatic weekly runs

- **Decision (with the project owner).** From gameweek 9 the weekly routine runs by itself on the project owner's Windows computer: Task Scheduler starts `python run.py auto` every 3 hours and at log-on (`scripts/schedule_windows.ps1`, `experiment/automation.py`). The project owner gave standing approval for the weekly `claude -p` calls it makes; every other real call still needs asking (CLAUDE.md).
- **What each run does.** It first looks only at saved files, and contacts FPL, Claude or GitHub only when a step is due:
  - **Scoring:** from 18 hours after a gameweek's last kick-off, it checks at most every 12 hours whether FPL has finished checking the points (the same test as before: bonus added for every day and `data_checked`), then scores the gameweek.
  - **Picks:** from 24 hours before each deadline it downloads the data, builds the snapshot and runs every team's decision. If last gameweek isn't scored yet, it waits until 6 hours before the deadline so the memory teams can see their results, and then picks anyway.
  - **Afterwards:** it commits and pushes the new files in `data/`, copies them to Supabase, updates a status panel on the website and shows a pop-up on the computer for finished jobs and problems.
- **Same table for every team.** The snapshot is built once per gameweek. A team whose call fails for a reason outside the agent's control (no internet, Claude usage limit, CLI error) saves nothing and is tried again by the next run with the same snapshot, until the deadline. Illegal answers are still handled as before (2 retries, then last week's team).
- **No decision starts after a deadline.** `decide` now checks the deadline before each team, not only at the start.
- **Missed deadlines.** If the computer is off or offline until a deadline, every team without a decision keeps last week's team, like an FPL manager who misses a deadline: no transfers, no chip, the same lineup and captain, and the free transfer is saved (`runner.record_missed`). The outcome is `missed`; it is counted as `missed_weeks`, not as the team's own `failed_weeks`. Expected points for a missed week come from the snapshot if one was built before the deadline; otherwise they are left empty, because data published after the deadline would leak results. All teams, AI and bots, follow the same rule.
- **Downloads stay inside the limits.** A score check costs one download of `bootstrap-static/` and `event-status/`, and one of each is kept back for the picks, so a gameweek folder never needs more than the 4 allowed. `fetch.get_bootstrap` now counts downloads in the folder the new copy will go into (after a deadline, the next gameweek's), not the folder of the newest copy.
- **Effect on the experiment.** None on what agents see or how teams are scored: the prompt, snapshot, validator, scorer and metrics are unchanged. Picks now usually happen about a day before the deadline, so late injury news can be missed, the same for every team.
