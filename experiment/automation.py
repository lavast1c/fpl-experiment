"""The automatic weekly routine: `python run.py auto` (decided 2026-10-27, METHODS.md).

A scheduled cloud task starts it every 3 hours (scripts/cloud_routine.md); the Windows schedule
(scripts/schedule_windows.ps1) is the fallback. Never run both at once.
Each run first looks only at saved files, and contacts FPL, Claude or GitHub only when a step is due:

1. Missed deadlines. A gameweek whose deadline has passed without every team's decision is
   recorded as missed (runner.record_missed): those teams keep last week's team.
2. Scoring. From 18 hours after a gameweek's last kick-off, ask FPL at most every 12 hours whether
   the points are final, and score the gameweek once they are.
3. Picks. From 24 hours before the next deadline: download the data, build the snapshot and run
   every team's decision. If last gameweek isn't scored yet, wait for it until 6 hours before the
   deadline, then pick anyway. A team whose call fails (no internet, Claude usage limit) is tried
   again by the next run, until the deadline. The snapshot is built only once, so every team gets
   the same table even when some are picked in a later run.
4. Then: save the new data to GitHub, copy it to Supabase, update the status panel on the website,
   and send a phone alert for finished jobs and problems (notify.py).

The `claude -p` calls in step 3 run without asking each week: the project owner gave standing
approval for the weekly picks on 2026-10-27 (CLAUDE.md). Nothing else here makes Claude calls.
FPL downloads stay inside fetch.py's limits: a score check costs one download of bootstrap-static
and event-status, and one of each is kept back for the picks.
"""

import contextlib
import subprocess
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import bots, config, fetch, notify, runner, snapshot, supabase_sync
from .files import read_json, read_json_gz, write_json
from .gameweeks import deadline, parse_time, upcoming_gw

HOUR = timedelta(hours=1)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOCK_STALE_HOURS = 6          # a lock this old was left by a crash or a shutdown
LOG_MAX_BYTES = 5_000_000     # then the log starts again (the previous one is kept as log.old.txt)


# --- timing (pure functions, tested in tests/test_automation.py) --------------------------------

def last_kickoff(fixtures: list[dict], gw: int) -> datetime | None:
    times = [parse_time(f["kickoff_time"]) for f in fixtures if f.get("event") == gw and f.get("kickoff_time")]
    return max(times) if times else None


def next_score_check(kickoff: datetime, last_download: datetime | None) -> datetime:
    """The first check comes 18 hours after the last kick-off; later ones 12 hours after the last download."""
    first = kickoff + config.AUTO_SCORE_AFTER_HOURS * HOUR
    if last_download is not None and last_download >= first:
        return last_download + config.AUTO_SCORE_EVERY_HOURS * HOUR
    return first


def pick_time(the_deadline: datetime, last_week_scored: bool) -> datetime:
    """When the picks for a deadline start: 24 hours before, or 6 if last gameweek isn't scored yet."""
    hours = config.AUTO_PICK_HOURS_BEFORE if last_week_scored else config.AUTO_PICK_LATEST_HOURS_BEFORE
    return the_deadline - hours * HOUR


# --- what has been done so far (saved files only) -----------------------------------------------

def scored(gw: int) -> bool:
    return (config.DATA_DIR / "scores" / f"gw{gw}.json").exists()


def has_decisions(gw: int) -> bool:
    folder = config.DATA_DIR / "decisions" / f"gw{gw}"
    return folder.exists() and any(folder.glob("*.json"))


def last_week_scored(gw: int) -> bool:
    """True if gameweek gw-1 is scored, or there is nothing to score (before the experiment began)."""
    return gw - 1 < config.FIRST_GW or not has_decisions(gw - 1) or scored(gw - 1)


def passed_gameweeks(events: list[dict], now: datetime) -> list[int]:
    return [e["id"] for e in events if e["id"] >= config.FIRST_GW and parse_time(e["deadline_time"]) <= now]


def unscored(events: list[dict], now: datetime) -> list[int]:
    return [gw for gw in passed_gameweeks(events, now) if has_decisions(gw) and not scored(gw)]


