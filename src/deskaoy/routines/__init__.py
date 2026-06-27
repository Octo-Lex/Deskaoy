"""Routines — scheduled automation with cron-like triggers.

Adopted from Pocket Agent's cron-jobs.ts pattern. Supports standard
5-field cron expressions plus simplified natural-language formats
(``every 5m``, ``@daily``, ``@hourly``).

Storage: JSON file via StorageResolver (or explicit path).
No external deps — pure stdlib.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Minimum allowed interval between cron fires (5 minutes).
#: Prevents abuse patterns like ``* * * * *`` (every minute).
MIN_CRON_INTERVAL_SECONDS: int = 300

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Routine:
    """A scheduled routine."""

    name: str
    schedule: str  # cron expression or natural language
    prompt: str  # what to do when triggered
    channel: str = "default"
    enabled: bool = True
    job_type: str = "routine"  # "routine" | "reminder"
    delete_after_run: bool = False
    context_messages: int = 0  # how many previous messages to include

    # ── Internal (not persisted) ──────────────────────────────────────────
    _id: int | None = field(default=None, repr=False, compare=False)
    _next_run: float | None = field(default=None, repr=False, compare=False)
    _last_run: float | None = field(default=None, repr=False, compare=False)
    _run_count: int = field(default=0, repr=False, compare=False)

    # -- Serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        """Persisted fields only (internal state is recomputed on load)."""
        return {
            "name": self.name,
            "schedule": self.schedule,
            "prompt": self.prompt,
            "channel": self.channel,
            "enabled": self.enabled,
            "job_type": self.job_type,
            "delete_after_run": self.delete_after_run,
            "context_messages": self.context_messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Routine:
        return cls(
            name=data["name"],
            schedule=data["schedule"],
            prompt=data["prompt"],
            channel=data.get("channel", "default"),
            enabled=data.get("enabled", True),
            job_type=data.get("job_type", "routine"),
            delete_after_run=data.get("delete_after_run", False),
            context_messages=data.get("context_messages", 0),
        )


@dataclass
class RoutineExecution:
    """Record of a single routine execution."""

    routine_name: str
    started_at: float
    finished_at: float
    success: bool
    result_summary: str
    error: str = ""


# ---------------------------------------------------------------------------
# Cron parsing helpers
# ---------------------------------------------------------------------------

_NAMED_SCHEDULES: dict[str, str] = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@hourly": "0 * * * *",
}

# Day-of-week mapping (0=Sunday … 6=Saturday)
_DOW_MAP: dict[str, int] = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3,
    "thu": 4, "fri": 5, "sat": 6,
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
    "thursday": 4, "friday": 5, "saturday": 6,
}


def _parse_field(expr: str, lo: int, hi: int) -> set[int]:
    """Parse a single cron field into a set of matching values.

    Supports: ``*``, ``*/N``, ``N``, ``N-M``, ``N,M``, ``N-M/S``.
    """
    values: set[int] = set()

    for part in expr.split(","):
        step = 1
        if "/" in part:
            range_part, step_s = part.split("/", 1)
            step = int(step_s)
        else:
            range_part = part

        if range_part == "*":
            start, end = lo, hi
        elif "-" in range_part:
            start_s, end_s = range_part.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            val = int(range_part)
            values.add(val)
            continue

        for v in range(start, end + 1, step):
            values.add(v)

    return values


def _parse_dow_field(expr: str) -> set[int]:
    """Parse day-of-week field, accepting numeric (0-6) or names."""
    values: set[int] = set()
    for part in expr.split(","):
        part_lower = part.strip().lower()
        # Strip step suffix for name lookup
        base = part_lower.split("/")[0].split("-")[0].strip()
        if base in _DOW_MAP:
            # Replace names with numbers, then parse normally
            mapped = part_lower.replace(base, str(_DOW_MAP[base]))
            values |= _parse_field(mapped, 0, 6)
        else:
            values |= _parse_field(part, 0, 6)
    return values


def _resolve_schedule(schedule: str) -> str:
    """Resolve named schedules and ``every Ns/m/h`` shortcuts."""
    s = schedule.strip()

    # Named schedules
    if s.startswith("@"):
        return _NAMED_SCHEDULES.get(s.lower(), s)

    # "every Nm", "every Nh", "every Ns"
    if s.lower().startswith("every "):
        rest = s[6:].strip()
        if rest.endswith("m") and rest[:-1].isdigit():
            n = int(rest[:-1])
            return f"*/{n} * * * *" if n <= 59 else f"0 */{n // 60} * * *"
        if rest.endswith("h") and rest[:-1].isdigit():
            n = int(rest[:-1])
            return f"0 */{n} * * *"
        if rest.endswith("s") and rest[:-1].isdigit():
            # Seconds not supported in cron; treat as minutes
            n = max(1, int(rest[:-1]) // 60)
            return f"*/{n} * * * *"

    return s


def _parse_cron(schedule: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    """Parse a 5-field cron expression into (minute, hour, day, month, dow) sets."""
    parts = schedule.split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5 cron fields, got {len(parts)}: {schedule!r}")

    minutes = _parse_field(parts[0], 0, 59)
    hours = _parse_field(parts[1], 0, 23)
    days = _parse_field(parts[2], 1, 31)
    months = _parse_field(parts[3], 1, 12)
    dows = _parse_dow_field(parts[4])

    return minutes, hours, days, months, dows


# ---------------------------------------------------------------------------
# Timezone-aware scheduling (Skyvern pattern)
# ---------------------------------------------------------------------------

def _cron_fields_to_seconds(
    minutes: set[int], hours: set[int],
    days: set[int], months: set[int], dows: set[int],
    from_dt: datetime,
) -> float | None:
    """Search forward from *from_dt* for the next matching cron time.

    Returns a UTC timestamp or ``None`` if nothing found within 366 days.
    """
    candidate = from_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = from_dt + timedelta(days=366)
    while candidate <= limit:
        if (candidate.minute in minutes
                and candidate.hour in hours
                and candidate.day in days
                and candidate.month in months
                and (candidate.weekday() + 1) % 7 in dows):
            return candidate.timestamp()
        candidate += timedelta(minutes=1)
    return None


def _validate_cron_interval(resolved: str) -> None:
    """Raise ``ValueError`` if the cron interval is less than ``MIN_CRON_INTERVAL_SECONDS``.

    Computes two consecutive fires and checks the gap.
    """
    try:
        fields = _parse_cron(resolved)
    except ValueError:
        raise ValueError(f"Invalid cron expression: {resolved!r}") from None

    # Compute first and second fires from a fixed reference point
    ref = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    first_ts = _cron_fields_to_seconds(*fields, from_dt=ref)
    if first_ts is None:
        raise ValueError(f"Invalid cron expression (no fire in 366 days): {resolved!r}")

    first_dt = datetime.fromtimestamp(first_ts, tz=UTC)
    second_ts = _cron_fields_to_seconds(*fields, from_dt=first_dt)
    if second_ts is None:
        return  # Only one fire per year is fine

    gap = second_ts - first_ts
    if gap < MIN_CRON_INTERVAL_SECONDS:
        raise ValueError(
            f"Cron interval too short: {gap:.0f}s < {MIN_CRON_INTERVAL_SECONDS}s "
            f"(minimum {MIN_CRON_INTERVAL_SECONDS // 60} minutes)"
        )


def validate_cron_expression(expr: str) -> None:
    """Validate a cron expression (named, natural-language, or 5-field).

    Checks:
      1. The expression can be resolved to a valid 5-field cron.
      2. The interval between consecutive fires is ≥ ``MIN_CRON_INTERVAL_SECONDS``.

    Raises:
      ValueError: If the expression is invalid or too frequent.
    """
    resolved = _resolve_schedule(expr)
    _validate_cron_interval(resolved)


def compute_next_run(
    schedule: str,
    from_time: float | None = None,
    *,
    timezone_name: str | None = None,
) -> float:
    """Compute the next run time for *schedule* as a monotonic timestamp.

    *from_time* defaults to ``time.time()`` (now).
    *timezone_name* is an optional IANA timezone name (e.g. ``"America/New_York"``).
    When ``None``, uses local time (backward compat). When set, the cron
    expression is evaluated in the specified timezone.
    """
    resolved = _resolve_schedule(schedule)
    minutes, hours, days, months, dows = _parse_cron(resolved)

    from_ts = from_time or time.time()

    if timezone_name is not None:
        tz = ZoneInfo(timezone_name)
        now = datetime.fromtimestamp(from_ts, tz=tz)
    else:
        now = datetime.fromtimestamp(from_ts)

    result = _cron_fields_to_seconds(minutes, hours, days, months, dows, now)
    if result is not None:
        return result

    # Fallback: 24 hours from now
    return (now + timedelta(hours=24)).timestamp()


def compute_previous_fire_time(
    schedule: str,
    timezone_name: str = "UTC",
) -> float:
    """Compute the most recent scheduled fire time before now.

    Useful for catch-up logic: determine if a routine missed its last
    scheduled slot.

    Returns a UTC timestamp.
    """
    resolved = _resolve_schedule(schedule)
    minutes, hours, days, months, dows = _parse_cron(resolved)

    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)

    # Search backwards in 1-minute steps (max 366 days)
    candidate = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    limit = now - timedelta(days=366)
    while candidate >= limit:
        if (candidate.minute in minutes
                and candidate.hour in hours
                and candidate.day in days
                and candidate.month in months
                and (candidate.weekday() + 1) % 7 in dows):
            return candidate.astimezone(UTC).timestamp()
        candidate -= timedelta(minutes=1)

    # Fallback
    return (now - timedelta(hours=24)).timestamp()


def calculate_next_runs(
    schedule: str,
    timezone_name: str | None = None,
    count: int = 5,
) -> list[float]:
    """Compute the next *count* fire times for *schedule*.

    Returns a list of UTC timestamps, starting from the nearest future fire.
    When *timezone_name* is ``None``, uses local time (backward compat).
    """
    resolved = _resolve_schedule(schedule)
    minutes, hours, days, months, dows = _parse_cron(resolved)

    if timezone_name is not None:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
    else:
        now = datetime.now()

    results: list[float] = []
    current = now

    for _ in range(count):
        ts = _cron_fields_to_seconds(minutes, hours, days, months, dows, current)
        if ts is None:
            break
        results.append(ts)
        # Advance past this fire to find the next one
        current = datetime.fromtimestamp(ts, tz=now.tzinfo) if now.tzinfo else datetime.fromtimestamp(ts)

    return results


# ---------------------------------------------------------------------------
# RoutineScheduler
# ---------------------------------------------------------------------------

_NEXT_ID = 1


class RoutineScheduler:
    """Schedule and execute routines on a cron-like basis.

    Uses no external deps — parses simplified cron expressions
    (minute hour day month weekday) and checks against system clock.
    Stores routines in a JSON file.
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._routines: dict[str, Routine] = {}
        self._executions: list[RoutineExecution] = []
        self._storage_path: Path | None = None

        if storage_dir is not None:
            self._storage_path = storage_dir / "routines.json"

    # ── CRUD ────────────────────────────────────────────────────────────────

    def add(self, routine: Routine) -> str:
        """Register a routine and compute its first ``_next_run``."""
        if routine.name in self._routines:
            raise ValueError(f"Routine {routine.name!r} already exists")

        global _NEXT_ID
        routine._id = _NEXT_ID
        _NEXT_ID += 1
        routine._next_run = compute_next_run(routine.schedule)
        self._routines[routine.name] = routine
        self.save()
        return routine.name

    def remove(self, name: str) -> bool:
        """Remove a routine by name. Returns True if found."""
        if name not in self._routines:
            return False
        del self._routines[name]
        self.save()
        return True

    def get(self, name: str) -> Routine | None:
        return self._routines.get(name)

    def enable(self, name: str) -> None:
        r = self._routines.get(name)
        if r is not None:
            r.enabled = True
            self.save()

    def disable(self, name: str) -> None:
        r = self._routines.get(name)
        if r is not None:
            r.enabled = False
            self.save()

    def list(self, enabled_only: bool = False) -> list[Routine]:
        routines = list(self._routines.values())
        if enabled_only:
            routines = [r for r in routines if r.enabled]
        return sorted(routines, key=lambda r: r.name)

    # ── Scheduling ──────────────────────────────────────────────────────────

    def get_due(self) -> list[Routine]:
        """Return enabled routines whose ``_next_run <= now``."""
        now = time.time()
        return [r for r in self._routines.values()
                if r.enabled and r._next_run is not None and r._next_run <= now]

    def mark_run(self, name: str, *, success: bool = True,
                 result_summary: str = "", error: str = "") -> None:
        """Update a routine after execution: set last_run, increment count,
        compute next_run. Handle ``delete_after_run``."""
        r = self._routines.get(name)
        if r is None:
            return

        now = time.time()
        started = r._next_run or now

        r._last_run = now
        r._run_count += 1

        # Record execution
        self._executions.append(RoutineExecution(
            routine_name=name,
            started_at=started,
            finished_at=now,
            success=success,
            result_summary=result_summary,
            error=error,
        ))

        if r.delete_after_run:
            del self._routines[name]
        else:
            r._next_run = compute_next_run(r.schedule)

        self.save()

    # ── Persistence ─────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load routines from JSON file. Creates empty state if file missing."""
        if self._storage_path is None:
            return
        if not self._storage_path.exists():
            self._routines = {}
            return

        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._routines = {}
            for item in data.get("routines", []):
                r = Routine.from_dict(item)
                r._next_run = compute_next_run(r.schedule)
                global _NEXT_ID
                r._id = _NEXT_ID
                _NEXT_ID += 1
                self._routines[r.name] = r
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Failed to load routines: %s", exc)
            self._routines = {}

    def save(self) -> None:
        """Persist routines to JSON file."""
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "routines": [r.to_dict() for r in self._routines.values()],
        }
        self._storage_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._routines)

    @property
    def executions(self) -> list[RoutineExecution]:
        return list(self._executions)
