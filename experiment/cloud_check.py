"""Check that a cloud session can do everything the automatic runs need (METHODS.md, 2026-10-28).

`python run.py cloud-check` changes nothing in data/ and reports:
1. the Python and `claude` CLI versions, and which sign-in variables agent calls remove (names only, never values)
2. whether the private settings are present (yes or no only)
3. one small FPL download (event-status/), saved in a temporary folder instead of data/
4. one read of the website's status row in Supabase
5. one test alert to the phone
6. a dry-run push to main (GitHub checks the permission; nothing is sent)
7. only with --yes-real-call: one very short real agent call (claude-haiku-5-5), made exactly the way the
   weekly picks make them. It is a real `claude -p` call, so it needs the project owner's approval (CLAUDE.md).
"""

import os
import platform
import subprocess
import tempfile
from pathlib import Path

import requests

from . import agents, config, fetch, notify, supabase_sync

TEST_MODEL = "claude-haiku-5-5"
NEEDED = ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "NTFY_TOPIC")
TIMEOUTS = ("BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS")   # let a long picks run finish in the cloud


def _command(*args: str) -> str:
    done = subprocess.run(list(args), capture_output=True, text=True, timeout=120, cwd=config.PROJECT_ROOT)
    if done.returncode != 0:
        raise RuntimeError(f"exit code {done.returncode}: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout.strip()


def claude_variables() -> list[str]:
    return sorted(k for k in os.environ if "ANTHROPIC" in k or "CLAUDE" in k)


def check_versions() -> str:
    removed = [k for k in claude_variables() if k in agents.BLOCKED_ENV]
    return (f"Python {platform.python_version()}, {_command('claude', '--version')}; "
            f"removed for agent calls: {removed or 'none'}")


def check_settings() -> str:
    supabase_sync._settings()   # also reads .env, if there is one
    missing = [name for name in NEEDED + TIMEOUTS if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"not set: {missing}")
    return "all present"


def check_fpl() -> str:
    with tempfile.TemporaryDirectory() as folder:
        data = fetch.get("event-status/", 0, raw_dir=Path(folder))
    return f"FPL answered ({len(data.get('status', []))} days in event-status)"


def check_supabase() -> str:
    settings = supabase_sync._settings()
    if settings is None:
        raise RuntimeError("Supabase settings missing")
    url, key = settings
    response = requests.get(f"{url}/rest/v1/automation_status", params={"select": "checked_at"},
                            headers=supabase_sync._headers(key), timeout=30)
    response.raise_for_status()
    return f"Supabase answered: {response.json()}"


def check_alert() -> str:
    if not notify.send("FPL experiment", "Test alert from the cloud check: the cloud can reach your phone."):
        raise RuntimeError("the alert was not sent")
    return "test alert sent"


def check_git_push() -> str:
    # A dry run asks GitHub for permission to push to main without sending anything. (Cloud sessions can push
    # but not delete branches, so a real test push would leave a branch behind.)
    _command("git", "push", "--dry-run", "origin", "HEAD:refs/heads/main")
    name, email = (subprocess.run(["git", "config", key], capture_output=True, text=True).stdout.strip() or "?"
                   for key in ("user.name", "user.email"))
    return f"GitHub accepts pushes to main (git identity here: {name} <{email}>)"


def check_agent_call() -> str:
    schema = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}
    record = agents.ClaudeAgent(TEST_MODEL).call(
        "This is a connection test. Answer in the requested format.", "Reply with the word ok.", schema, None)
    if record.error or record.model_mismatch:
        raise RuntimeError(f"{record.error or 'model mismatch'}; models used {record.models_used}; "
                           f"stderr: {record.raw_stderr[-500:]}")
    return (f"{TEST_MODEL} answered {record.answer} in {record.duration_ms / 1000:.1f} s "
            f"({record.input_tokens} input and {record.output_tokens} output tokens)")


CHECKS = [("Versions and sign-in", check_versions), ("Private settings", check_settings),
          ("FPL download", check_fpl), ("Supabase", check_supabase), ("Phone alert", check_alert),
          ("GitHub push", check_git_push)]


def run(real_call: bool = False) -> bool:
    failed = []
    for name, check in CHECKS + ([("Agent call", check_agent_call)] if real_call else []):
        try:
            print(f"PASS  {name}: {check()}")
        except Exception as error:  # noqa: BLE001 - report every check, whatever goes wrong
            failed.append(name)
            print(f"FAIL  {name}: {error}")
    print("ALL CHECKS PASSED" if not failed else f"FAILED: {', '.join(failed)}")
    print(f"(Claude variables here: {', '.join(claude_variables()) or 'none'})")
    return not failed