def saved_fpl_data() -> tuple[list[dict], list[dict], datetime]:
    """The newest saved gameweek list and fixtures, and when bootstrap-static was last downloaded."""
    latest = fetch.latest_bootstrap()
    if latest is None:
        raise SystemExit("No saved FPL data yet. Run `python run.py fetch` once first.")
    fixture_files = sorted(config.RAW_DIR.glob("gw*/fixtures_*.json.gz"), key=fetch.saved_at)
    fixtures = read_json_gz(fixture_files[-1]) if fixture_files else []
    return read_json_gz(latest[0])["events"], fixtures, fetch.saved_at(latest[0])


def downloads_left(gw_folder: int) -> int:
    """How many more bootstrap-static and event-status downloads fetch.py allows in a folder."""
    used = max(len(fetch.cached_files(config.RAW_DIR, gw_folder, e)) for e in ("bootstrap-static/", "event-status/"))
    return config.MAX_FETCHES_PER_GAMEWEEK - used


# --- one automatic run --------------------------------------------------------------------------

@dataclass
class Report:
    """What one run did: for the log, the phone alert, the website's status panel and the commit message."""
    done: list[str] = field(default_factory=list)        # finished jobs
    problems: list[str] = field(default_factory=list)    # something went wrong (or a deadline was missed)
    waiting: list[str] = field(default_factory=list)     # normal waits, e.g. FPL is still checking points


def record_missed_weeks(now: datetime, events: list[dict], report: Report) -> None:
    for gw in passed_gameweeks(events, now):
        if runner.undecided(gw):
            missed = runner.record_missed(gw)
            report.problems.append(f"Gameweek {gw}: {len(missed)} team(s) missed the deadline and kept "
                                   f"last week's team ({', '.join(missed)}).")


def score_if_final(now: datetime, report: Report, check_now: bool = False) -> None:
    """Score every finished gameweek that FPL has confirmed, oldest first. check_now skips the
    12-hour wait between checks (used right after the picks' own download, which costs nothing)."""
    events, fixtures, last_download = saved_fpl_data()
    for gw in unscored(events, now):
        kickoff = last_kickoff(fixtures, gw)
        if kickoff is None or now < kickoff + config.AUTO_SCORE_AFTER_HOURS * HOUR:
            return   # the matches aren't over yet
        if not check_now:
            if now < next_score_check(kickoff, last_download):
                return
            folder = upcoming_gw(events, now)
            keep_back = 1 if folder is not None and not runner.has_snapshot(folder) else 0
            if folder is not None and downloads_left(folder) <= keep_back:
                report.waiting.append(f"Gameweek {gw}: this week's FPL downloads are used up, so scoring "
                                      f"waits until after the next deadline.")
                return
        final, _ = runner.gameweek_is_final(gw)
        check_now = True   # the data just checked is fresh, so later gameweeks need no new download
        if not final:
            report.waiting.append(f"Gameweek {gw}: FPL hasn't confirmed the points yet.")
            return
        rows = runner.score_gameweek(gw, mock=False)
        best = max(rows, key=lambda r: r["net_points"])
        report.done.append(f"Gameweek {gw} scored (top: {best['team']} with {best['net_points']} points).")


def download_for_picks() -> int:
    """The same three downloads as `python run.py fetch`. Returns the gameweek folder they went into.
    If a download limit is reached, the saved copy is used instead."""
    _, gw = fetch.get_bootstrap()
    for endpoint in ("fixtures/", "event-status/"):
        try:
            fetch.get(endpoint, gw)
        except fetch.FetchCapReached as error:
            print(f"  {error} Using the saved copy.")
    return gw


