"""Command-line entry point for the experiment.

    python run.py fetch [--force]        download this gameweek's public data (cached, rate-limited)
    python run.py snapshot [--filter F]  build the player table agents receive (no network)
    python run.py sync                   copy local data files to Supabase
    python run.py check-scorer           one-off: compare our scorer with real teams' official scores
    python run.py check-xpoints [--past] test our expected points on this season (or 4 past seasons)
    python run.py decide --gw N [--mock] all teams make their gameweek N decision
    python run.py score --gw N [--mock]  score gameweek N once it is final
    python run.py test-calls --gw N --yes-real-calls   phase 4 check: 2 real calls per model
    python run.py auto [--dry-run] [--log]   the automatic weekly routine (scheduler, every hour)
    python run.py cloud-check --yes-real-call   can a cloud session do everything `auto` needs? (1 real call)

"""

import argparse
import sys

from experiment import api_rules, bots, config, fetch, metrics, runner, scorer_check, snapshot, supabase_sync, test_calls
from experiment.files import read_json_gz
from experiment.gameweeks import deadline, hours_until_deadline


def cmd_fetch(args) -> None:
    print("Fetching public FPL data")
    bootstrap, gw = fetch.get_bootstrap(force=args.force)
    fetch.get("fixtures/", gw, force=args.force)
    fetch.get("event-status/", gw, force=args.force)
    when = deadline(bootstrap["events"], gw)
    hours = hours_until_deadline(bootstrap["events"], gw)
    print(f"Decision gameweek: {gw}, deadline {when:%a %d %b %Y %H:%M} UTC ({hours:.1f} hours away)")
    supabase_sync.sync()


def cmd_snapshot(args) -> None:
    meta, rows, rules_path = snapshot.build_from_saved(args.filter)
    print(f"Snapshot for gameweek {meta['gw']}: {meta['players_in_snapshot']} of {meta['players_in_game']} players "
          f"(filter '{args.filter}'), ~{meta['est_tokens']:,} tokens (estimate)")
    print("\nCandidate filters:")
    for result in snapshot.compare_filters(rows):
        print(f"  {result['filter']:<20} {result['players']:>4} players  "
              f"{result['chars']:>7,} chars  ~{result['est_tokens']:>6,} tokens")
    print(f"\nRules saved to {rules_path.relative_to(config.PROJECT_ROOT).as_posix()}")
    supabase_sync.sync()


def cmd_sync(args) -> None:
    if not supabase_sync.sync():
        sys.exit(1)


def cmd_check_scorer(args) -> None:
    if not scorer_check.run(args.sample, args.teams, args.keep):
        sys.exit(1)


def cmd_check_xpoints(args) -> None:
    # Imported here so the other commands don't load the past-season test.
    from experiment import xpoints_check, xpoints_past
    if args.past:
        xpoints_past.run()
    else:
        xpoints_check.run()


def _teams(names: str | None):
    """AI teams and bots named in --teams (default: all of them)."""
    if not names:
        return runner.TEAMS, bots.BOTS
    wanted = names.split(",")
    unknown = set(wanted) - {t.id for t in runner.TEAMS + bots.BOTS}
    if unknown:
        sys.exit(f"Unknown team(s): {sorted(unknown)}")
    return [t for t in runner.TEAMS if t.id in wanted], [b for b in bots.BOTS if b.id in wanted]


def cmd_decide(args) -> None:
    teams, bot_list = _teams(args.teams)
    runner.decide(args.gw, args.mock, teams, args.yes_real_calls, bot_list)
    if not args.mock:
        supabase_sync.sync()


def cmd_metrics(args) -> None:
    metrics.build_all(runner.base_dir(args.mock))


def cmd_score(args) -> None:
    runner.score_gameweek(args.gw, args.mock)
    if not args.mock:
        supabase_sync.sync()


def cmd_auto(args) -> None:
    # Imported here so the other commands don't load the scheduler's code.
    from experiment import automation
    if args.dry_run:
        automation.describe()
    elif args.log:
        automation.run_logged()
    else:
        automation.run()


def cmd_cloud_check(args) -> None:
    if not args.yes_real_call:
        sys.exit("This makes 1 real `claude -p` call (claude-haiku-5-5). Add --yes-real-call once agreed.")
    from experiment import cloud_check
    if not cloud_check.run():
        sys.exit(1)


def cmd_test_calls(args) -> None:
    if not args.yes_real_calls:
        sys.exit("This makes 6 real `claude -p` calls (2 per model). Add --yes-real-calls once agreed.")
    test_calls.run(args.gw)


def main() -> None:
    parser = argparse.ArgumentParser(description="FPL agents experiment")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("fetch", help="download this gameweek's public FPL data")
    p.add_argument("--force", action="store_true", help="ignore the cache and the per-gameweek limit")
    p.set_defaults(func=cmd_fetch)

    p = commands.add_parser("snapshot", help="build the player table agents receive")
    p.add_argument("--filter", choices=list(snapshot.FILTERS), default=config.SNAPSHOT_FILTER)
    p.set_defaults(func=cmd_snapshot)

    p = commands.add_parser("sync", help="copy local data files to Supabase")
    p.set_defaults(func=cmd_sync)

    p = commands.add_parser("check-scorer", help="one-off: compare our scorer with real teams' official scores")
    p.add_argument("--sample", type=int, default=40, help="random teams to look at")
    p.add_argument("--teams", type=int, default=15, help="teams to check every finished gameweek for")
    p.add_argument("--keep", action="store_true", help="keep the test cache (for debugging)")
    p.set_defaults(func=cmd_check_scorer)

    p = commands.add_parser("check-xpoints", help="test our expected points on gameweeks already played")
    p.add_argument("--past", action="store_true",
                   help="use 4 past seasons instead (downloads a community dataset, ~25 MB, git-ignored)")
    p.set_defaults(func=cmd_check_xpoints)

    p = commands.add_parser("decide", help="all teams make their decision for a gameweek")
    p.add_argument("--gw", type=int, required=True)
    p.add_argument("--mock", action="store_true", help="fake agent, saved in data/mock (no quota used)")
    p.add_argument("--teams", help="comma-separated team ids, e.g. H-none,form-bot (default: all 9 and both bots)")
    p.add_argument("--yes-real-calls", action="store_true", help="confirm real `claude -p` calls (uses your plan)")
    p.set_defaults(func=cmd_decide)

    p = commands.add_parser("score", help="score a gameweek once FPL has finalised it")
    p.add_argument("--gw", type=int, required=True)
    p.add_argument("--mock", action="store_true", help="score the mock run (fake points if not played yet)")
    p.set_defaults(func=cmd_score)

    p = commands.add_parser("metrics", help="rebuild the results and metrics files from saved data")
    p.add_argument("--mock", action="store_true")
    p.set_defaults(func=cmd_metrics)

    p = commands.add_parser("auto", help="the automatic weekly routine (run every hour by the scheduler)")
    p.add_argument("--dry-run", action="store_true", help="only say what is due, from saved files (no downloads or calls)")
    p.add_argument("--log", action="store_true", help="write the output to automation/log.txt (the scheduler uses this)")
    p.set_defaults(func=cmd_auto)

    p = commands.add_parser("cloud-check", help="check a cloud session can reach everything `auto` needs (1 real call)")
    p.add_argument("--yes-real-call", action="store_true")
    p.set_defaults(func=cmd_cloud_check)

    p = commands.add_parser("test-calls", help="phase 4 check: one probe and one decision call per model")
    p.add_argument("--gw", type=int, required=True)
    p.add_argument("--yes-real-calls", action="store_true")
    p.set_defaults(func=cmd_test_calls)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
