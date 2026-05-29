"""Blackboard — shared key-value store for multi-app orchestration.

AppAgents write results to the blackboard; other AppAgents read them.
Supports async read_or_wait() for DAG dependency synchronization.

The blackboard tracks who wrote what and when, enabling provenance
and conflict detection.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class BlackboardEntry:
    """A single entry in the blackboard."""

    key: str
    value: Any
    writer: str
    timestamp: float
    version: int = 1


class Blackboard:
    """Shared state store for multi-app orchestration.

    Thread-safe and async-friendly. Keys are dot-namespaced strings
    (e.g. "email.subject", "task.url") to avoid collisions.

    Usage:
        bb = Blackboard()
        bb.write("email.subject", "Q3 Report", writer="outlook_agent")
        subject = bb.read("email.subject")  # → "Q3 Report"
    """

    def __init__(self) -> None:
        self._entries: dict[str, BlackboardEntry] = {}
        self._lock = threading.Lock()
        self._waiters: dict[str, list[asyncio.Event]] = {}

    def write(self, key: str, value: Any, writer: str) -> None:
        """Write a value to the blackboard.

        If the key already exists, the value is overwritten and the
        version is incremented.
        """
        with self._lock:
            existing = self._entries.get(key)
            version = (existing.version + 1) if existing else 1
            self._entries[key] = BlackboardEntry(
                key=key,
                value=value,
                writer=writer,
                timestamp=time.monotonic(),
                version=version,
            )
            # Notify any waiters
            for event in self._waiters.pop(key, []):
                with contextlib.suppress(RuntimeError):
                    event.set()

    def read(self, key: str) -> Any | None:
        """Read a value. Returns None if the key doesn't exist."""
        with self._lock:
            entry = self._entries.get(key)
            return entry.value if entry else None

    async def read_or_wait(self, key: str, timeout: float = 30.0) -> Any:
        """Read a value, waiting until it's written if necessary.

        Raises TimeoutError if the key is not written within *timeout* seconds.
        """
        # Fast path: already written
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                return entry.value
            # Register waiter
            event = asyncio.Event()
            self._waiters.setdefault(key, []).append(event)

        # Wait for the write to happen
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            raise TimeoutError(
                f"Blackboard key '{key}' was not written within {timeout}s"
            ) from None

        # Read the now-available value
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                return entry.value
            raise KeyError(f"Blackboard key '{key}' disappeared unexpectedly")

    def has(self, key: str) -> bool:
        """Check if a key exists in the blackboard."""
        with self._lock:
            return key in self._entries

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all current values.

        Returns a plain dict mapping keys to values (no metadata).
        """
        with self._lock:
            return {k: e.value for k, e in self._entries.items()}

    def snapshot_with_meta(self) -> dict[str, dict]:
        """Return a snapshot with writer and timestamp metadata."""
        with self._lock:
            return {
                k: {"value": e.value, "writer": e.writer, "timestamp": e.timestamp, "version": e.version}
                for k, e in self._entries.items()
            }

    def keys(self) -> list[str]:
        """Return all keys currently in the blackboard."""
        with self._lock:
            return list(self._entries.keys())

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._entries.clear()
            # Wake up any waiters (they'll get KeyError)
            for events in self._waiters.values():
                for event in events:
                    with contextlib.suppress(RuntimeError):
                        event.set()
            self._waiters.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return self.has(key)