def pick_if_due(now: datetime, report: Report) -> None:
    events, _, _ = saved_fpl_data()
    gw = upcoming_gw(events, now)
    if gw is None or not runner.undecided(gw):
        return
    if now < pick_time(deadline(events, gw), last_week_scored(gw)):
        if now >= pick_time(deadline(events, gw), True):
            report.waiting.append(f"Gameweek {gw}: the picks wait for gameweek {gw - 1}'s points until "
                                  f"{pick_time(deadline(events, gw), False):%a %d %b %H:%M} UTC.")
        return

    if not runner.has_snapshot(gw):
        download_for_picks()
        events, _, _ = saved_fpl_data()
        if upcoming_gw(events, now) != gw:
            report.problems.append(f"Gameweek {gw}: FPL's gameweek list changed; the picks will be retried.")
            return
        if not last_week_scored(gw):
            score_if_final(now, report, check_now=True)   # the download above is fresh: no extra cost
            if not last_week_scored(gw) and now < pick_time(deadline(events, gw), False):
                return   # the deadline moved later: keep waiting for the points
        if fetch.latest_bootstrap()[1] != gw:
            report.problems.append(f"Gameweek {gw}: no FPL data for this gameweek could be downloaded.")
            return
        meta, _, _ = snapshot.build_from_saved()
        print(f"Snapshot for gameweek {gw}: {meta['players_in_snapshot']} players")

    runner.decide(gw, mock=False, real_calls_confirmed=True)
    left = runner.undecided(gw)
    if left:
        report.problems.append(f"Gameweek {gw}: {', '.join(left)} not picked yet (Claude could not be "
                               f"reached); trying again at the next check, until the deadline.")
    else:
        report.done.append(f"Gameweek {gw} picks done for all {len(runner.TEAMS) + len(bots.BOTS)} teams.")


def attempt(report: Report, name: str, action, *args) -> None:
    """Run one step; any error becomes a reported problem instead of stopping the other steps."""
    try:
        action(*args)
    except (Exception, SystemExit) as error:  # noqa: BLE001 - one failed step must not stop the rest
        traceback.print_exc()
        report.problems.append(f"{name} failed: {error}")


def run(now: datetime | None = None) -> Report | None:
    """One automatic run (steps 1-4 of the module docstring). Returns None if another run is busy."""
    now = now or datetime.now(timezone.utc)
    with lock(now) as free:
        if not free:
            print("Another automatic run is still busy, so this one stops.")
            return None
        report = Report()
        attempt(report, "Recording missed deadlines", lambda: record_missed_weeks(now, saved_fpl_data()[0], report))
        attempt(report, "Scoring", score_if_final, now, report)
        attempt(report, "The picks", pick_if_due, now, report)
        attempt(report, "Saving the data", save_and_copy, report)
        attempt(report, "Updating the status", update_status, now, report)
        for line in report.done + report.problems + report.waiting:
            print(f"  {line}")
        if report.done or report.problems:
            title = "FPL experiment: problem" if report.problems else "FPL experiment"
            notify.send(title, " ".join(report.problems + report.done), problem=bool(report.problems))
        return report


def run_logged() -> None:
    """run(), with everything it prints added to automation/log.txt (the scheduler shows no window)."""
    config.AUTO_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.AUTO_DIR / "log.txt"
    if log_path.exists() and log_path.stat().st_size > LOG_MAX_BYTES:
        log_path.replace(config.AUTO_DIR / "log.old.txt")
    with open(log_path, "a", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        print(f"\n=== {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC ===")
        try:
            run()
        except Exception:  # noqa: BLE001 - make sure even an unexpected error reaches the log and the owner
            traceback.print_exc()
            notify.send("FPL experiment: problem", "The automatic run crashed. See automation/log.txt.", problem=True)


@contextlib.contextmanager
def lock(now: datetime):
    """Only one automatic run at a time: the picks can take an hour, and the scheduler may start another."""
    path = config.AUTO_DIR / "lock.json"
    if path.exists() and now - parse_time(read_json(path)["started_at"]) < LOCK_STALE_HOURS * HOUR:
        yield False
        return
    write_json(path, {"started_at": now.isoformat(timespec="seconds")})
    try:
        yield True
    finally:
        path.unlink(missing_ok=True)


# --- saving, status and planning ----------------------------------------------------------------

def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=config.PROJECT_ROOT, capture_output=True, text=True,
                          encoding="utf-8", creationflags=NO_WINDOW)


