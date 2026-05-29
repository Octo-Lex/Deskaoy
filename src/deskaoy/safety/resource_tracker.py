"""ResourceTracker — track and cleanup resources in long-running sessions.

Adopted from UI-TARS Desktop's ``resource-cleaner.ts`` pattern.
Long-running sessions accumulate resources (temp files, screenshots,
browser contexts, ledger handles). The tracker:

- Records resources with cleanup callbacks
- Cleans up all resources on session termination
- Supports age-based cleanup for stale resources
- Thread-safe for concurrent access

No external deps — pure stdlib.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrackedResource:
    """A tracked resource with optional cleanup callback."""
    resource_type: str   # "temp_file", "screenshot", "browser_context", "ledger"
    resource_id: str
    created_at: float = field(default_factory=time.time)
    cleanup_fn: Callable[[], Any] | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class ResourceTracker:
    """Track and cleanup resources in long-running sessions.

    Thread-safe. Call ``cleanup_all()`` in ``terminate_session()`` to
    release all tracked resources.

    Usage::

        tracker = ResourceTracker()
        tracker.track("temp_file", "/tmp/shot_123.png",
                      cleanup_fn=lambda: os.unlink("/tmp/shot_123.png"))
        # ... later ...
        tracker.cleanup_all()  # Removes all tracked resources
    """

    def __init__(self) -> None:
        self._resources: dict[str, TrackedResource] = {}
        self._lock = threading.Lock()

    def track(
        self,
        resource_type: str,
        resource_id: str,
        cleanup_fn: Callable[[], Any] | None = None,
        **metadata: Any,
    ) -> str:
        """Register a resource for tracking.

        Args:
            resource_type: Category (e.g. "temp_file", "screenshot").
            resource_id: Unique identifier for the resource.
            cleanup_fn: Optional callback to release the resource.
            **metadata: Extra metadata stored with the resource.

        Returns:
            The resource_id (for untracking).
        """
        with self._lock:
            resource = TrackedResource(
                resource_type=resource_type,
                resource_id=resource_id,
                cleanup_fn=cleanup_fn,
                metadata=metadata,
            )
            self._resources[resource_id] = resource
            return resource_id

    def untrack(self, resource_id: str) -> bool:
        """Remove a resource from tracking without running cleanup.

        Returns True if the resource was found.
        """
        with self._lock:
            return self._resources.pop(resource_id, None) is not None

    def cleanup(self, resource_id: str) -> bool:
        """Run cleanup for a specific resource and untrack it.

        Returns True if the resource was found and cleaned up.
        """
        with self._lock:
            resource = self._resources.pop(resource_id, None)
        if resource is None:
            return False
        self._run_cleanup(resource)
        return True

    def cleanup_all(self) -> int:
        """Run cleanup for all tracked resources.

        Returns the count of resources cleaned up.
        """
        with self._lock:
            resources = list(self._resources.values())
            self._resources.clear()

        count = 0
        for resource in resources:
            self._run_cleanup(resource)
            count += 1
        return count

    def cleanup_older_than(self, max_age_seconds: float) -> int:
        """Cleanup resources older than the given age threshold.

        Args:
            max_age_seconds: Maximum age in seconds. Resources older
                than this are cleaned up.

        Returns:
            Count of resources cleaned up.
        """
        now = time.time()
        to_clean: list[TrackedResource] = []

        with self._lock:
            expired = [
                rid for rid, res in self._resources.items()
                if (now - res.created_at) > max_age_seconds
            ]
            for rid in expired:
                to_clean.append(self._resources.pop(rid))

        for resource in to_clean:
            self._run_cleanup(resource)
        return len(to_clean)

    def get_by_type(self, resource_type: str) -> list[TrackedResource]:
        """Get all tracked resources of a given type."""
        with self._lock:
            return [
                res for res in self._resources.values()
                if res.resource_type == resource_type
            ]

    @property
    def count(self) -> int:
        """Number of currently tracked resources."""
        with self._lock:
            return len(self._resources)

    @property
    def tracked_types(self) -> set[str]:
        """Set of unique resource types currently tracked."""
        with self._lock:
            return {res.resource_type for res in self._resources.values()}

    def _run_cleanup(self, resource: TrackedResource) -> None:
        """Execute a resource's cleanup callback. Best-effort."""
        if resource.cleanup_fn is None:
            return
        try:
            result = resource.cleanup_fn()
            # Handle async cleanup functions
            if asyncio.iscoroutine(result):
                logger.warning(
                    "Async cleanup_fn for %s/%s — skipped in sync context. "
                    "Use cleanup_all_async() instead.",
                    resource.resource_type, resource.resource_id,
                )
        except Exception:
            logger.warning(
                "Cleanup failed for %s/%s",
                resource.resource_type, resource.resource_id,
                exc_info=True,
            )

    async def cleanup_all_async(self) -> int:
        """Async version of cleanup_all — handles async cleanup callbacks."""
        with self._lock:
            resources = list(self._resources.values())
            self._resources.clear()

        count = 0
        for resource in resources:
            if resource.cleanup_fn is not None:
                try:
                    result = resource.cleanup_fn()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.warning(
                        "Async cleanup failed for %s/%s",
                        resource.resource_type, resource.resource_id,
                        exc_info=True,
                    )
            count += 1
        return count

