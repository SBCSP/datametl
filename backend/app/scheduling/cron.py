"""Cron expression + timezone helpers for scheduled SQL scripts.

A schedule stores a 5-field cron string and an IANA timezone (e.g. "America/New_York").
`next_run` interprets the cron in that timezone (so "0 2 * * *" means 2am local, DST-aware)
and returns a UTC-aware datetime suitable for storing in `next_run_at` and comparing against
`func.now()`. Kept dependency-light (croniter + stdlib zoneinfo) and free of DB imports so it's
trivially unit-testable.
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


class CronError(ValueError):
    """Raised for an invalid cron expression or unknown timezone."""


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise CronError(f"Unknown timezone: {tz}") from e


def validate(cron: str, tz: str) -> None:
    """Raise CronError if the cron expression or timezone is invalid."""
    _zone(tz)
    if not croniter.is_valid(cron):
        raise CronError(f"Invalid cron expression: {cron}")


def next_run(cron: str, tz: str, after: datetime | None = None) -> datetime:
    """Next fire time strictly after `after` (default: now), as a UTC-aware datetime.

    The cron fields are evaluated in `tz` so wall-clock schedules track local time and DST.
    `after` may be naive (assumed UTC) or aware; it's converted into `tz` for croniter.
    """
    validate(cron, tz)
    zone = _zone(tz)
    base = after if after is not None else datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    local_base = base.astimezone(zone)
    nxt: datetime = croniter(cron, local_base).get_next(datetime)
    return nxt.astimezone(UTC)


def preview(cron: str, tz: str, n: int = 3, after: datetime | None = None) -> list[datetime]:
    """The next `n` fire times as UTC-aware datetimes (for the form's live preview)."""
    validate(cron, tz)
    zone = _zone(tz)
    base = after if after is not None else datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    itr = croniter(cron, base.astimezone(zone))
    out: list[datetime] = []
    for _ in range(max(0, n)):
        out.append(itr.get_next(datetime).astimezone(UTC))
    return out