def save_and_copy(report: Report) -> None:
    """Commit the changed files in data/ and push them to GitHub, then copy them to Supabase."""
    if not git("status", "--porcelain", "--", "data").stdout.strip():
        return
    supabase_sync.sync()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "main":
        report.problems.append(f"The data was saved on this computer but not pushed: git is on '{branch}', not main.")
        return
    lines = report.done + report.problems
    message = f"{lines[0] if lines else 'Download FPL data'} (automatic run)" + "".join(f"\n\n{l}" for l in lines[1:])
    git("add", "--", "data")
    committed = git("commit", "-m", message, "--", "data")
    if committed.returncode != 0:
        raise RuntimeError(f"git commit: {committed.stderr.strip() or committed.stdout.strip()}")
    if git("push", "origin", "main").returncode != 0:
        git("pull", "--rebase", "--autostash", "origin", "main")
        pushed = git("push", "origin", "main")
        if pushed.returncode != 0:
            report.problems.append(f"The data was saved on this computer but not pushed to GitHub "
                                   f"({pushed.stderr.strip()[:200]}).")


def upcoming_steps(now: datetime) -> list[dict]:
    """The next scoring and picks, with the time each can start (for the website and --dry-run)."""
    events, fixtures, last_download = saved_fpl_data()
    steps = []
    waiting = unscored(events, now)
    if waiting:
        gw, kickoff = waiting[0], last_kickoff(fixtures, waiting[0])
        start = next_score_check(kickoff, last_download) if kickoff else now
        steps.append({"step": f"Score gameweek {gw}", "from": max(start, now).isoformat(timespec="minutes"),
                      "note": "as soon as FPL has confirmed the points"})
    gw = upcoming_gw(events, now)
    if gw is not None and runner.undecided(gw):
        the_deadline, ready = deadline(events, gw), last_week_scored(gw)
        steps.append({"step": f"Pick gameweek {gw} teams",
                      "from": max(pick_time(the_deadline, ready), now).isoformat(timespec="minutes"),
                      "note": f"deadline {the_deadline:%a %d %b %H:%M} UTC"
                              + ("" if ready else f"; waits for gameweek {gw - 1}'s points")})
    return steps


def update_status(now: datetime, report: Report) -> None:
    """Save the status (automation/status.json) and copy it to Supabase for the website's panel."""
    path = config.AUTO_DIR / "status.json"
    status = read_json(path) if path.exists() else {"id": 1, "last_result": None, "last_result_at": None,
                                                    "last_result_ok": None}
    if report.done or report.problems:
        status.update(last_result=" ".join(report.problems + report.done),
                      last_result_at=now.isoformat(timespec="minutes"), last_result_ok=not report.problems)
    status.update(checked_at=now.isoformat(timespec="minutes"),
                  next_check_by=(now + config.AUTO_EVERY_HOURS * HOUR).isoformat(timespec="minutes"),
                  every_hours=config.AUTO_EVERY_HOURS, upcoming=upcoming_steps(now),
                  waiting=report.waiting, problems=report.problems)
    write_json(path, status)
    supabase_sync.push_status(status)


def describe(now: datetime | None = None) -> None:
    """`python run.py auto --dry-run`: what would happen, from saved files only (no downloads or calls)."""
    now = now or datetime.now(timezone.utc)
    events, _, last_download = saved_fpl_data()
    print(f"Now: {now:%a %d %b %H:%M} UTC. Newest FPL data downloaded {last_download:%a %d %b %H:%M} UTC.")
    missed = [gw for gw in passed_gameweeks(events, now) if runner.undecided(gw)]
    if missed:
        print(f"  Would record missed deadlines for gameweek(s) {missed}.")
    for step in upcoming_steps(now):
        due = "now" if parse_time(step["from"]) <= now else f"from {parse_time(step['from']):%a %d %b %H:%M} UTC"
        print(f"  {step['step']}: {due} ({step['note']})")
