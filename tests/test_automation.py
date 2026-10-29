"""The automatic routine's timing rules (automation.py), on made-up data and temporary folders."""

from datetime import datetime, timedelta, timezone

import pytest

from experiment import automation, config
from experiment.files import write_json

HOUR = timedelta(hours=1)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def temporary_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "AUTO_DIR", tmp_path / "automation")


def test_last_kickoff_ignores_other_and_postponed_matches(fixtures):
    assert automation.last_kickoff(fixtures, 9) == utc("2026-10-24T14:00")
    assert automation.last_kickoff(fixtures, 11) == utc("2026-11-07T14:00")   # the later of a double
    assert automation.last_kickoff(fixtures, 12) is None


def test_score_checks_start_18_hours_after_the_last_kickoff_then_every_12():
    kickoff = utc("2026-10-25T16:30")
    first = kickoff + 18 * HOUR
    assert automation.next_score_check(kickoff, None) == first
    assert automation.next_score_check(kickoff, kickoff - 24 * HOUR) == first   # a download before the matches
    assert automation.next_score_check(kickoff, first + 2 * HOUR) == first + 14 * HOUR


def test_picks_start_24_hours_before_or_6_if_last_week_is_not_scored():
    the_deadline = utc("2026-10-31T11:00")
    assert automation.pick_time(the_deadline, True) == utc("2026-10-30T11:00")
    assert automation.pick_time(the_deadline, False) == utc("2026-10-31T05:00")


def test_which_gameweeks_have_passed_and_still_need_scoring(bootstrap):
    events, now = bootstrap["events"], utc("2026-10-25T12:00")   # after gameweek 9's deadline
    assert automation.passed_gameweeks(events, now) == [8, 9]
    write_json(config.DATA_DIR / "decisions" / "gw8" / "H-none.json", {})
    write_json(config.DATA_DIR / "decisions" / "gw9" / "H-none.json", {})
    assert automation.unscored(events, now) == [8, 9]
    assert not automation.last_week_scored(9)
    write_json(config.DATA_DIR / "scores" / "gw8.json", {})
    assert automation.unscored(events, now) == [9]
    assert automation.last_week_scored(9)
    assert automation.last_week_scored(config.FIRST_GW)   # nothing before the experiment's first gameweek


def test_only_one_run_at_a_time_unless_the_lock_is_stale():
    now = utc("2026-10-27T12:00")
    with automation.lock(now) as first:
        assert first
        with automation.lock(now + HOUR) as second:
            assert not second
    assert not (config.AUTO_DIR / "lock.json").exists()   # released afterwards
    write_json(config.AUTO_DIR / "lock.json", {"started_at": (now - 7 * HOUR).isoformat()})
    with automation.lock(now) as after_crash:
        assert after_crash


def test_a_quiet_run_keeps_the_last_result_on_the_website(monkeypatch):
    # A cloud run starts without automation/status.json, so a quiet run must not send an empty last result.
    sent = []
    monkeypatch.setattr(automation, "upcoming_steps", lambda now: [])
    monkeypatch.setattr(automation.supabase_sync, "push_status", sent.append)
    automation.update_status(utc("2026-10-28T06:07"), automation.Report())
    assert "last_result" not in sent[-1] and sent[-1]["checked_at"] == "2026-10-28T06:07+00:00"
    automation.update_status(utc("2026-10-28T09:07"), automation.Report(done=["Gameweek 9 picks done."]))
    assert sent[-1]["last_result"] == "Gameweek 9 picks done." and sent[-1]["last_result_ok"] is True


# --- saving to GitHub (a real git repository in a temporary folder, with a second copy pushing too) ---

def run_git(folder, *args):
    import subprocess
    return subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def copies(tmp_path, monkeypatch):
    """'here' is the automatic run's copy; 'other' is another computer (or the cloud) pushing to the same GitHub."""
    remote, here, other = tmp_path / "github.git", tmp_path / "here", tmp_path / "other"
    run_git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    for folder in (here, other):
        run_git(tmp_path, "clone", "-q", str(remote), str(folder))
        run_git(folder, "config", "user.name", "Test")
        run_git(folder, "config", "user.email", "test@example.com")
        run_git(folder, "checkout", "-q", "-b", "main")
    (here / "data").mkdir()
    (here / "data" / "log.csv").write_text("a\n")
    run_git(here, "add", "data")
    run_git(here, "commit", "-q", "-m", "start")
    run_git(here, "push", "-q", "origin", "main")
    run_git(other, "pull", "-q", "origin", "main")
    monkeypatch.setattr(config, "PROJECT_ROOT", here)
    return here, other, remote


def commit_line(folder, text, push):
    with open(folder / "data" / "log.csv", "a") as f:
        f.write(text + "\n")
    run_git(folder, "commit", "-q", "-am", text)
    if push:
        run_git(folder, "push", "-q", "origin", "main")


def test_a_run_starts_from_githubs_newest_data(copies):
    here, other, _ = copies
    commit_line(other, "from the cloud", push=True)
    report = automation.Report()
    assert automation.catch_up_with_github(report) and report.problems == []
    assert "from the cloud" in (here / "data" / "log.csv").read_text()


def test_a_clash_with_github_is_undone_not_left_half_way(copies):
    here, other, remote = copies
    commit_line(other, "pushed elsewhere", push=True)
    commit_line(here, "made here", push=False)
    report = automation.Report()
    automation.push_to_github(report)
    assert "clashes" in report.problems[0]
    assert automation.branch() == "main"                      # not stuck mid-rebase
    assert "<<<<<<<" not in (here / "data" / "log.csv").read_text()
    assert "made here" in run_git(here, "log", "-1", "--format=%s")   # the commit is kept for sorting out


def test_a_commit_an_earlier_run_could_not_push_is_pushed_next_time(copies, monkeypatch):
    here, _, remote = copies
    commit_line(here, "push failed last time", push=False)
    monkeypatch.setattr(automation.supabase_sync, "sync", lambda: None)
    report = automation.Report()
    automation.save_and_copy(report)                          # nothing new in data/, but one commit to push
    assert report.problems == []
    assert "push failed last time" in run_git(remote, "log", "-1", "--format=%s", "main")


def test_progress_is_committed_and_pushed(copies):
    here, _, remote = copies
    (here / "data" / "decision.json").write_text("{}")
    automation.commit_and_push("Gameweek 9: picks so far (automatic run, still going)", automation.Report())
    assert run_git(remote, "log", "-1", "--format=%s", "main").strip() == "Gameweek 9: picks so far (automatic run, still going)"
