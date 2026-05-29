"""Tests for Scheduled Routines."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from deskaoy.routines import (
    Routine,
    RoutineExecution,
    RoutineScheduler,
    compute_next_run,
    _parse_field,
    _resolve_schedule,
)


# ═══════════════════════════════════════════════════════════════════════════
# Unit: cron parsing
# ═══════════════════════════════════════════════════════════════════════════

class TestParseField:
    def test_star(self):
        assert _parse_field("*", 0, 5) == {0, 1, 2, 3, 4, 5}

    def test_single_value(self):
        assert _parse_field("3", 0, 10) == {3}

    def test_range(self):
        assert _parse_field("1-3", 0, 10) == {1, 2, 3}

    def test_step(self):
        assert _parse_field("*/15", 0, 59) == {0, 15, 30, 45}

    def test_comma(self):
        assert _parse_field("1,3,5", 0, 10) == {1, 3, 5}

    def test_range_with_step(self):
        assert _parse_field("0-30/10", 0, 59) == {0, 10, 20, 30}


class TestResolveSchedule:
    def test_daily(self):
        assert _resolve_schedule("@daily") == "0 0 * * *"

    def test_hourly(self):
        assert _resolve_schedule("@hourly") == "0 * * * *"

    def test_monthly(self):
        assert _resolve_schedule("@monthly") == "0 0 1 * *"

    def test_weekly(self):
        assert _resolve_schedule("@weekly") == "0 0 * * 0"

    def test_yearly(self):
        assert _resolve_schedule("@yearly") == "0 0 1 1 *"

    def test_every_5m(self):
        assert _resolve_schedule("every 5m") == "*/5 * * * *"

    def test_every_1h(self):
        assert _resolve_schedule("every 1h") == "0 */1 * * *"

    def test_passthrough(self):
        assert _resolve_schedule("0 8 * * *") == "0 8 * * *"


class TestComputeNextRun:
    def test_daily_8am_comes_tomorrow(self):
        """If we're past 8am today, next run is tomorrow 8am."""
        now = datetime(2025, 1, 15, 10, 0)  # 10am
        result = compute_next_run("0 8 * * *", from_time=now.timestamp())
        next_dt = datetime.fromtimestamp(result)
        assert next_dt.hour == 8
        assert next_dt.minute == 0
        assert next_dt.day == 16  # tomorrow

    def test_every_5m(self):
        now = datetime(2025, 1, 15, 10, 3)
        result = compute_next_run("*/5 * * * *", from_time=now.timestamp())
        next_dt = datetime.fromtimestamp(result)
        assert next_dt.minute == 5

    def test_specific_time_same_day(self):
        """If the time hasn't passed yet today, it fires today."""
        now = datetime(2025, 1, 15, 6, 0)
        result = compute_next_run("0 8 * * *", from_time=now.timestamp())
        next_dt = datetime.fromtimestamp(result)
        assert next_dt.day == 15  # today
        assert next_dt.hour == 8

    def test_weekday_only(self):
        """Saturday run for a Mon-Fri schedule should be Monday."""
        # Jan 4 2025 is Saturday
        now = datetime(2025, 1, 4, 10, 0)
        result = compute_next_run("0 9 * * 1-5", from_time=now.timestamp())
        next_dt = datetime.fromtimestamp(result)
        assert next_dt.weekday() == 0  # Monday
        assert next_dt.hour == 9


# ═══════════════════════════════════════════════════════════════════════════
# Unit: Routine dataclass
# ═══════════════════════════════════════════════════════════════════════════

class TestRoutine:
    def test_to_dict(self):
        r = Routine(name="test", schedule="0 8 * * *", prompt="hello")
        d = r.to_dict()
        assert d["name"] == "test"
        assert d["schedule"] == "0 8 * * *"
        assert "_id" not in d  # internals excluded

    def test_from_dict(self):
        d = {"name": "test", "schedule": "@daily", "prompt": "hello"}
        r = Routine.from_dict(d)
        assert r.name == "test"
        assert r.enabled is True
        assert r.job_type == "routine"

    def test_from_dict_with_extras(self):
        d = {
            "name": "test", "schedule": "@daily", "prompt": "hello",
            "enabled": False, "job_type": "reminder",
            "delete_after_run": True, "context_messages": 5,
        }
        r = Routine.from_dict(d)
        assert r.enabled is False
        assert r.job_type == "reminder"
        assert r.delete_after_run is True
        assert r.context_messages == 5

    def test_round_trip(self):
        r = Routine(name="roundtrip", schedule="0 8 * * *", prompt="test",
                    channel="desktop", enabled=False)
        d = r.to_dict()
        r2 = Routine.from_dict(d)
        assert r2.name == r.name
        assert r2.schedule == r.schedule
        assert r2.channel == r.channel
        assert r2.enabled is False


