"""Tests for Schedule Enhancements (v0.16.0 — Skyvern pattern)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from deskaoy.routines import (
    MIN_CRON_INTERVAL_SECONDS,
    Routine,
    RoutineScheduler,
    calculate_next_runs,
    compute_next_run,
    compute_previous_fire_time,
    validate_cron_expression,
)


class TestValidateCronExpression:
    """Tests for validate_cron_expression()."""

    def test_valid_daily(self):
        """Valid daily cron should not raise."""
        validate_cron_expression("0 0 * * *")

    def test_valid_hourly(self):
        validate_cron_expression("0 * * * *")

    def test_valid_every_15m(self):
        validate_cron_expression("*/15 * * * *")

    def test_valid_every_5m(self):
        validate_cron_expression("*/5 * * * *")

    def test_rejects_every_minute(self):
        """Every-minute cron is too frequent."""
        with pytest.raises(ValueError, match="too short"):
            validate_cron_expression("* * * * *")

    def test_rejects_every_2m(self):
        """Every-2-minute cron is too frequent."""
        with pytest.raises(ValueError, match="too short"):
            validate_cron_expression("*/2 * * * *")

    def test_rejects_invalid_fields(self):
        with pytest.raises(ValueError, match="Invalid cron"):
            validate_cron_expression("not a cron")

    def test_valid_named_schedule(self):
        validate_cron_expression("@daily")

    def test_valid_natural_language(self):
        validate_cron_expression("every 5m")

    def test_rejects_every_1m_natural_language(self):
        """'every 1m' resolves to */1 (every minute) — too frequent."""
        with pytest.raises(ValueError):
            validate_cron_expression("every 1m")


class TestComputeNextRunTimezone:
    """Tests for timezone-aware compute_next_run()."""

    def test_utc_default(self):
        """When no timezone specified, uses local time. When UTC specified, uses UTC."""
        now = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
        # Explicit UTC timezone
        result = compute_next_run("0 8 * * *", from_time=now.timestamp(), timezone_name="UTC")
        next_dt = datetime.fromtimestamp(result, tz=timezone.utc)
        assert next_dt.hour == 8
        assert next_dt.minute == 0

    def test_new_york_timezone(self):
        """America/New_York is UTC-4 (summer) or UTC-5 (winter)."""
        # Winter time: Jan 15, 10am UTC = 5am NYC
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        # Schedule 8am NYC = 13:00 UTC in winter
        result = compute_next_run(
            "0 8 * * *", from_time=now.timestamp(), timezone_name="America/New_York",
        )
        next_dt = datetime.fromtimestamp(result, tz=timezone.utc)
        # 8am NYC winter = 13:00 UTC, which is after 10:00 UTC
        assert next_dt.hour == 13
        assert next_dt.minute == 0

    def test_tokyo_timezone(self):
        """Asia/Tokyo is UTC+9."""
        # Jan 15, 3am UTC = 12pm Tokyo
        now = datetime(2025, 1, 15, 3, 0, tzinfo=timezone.utc)
        # Schedule 9am Tokyo — should be Jan 16 0:00 UTC (9am Tokyo)
        result = compute_next_run(
            "0 9 * * *", from_time=now.timestamp(), timezone_name="Asia/Tokyo",
        )
        next_dt = datetime.fromtimestamp(result, tz=timezone.utc)
        assert next_dt.hour == 0  # 9am Tokyo = 0:00 UTC


class TestComputePreviousFireTime:
    """Tests for compute_previous_fire_time()."""

    def test_returns_past_timestamp(self):
        prev = compute_previous_fire_time("0 8 * * *")
        assert prev < time.time()

    def test_daily_schedule(self):
        """Previous fire for daily 8am should be within last 24h."""
        prev = compute_previous_fire_time("0 8 * * *")
        now = time.time()
        assert prev > now - 86400 * 2  # Within 2 days

    def test_hourly_schedule(self):
        """Previous fire for hourly should be within last hour."""
        prev = compute_previous_fire_time("0 * * * *")
        now = time.time()
        assert prev > now - 7200  # Within 2 hours


class TestCalculateNextRuns:
    """Tests for calculate_next_runs()."""

    def test_returns_count(self):
        runs = calculate_next_runs("0 8 * * *", count=3)
        assert len(runs) == 3

    def test_ascending_order(self):
        runs = calculate_next_runs("0 8 * * *", count=5)
        for i in range(len(runs) - 1):
            assert runs[i] < runs[i + 1]

    def test_daily_interval(self):
        runs = calculate_next_runs("0 8 * * *", count=3)
        # Each run should be ~24h apart
        for i in range(len(runs) - 1):
            gap = runs[i + 1] - runs[i]
            # Allow 23-25h (DST transitions)
            assert 80000 < gap < 90000

    def test_with_timezone(self):
        runs = calculate_next_runs("0 9 * * *", timezone_name="Asia/Tokyo", count=3)
        assert len(runs) == 3
        # All should be in the future
        now = time.time()
        for r in runs:
            assert r > now

    def test_every_5m(self):
        runs = calculate_next_runs("*/5 * * * *", count=5)
        assert len(runs) == 5
        for i in range(len(runs) - 1):
            gap = runs[i + 1] - runs[i]
            assert 290 < gap < 310  # ~5 min
