# The automatic runs in the cloud

Since 2026-10-28 (METHODS.md) a Claude Code **scheduled cloud task** starts `python run.py auto` every 3 hours on
Anthropic's cloud computers, so the experiment keeps running while the project owner's PC is off. The cloud
session only runs the commands below; the weekly agent calls inside `run.py auto` are the same `claude -p`
calls, with the same flags, as on the PC (`experiment/agents.py`). This file records the exact setup so it can be
checked or rebuilt. The Windows schedule (`schedule_windows.ps1`) is the fallback; never run both at once.

## Cloud environment "FPL experiment" (claude.ai/code, set up by the project owner)

- **Network access:** Custom, with the default package-manager list plus
  `fantasy.premierleague.com`, `adijcrtvxrnvalezelhg.supabase.co` and `ntfy.sh`.
- **Environment variables:** `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `NTFY_TOPIC` (the same values as `.env`),
  and `BASH_DEFAULT_TIMEOUT_MS=3600000`, `BASH_MAX_TIMEOUT_MS=3600000` so a picks run can take up to an hour.
- **Setup script:** none.

`python run.py cloud-check --yes-real-call`, run once in this environment, checks all of this (it makes one
real `claude -p` call, so it needs the project owner's approval).

## Scheduled task "FPL experiment: automatic run"

- **Schedule:** `7 */3 * * *` (UTC): 00:07, 03:07, ... 21:07. Seven minutes past, because runs on the hour can
  start late.
- **Repository:** `https://github.com/lavast1c/fpl-experiment`. **Session model:** `claude-sonnet-5-5` (it only
  runs the commands). **Tools:** Bash, Read. **Connectors:** none.
- **Prompt:**

```
Automatic run of the FPL agents experiment in this repository (see CLAUDE.md, METHODS.md 2026-10-28 and
experiment/automation.py). The project owner gave standing approval for the weekly agent calls that
`python run.py auto` makes. Make no other `claude` calls.

Do exactly this, from the repository root, and nothing else:
1. git checkout -q main && git pull -q --ff-only origin main
2. git config user.name "Lavastic" && git config user.email "212013989+lavast1c@users.noreply.github.com"
3. python -m pip install -q -r requirements.txt
4. python run.py auto
   Run it in the foreground with the Bash tool's timeout set to 3600000 ms (picks can take up to an hour).
   If it is moved to the background, wait until it has finished.

Rules:
- Do not edit, fix, retry or re-run anything. The command commits and pushes the data itself.
- Never print the values of environment variables.
- If a step fails, stop and report the error.

Finish with the last 40 lines of the command's output.
```