class TestRoutineExecution:
    def test_fields(self):
        ex = RoutineExecution(
            routine_name="test",
            started_at=1000.0,
            finished_at=1001.0,
            success=True,
            result_summary="done",
        )
        assert ex.routine_name == "test"
        assert ex.success is True
        assert ex.error == ""


# ═══════════════════════════════════════════════════════════════════════════
# Integration: RoutineScheduler
# ═══════════════════════════════════════════════════════════════════════════

class TestRoutineScheduler:
    def _scheduler(self, tmp: Path) -> RoutineScheduler:
        s = RoutineScheduler(storage_dir=tmp)
        return s

    def test_add_routine(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="morning", schedule="0 8 * * *", prompt="check calendar"))
        assert s.count == 1
        r = s.get("morning")
        assert r is not None
        assert r._next_run is not None

    def test_add_duplicate_raises(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="dup", schedule="@daily", prompt="x"))
        with pytest.raises(ValueError, match="already exists"):
            s.add(Routine(name="dup", schedule="@daily", prompt="y"))

    def test_remove_routine(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="rm", schedule="@daily", prompt="x"))
        assert s.remove("rm") is True
        assert s.count == 0
        assert s.remove("nonexistent") is False

    def test_enable_disable(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="toggle", schedule="@daily", prompt="x"))
        s.disable("toggle")
        assert s.get("toggle").enabled is False
        s.enable("toggle")
        assert s.get("toggle").enabled is True

    def test_list_all_vs_enabled(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="a", schedule="@daily", prompt="a"))
        s.add(Routine(name="b", schedule="@daily", prompt="b"))
        s.disable("b")
        assert len(s.list()) == 2
        assert len(s.list(enabled_only=True)) == 1

    def test_get_due_returns_due(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        # Schedule that fires every minute — guaranteed due
        r = Routine(name="frequent", schedule="*/1 * * * *", prompt="tick")
        # Force next_run to the past
        s.add(r)
        s.get("frequent")._next_run = time.time() - 60
        due = s.get_due()
        assert len(due) == 1
        assert due[0].name == "frequent"

    def test_get_due_empty_when_nothing_due(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        # Schedule far in the future
        r = Routine(name="future", schedule="0 3 1 1 *", prompt="once a year")
        s.add(r)
        # Override next_run to future
        s.get("future")._next_run = time.time() + 999999
        assert s.get_due() == []

    def test_mark_run_updates(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="runme", schedule="*/1 * * * *", prompt="x"))
        s.get("runme")._next_run = time.time() - 10
        s.mark_run("runme", success=True, result_summary="done")
        r = s.get("runme")
        assert r._run_count == 1
        assert r._last_run is not None
        assert r._next_run is not None

    def test_mark_run_delete_after_run(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="once", schedule="@daily", prompt="x",
                       delete_after_run=True))
        s.get("once")._next_run = time.time() - 10
        s.mark_run("once", success=True)
        assert s.get("once") is None
        assert s.count == 0

    def test_mark_run_records_execution(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="rec", schedule="*/1 * * * *", prompt="x"))
        s.get("rec")._next_run = time.time() - 10
        s.mark_run("rec", success=True, result_summary="ok")
        execs = s.executions
        assert len(execs) == 1
        assert execs[0].routine_name == "rec"
        assert execs[0].success is True

    def test_save_load_roundtrip(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.add(Routine(name="persist", schedule="0 8 * * *", prompt="check email"))
        s.save()

        s2 = self._scheduler(tmp_path)
        s2.load()
        assert s2.count == 1
        r = s2.get("persist")
        assert r is not None
        assert r.schedule == "0 8 * * *"
        assert r._next_run is not None

    def test_load_missing_file(self, tmp_path: Path):
        s = self._scheduler(tmp_path)
        s.load()  # should not raise
        assert s.count == 0

    def test_load_corrupt_file(self, tmp_path: Path):
        (tmp_path / "routines.json").write_text("not json{{{")
        s = self._scheduler(tmp_path)
        s.load()  # should not raise
        assert s.count == 0
