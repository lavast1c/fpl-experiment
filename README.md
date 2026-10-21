# Do AI agents learn from experience, or learn the wrong lessons from luck?

A season-long experiment in Fantasy Premier League (2026/27). Nine Claude agents (three model sizes × three kinds of memory) and two simple rule-based bots each manage a **simulated** FPL team. Every team is scored by this project's own code, using public FPL data.

> **Status:** under construction (phase 1 of 6: data fetching and the weekly player snapshot). Full documentation arrives in phase 6.

## The question

If you give an AI agent memory of its past decisions, does it actually improve over a season? Or, because FPL is so luck-heavy, does it learn "superstitions" from random outcomes? And does the answer change with model size?

## Teams

| | No memory | Self-written memory | Verified memory |
|---|---|---|---|
| `claude-haiku-5-5` | H-none | H-self | H-verified |
| `claude-sonnet-5-5` | S-none | S-self | S-verified |
| `claude-opus-5-5` | O-none | O-self | O-verified |

Baselines: a **form bot**, a **crowd bot** (most-owned players) and the **global average** score.

## What this project does not do

No FPL accounts, no logins, no submitting teams, and no real person's team appears in the results. See [`docs/BRIEF.md`](docs/BRIEF.md) for the full design and [`METHODS.md`](METHODS.md) for every methodological decision.

## Running it

```
pip install -r requirements.txt
copy .env.example .env        # optional: Supabase credentials (cp on macOS/Linux)
python run.py fetch           # download this gameweek's public data (cached, rate-limited)
python run.py snapshot        # build the player table every agent receives
python run.py sync            # copy local data files to Supabase
python -m pytest              # run the tests
```

## Licence

Code: MIT (see [`LICENSE`](LICENSE)). FPL data belongs to the Premier League.
