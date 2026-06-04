"""Pure-logic tests for the cron/timezone helper (no DB, no worker)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scheduling.cron import CronError, next_run, preview, validate


def test_validate_accepts_standard_cron() -> None:
    validate("0 2 * * *", "America/New_York")  # no raise


def test_validate_rejects_bad_cron() -> None:
    with pytest.raises(CronError):
        validate("not a cron", "UTC")


def test_validate_rejects_unknown_timezone() -> None:
    with pytest.raises(CronError):
        validate("0 2 * * *", "Mars/Olympus_Mons")


def test_next_run_is_tz_aware_in_winter() -> None:
    # 2am America/New_York in January is EST (UTC-5) → 07:00 UTC.
    after = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    nxt = next_run("0 2 * * *", "America/New_York", after=after)
    assert nxt == datetime(2026, 1, 15, 7, 0, tzinfo=UTC)


def test_next_run_handles_dst_in_summer() -> None:
    # 2am America/New_York in July is EDT (UTC-4) → 06:00 UTC.
    after = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    nxt = next_run("0 2 * * *", "America/New_York", after=after)
    assert nxt == datetime(2026, 7, 15, 6, 0, tzinfo=UTC)


def test_next_run_treats_naive_after_as_utc() -> None:
    naive = datetime(2026, 1, 15, 0, 0)
    aware = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    assert next_run("0 * * * *", "UTC", after=naive) == next_run("0 * * * *", "UTC", after=aware)


def test_preview_returns_n_ascending_utc_times() -> None:
    after = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    runs = preview("0 * * * *", "UTC", n=3, after=after)
    assert len(runs) == 3
    assert all(r.tzinfo is not None for r in runs)
    assert runs == sorted(runs)
    assert runs[0] == datetime(2026, 1, 15, 1, 0, tzinfo=UTC)
