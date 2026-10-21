"""Command-line entry point for the experiment.

    python run.py fetch [--force]        download this gameweek's public data (cached, rate-limited)
    python run.py snapshot [--filter F]  build the player table agents receive (no network)
    python run.py sync                   copy local data files to Supabase
    python run.py check-scorer           one-off: compare our scorer with real teams' official scores
    python run.py decide --gw N [--mock] all teams make their gameweek N decision
    python run.py score --gw N [--mock]  score gameweek N once it is final
    python run.py test-calls --gw N --yes-real-calls   phase 4 check: 2 real calls per model

"""

import argparse
import sys

from experiment import api_rules, config, fetch, runner, scorer_check, snapshot, supabase_sync, test_calls
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
    latest = fetch.latest_bootstrap()
    if latest is None:
        sys.exit("No saved data yet. Run `python run.py fetch` first.")
    bootstrap_file, gw = latest
    fixture_files = fetch.cached_files(config.RAW_DIR, gw, "fixtures/")
    if not fixture_files:
        sys.exit(f"No saved fixtures for gameweek {gw}. Run `python run.py fetch` first.")

    bootstrap = read_json_gz(bootstrap_file)
    fixtures = read_json_gz(fixture_files[-1])
    rows = snapshot.build_rows(bootstrap, fixtures, gw)

    sources = {"bootstrap": bootstrap_file.relative_to(config.RAW_DIR).as_posix(),
               "fixtures": fixture_files[-1].relative_to(config.RAW_DIR).as_posix()}
    meta = snapshot.save_snapshot(gw, rows, args.filter, sources)
    rules_path = api_rules.save_rules(bootstrap, sources["bootstrap"])

    print(f"Snapshot for gameweek {gw}: {meta['players_in_snapshot']} of {meta['players_in_game']} players "
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


def _teams(names: str | None):
    if not names:
        return runner.TEAMS
    wanted = names.split(",")
    unknown = set(wanted) - {t.id for t in runner.TEAMS}
    if unknown:
        sys.exit(f"Unknown team(s): {sorted(unknown)}")
    return [t for t in runner.TEAMS if t.id in wanted]


def cmd_decide(args) -> None:
    runner.decide(args.gw, args.mock, _teams(args.teams), args.yes_real_calls)


def cmd_score(args) -> None:
    runner.score_gameweek(args.gw, args.mock)


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

    p = commands.add_parser("decide", help="all teams make their decision for a gameweek")
    p.add_argument("--gw", type=int, required=True)
    p.add_argument("--mock", action="store_true", help="fake agent, saved in data/mock (no quota used)")
    p.add_argument("--teams", help="comma-separated team ids, e.g. H-none,S-none (default: all 9)")
    p.add_argument("--yes-real-calls", action="store_true", help="confirm real `claude -p` calls (uses your plan)")
    p.set_defaults(func=cmd_decide)

    p = commands.add_parser("score", help="score a gameweek once FPL has finalised it")
    p.add_argument("--gw", type=int, required=True)
    p.add_argument("--mock", action="store_true", help="score the mock run (fake points if not played yet)")
    p.set_defaults(func=cmd_score)

    p = commands.add_parser("test-calls", help="phase 4 check: one probe and one decision call per model")
    p.add_argument("--gw", type=int, required=True)
    p.add_argument("--yes-real-calls", action="store_true")
    p.set_defaults(func=cmd_test_calls)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
