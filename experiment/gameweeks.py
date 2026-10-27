"""Work out the current and next gameweek, and deadlines, from the API's `events` list."""

from datetime import datetime, timezone


def parse_time(text: str) -> datetime:
    """FPL times look like '2026-10-24T10:00:00Z' (UTC)."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def current_gw(events: list[dict]) -> int | None:
    """The gameweek being played now (or most recently), or None before the season starts."""
    for event in events:
        if event.get("is_current"):
            return event["id"]
    return None


def next_gw(events: list[dict]) -> int | None:
    """The gameweek whose deadline is coming up, or None after the last deadline of the season."""
    for event in events:
        if event.get("is_next"):
            return event["id"]
    return None


def decision_gw(events: list[dict]) -> int:
    """The gameweek teams are picking for. Raw data and snapshots are filed under this number."""
    gw = next_gw(events) or current_gw(events)
    if gw is None:
        raise ValueError("No current or next gameweek found in events.")
    return gw


def upcoming_gw(events: list[dict], now: datetime) -> int | None:
    """The first gameweek whose deadline is after `now`, worked out from deadlines alone, so it is
    right even when the saved data (and its is_next flag) is from before the last deadline."""
    for event in events:
        if parse_time(event["deadline_time"]) > now:
            return event["id"]
    return None


def get_event(events: list[dict], gw: int) -> dict:
    for event in events:
        if event["id"] == gw:
            return event
    raise ValueError(f"Gameweek {gw} not found in events.")


def deadline(events: list[dict], gw: int) -> datetime:
    return parse_time(get_event(events, gw)["deadline_time"])


def hours_until_deadline(events: list[dict], gw: int, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return (deadline(events, gw) - now).total_seconds() / 3600
