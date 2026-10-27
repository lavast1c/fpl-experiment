"""Read the public FPL API, politely.

Every request in the project goes through this file, which enforces the brief's rules:
- only endpoints listed in config.ALLOWED_ENDPOINTS
- reuse a cached copy when it is recent enough
- at most config.MAX_FETCHES_PER_GAMEWEEK downloads of one endpoint per gameweek (unless forced)
- wait config.REQUEST_DELAY_SECONDS between requests
- plain requests.get with no session, cookies or login of any kind
Each response is saved gzipped as data/raw/gw{N}/{endpoint}_{UTC time}.json.gz
and logged in data/raw/fetch_log.csv.
"""

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config
from .files import append_csv, read_json_gz, write_json_gz
from .gameweeks import decision_gw, upcoming_gw

FETCH_LOG_FIELDS = ["fetched_at", "gw", "endpoint", "file", "sha256", "bytes", "forced"]
TIME_FORMAT = "%Y%m%dT%H%M%SZ"

# When the last request was sent (time.monotonic()), shared by every call in this run.
_last_request_at: float | None = None


class FetchCapReached(Exception):
    """Raised when an endpoint has already been downloaded the maximum number of times this gameweek."""


def endpoint_slug(endpoint: str) -> str:
    """'bootstrap-static/' -> 'bootstrap-static', 'event/8/live/' -> 'event-8-live'."""
    return re.sub(r"[/?=_]+", "-", endpoint.strip("/"))


def cached_files(raw_dir: Path, gw: int, endpoint: str) -> list[Path]:
    """All saved copies of an endpoint for one gameweek, oldest first (names sort by time)."""
    folder = raw_dir / f"gw{gw}"
    return sorted(folder.glob(f"{endpoint_slug(endpoint)}_*.json.gz"))


def saved_at(path: Path) -> datetime:
    """Read the UTC download time back out of a cache file name."""
    stamp = path.name.split("_")[-1].removesuffix(".json.gz")
    return datetime.strptime(stamp, TIME_FORMAT).replace(tzinfo=timezone.utc)


def matches(endpoint: str, patterns) -> bool:
    return any(re.fullmatch(pattern, endpoint) for pattern in patterns)


def is_fresh(path: Path, endpoint: str, now: datetime) -> bool:
    max_age_hours = next((hours for pattern, hours in config.CACHE_MAX_AGE_HOURS.items()
                          if re.fullmatch(pattern, endpoint)), 1)
    return (now - saved_at(path)).total_seconds() < max_age_hours * 3600


def _download(endpoint: str, http_get, sleep, test_only: bool = False) -> dict | list:
    """One GET request, spaced at least REQUEST_DELAY_SECONDS after the previous one.

    test_only=True also allows TEST_ONLY_ENDPOINTS (only the scorer check passes it).
    """
    global _last_request_at
    allowed = matches(endpoint, config.ALLOWED_ENDPOINTS) or (test_only and matches(endpoint, config.TEST_ONLY_ENDPOINTS))
    if not allowed:
        raise ValueError(f"Endpoint {endpoint!r} is not on the allowed list in config.py.")
    if _last_request_at is not None:
        wait = config.REQUEST_DELAY_SECONDS - (time.monotonic() - _last_request_at)
        if wait > 0:
            sleep(wait)
    print(f"  GET {config.API_BASE}{endpoint}")
    # Deliberately only these two headers: no cookies, no Authorization.
    response = http_get(
        config.API_BASE + endpoint,
        headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    _last_request_at = time.monotonic()
    response.raise_for_status()
    return response.json()


def _save(raw_dir: Path, gw: int, endpoint: str, data, now: datetime, forced: bool) -> Path:
    path = raw_dir / f"gw{gw}" / f"{endpoint_slug(endpoint)}_{now.strftime(TIME_FORMAT)}.json.gz"
    raw = write_json_gz(path, data)
    append_csv(
        raw_dir / "fetch_log.csv",
        {
            "fetched_at": now.isoformat(timespec="seconds"),
            "gw": gw,
            "endpoint": endpoint,
            "file": path.relative_to(raw_dir).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "forced": forced,
        },
        FETCH_LOG_FIELDS,
    )
    return path


def _check_cap(raw_dir: Path, gw: int, endpoint: str, force: bool) -> None:
    count = len(cached_files(raw_dir, gw, endpoint))
    if count >= config.MAX_FETCHES_PER_GAMEWEEK:
        if not force:
            raise FetchCapReached(
                f"{endpoint} already downloaded {count} times for gameweek {gw} "
                f"(limit {config.MAX_FETCHES_PER_GAMEWEEK}). Use the cached copy, or --force if really needed."
            )
        print(f"  WARNING: going over the fetch limit for {endpoint} in gameweek {gw} (--force).")


def get(endpoint: str, gw: int, *, force: bool = False, raw_dir: Path = config.RAW_DIR,
        http_get=requests.get, sleep=time.sleep, now: datetime | None = None):
    """Return an endpoint's data for a gameweek, from cache if fresh, otherwise downloaded.

    force=True skips the cache and allows going over the fetch limit (with a warning).
    """
    now = now or datetime.now(timezone.utc)
    files = cached_files(raw_dir, gw, endpoint)
    if files and not force and is_fresh(files[-1], endpoint, now):
        print(f"  cached {endpoint} ({files[-1].name})")
        return read_json_gz(files[-1])
    _check_cap(raw_dir, gw, endpoint, force)
    data = _download(endpoint, http_get, sleep)
    _save(raw_dir, gw, endpoint, data, now, force)
    return data


def latest_bootstrap(raw_dir: Path = config.RAW_DIR) -> tuple[Path, int] | None:
    """The newest saved bootstrap-static file in any gameweek folder, with its gameweek."""
    newest = None
    for folder in raw_dir.glob("gw*"):
        files = cached_files(raw_dir, int(folder.name[2:]), "bootstrap-static/")
        if files and (newest is None or saved_at(files[-1]) > saved_at(newest[0])):
            newest = (files[-1], int(folder.name[2:]))
    return newest


def get_bootstrap(*, force: bool = False, raw_dir: Path = config.RAW_DIR,
                  http_get=requests.get, sleep=time.sleep, now: datetime | None = None):
    """Return (bootstrap data, decision gameweek).

    bootstrap-static is special: we only learn which gameweek folder it belongs in after
    downloading it, because the gameweek list is inside it.
    """
    endpoint = "bootstrap-static/"
    now = now or datetime.now(timezone.utc)
    latest = latest_bootstrap(raw_dir)
    if latest and not force and is_fresh(latest[0], endpoint, now):
        print(f"  cached {endpoint} ({latest[0].name})")
        data = read_json_gz(latest[0])
        return data, decision_gw(data["events"])
    if latest:
        # Count downloads in the folder the new copy will go into: after a deadline that is the next
        # gameweek's folder, not the folder of the newest copy.
        folder = upcoming_gw(read_json_gz(latest[0])["events"], now) or latest[1]
        _check_cap(raw_dir, folder, endpoint, force)
    data = _download(endpoint, http_get, sleep)
    gw = decision_gw(data["events"])
    _save(raw_dir, gw, endpoint, data, now, force)
    return data, gw
