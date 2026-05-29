"""SnapshotStore — persistent snapshot storage with LRU eviction.

Manages snapshot lifecycle: create → persist → query → evict.
All file I/O is async via asyncio.to_thread for non-blocking operation.

HB-01: Only writes to ~/.deskaoy/snapshots/
AR-01: Only SnapshotStore.create() may write snapshot files.
AR-04: LRU eviction runs on every create().
"""

from __future__ import annotations

import dataclasses as _dc
import json
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from deskaoy.cascade.snapshot_types import (
    SnapshotElement,
    SnapshotInfo,
    SnapshotRecord,
    StaleResult,
    assign_element_ids,
)


@_dc.dataclass
class SnapshotMetrics:
    """LRU cache metrics for SnapshotStore.

    Fields:
        hits: Number of cache hits (snapshot found by get()).
        misses: Number of cache misses (snapshot not found by get()).
        evictions: Number of snapshots evicted by LRU policy.
        total_size_bytes: Estimated total size of all snapshot files on disk.
        count: Number of snapshots currently stored.
    """
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_size_bytes: int = 0
    count: int = 0

logger = logging.getLogger(__name__)


class SnapshotStore:
    """Persistent snapshot store with LRU eviction.

    Snapshots are stored as directories under SNAPSHOT_DIR:
        ~/.deskaoy/snapshots/<uuid>/
            snapshot.json
            raw.png              (optional)

    Usage:
        store = SnapshotStore()
        sid = await store.create(elements, screenshot_bytes, metadata)
        record = await store.get(sid)
    """

    SNAPSHOT_DIR: Path = Path.home() / ".deskaoy" / "snapshots"
    MAX_SNAPSHOTS: int = 50

    def __init__(
        self,
        *,
        snapshot_dir: Path | None = None,
        max_snapshots: int | None = None,
    ) -> None:
        if snapshot_dir is not None:
            self._snapshot_dir = Path(snapshot_dir)
        else:
            self._snapshot_dir = self.SNAPSHOT_DIR
        if max_snapshots is not None:
            self._max_snapshots = max_snapshots
        else:
            self._max_snapshots = self.MAX_SNAPSHOTS

        # Metrics counters
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    @property
    def snapshot_dir(self) -> Path:
        return self._snapshot_dir

    @property
    def max_snapshots(self) -> int:
        return self._max_snapshots

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(
        self,
        elements: list[dict],
        screenshot_bytes: bytes | None = None,
        *,
        metadata: dict | None = None,
    ) -> str:
        """Create a new snapshot and persist it to disk.

        Args:
            elements: List of element dicts, each with at least 'role' key.
                      Additional keys: name, bounds, actionable, value, description.
            screenshot_bytes: Optional PNG screenshot bytes.
            metadata: Optional dict with window metadata:
                      application, window_title, window_bounds, bundle_id, pid, platform.

        Returns:
            The snapshot ID (UUID v4 string).
        """
        meta = metadata or {}

        # Assign deterministic element IDs
        element_ids = assign_element_ids(elements)
        snapshot_elements: list[SnapshotElement] = []
        for elem_dict, eid in zip(elements, element_ids, strict=False):
            snapshot_elements.append(SnapshotElement(
                element_id=eid,
                role=elem_dict.get("role", ""),
                name=elem_dict.get("name"),
                bounds=elem_dict.get("bounds"),
                actionable=elem_dict.get("actionable", False),
                value=elem_dict.get("value"),
                description=elem_dict.get("description"),
            ))

        snapshot_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()

        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            created_at=created_at,
            application=meta.get("application"),
            window_title=meta.get("window_title"),
            window_bounds=meta.get("window_bounds"),
            bundle_id=meta.get("bundle_id"),
            pid=meta.get("pid"),
            platform=meta.get("platform", "windows"),
            elements=snapshot_elements,
        )

        # Write to disk
        snap_dir = self._snapshot_dir / snapshot_id
        await self._write_snapshot(snap_dir, record, screenshot_bytes)

        # LRU eviction
        await self._evict_if_needed()

        logger.debug("Snapshot created: %s (%d elements)", snapshot_id, len(snapshot_elements))
        return snapshot_id

    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------

    async def get(self, snapshot_id: str) -> SnapshotRecord | None:
        """Load a snapshot from disk by ID.

        Returns None if the snapshot does not exist.
        """
        snap_dir = self._snapshot_dir / snapshot_id
        json_path = snap_dir / "snapshot.json"
        if not json_path.exists():
            self._misses += 1
            return None

        try:
            data = await self._read_json(json_path)
            screenshot_path = snap_dir / "raw.png"
            sp = screenshot_path if screenshot_path.exists() else None
            self._hits += 1
            return SnapshotRecord.from_dict(data, screenshot_path=sp)
        except Exception as exc:
            self._misses += 1
            logger.error("Failed to load snapshot %s: %s", snapshot_id, exc)
            return None

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list_snapshots(self) -> list[SnapshotInfo]:
        """List all stored snapshots (summary info, no element data)."""
        if not self._snapshot_dir.exists():
            return []

        infos: list[SnapshotInfo] = []
        for snap_dir in sorted(self._snapshot_dir.iterdir()):
            if not snap_dir.is_dir():
                continue
            json_path = snap_dir / "snapshot.json"
            if not json_path.exists():
                continue
            try:
                data = await self._read_json(json_path)
                has_screenshot = (snap_dir / "raw.png").exists()
                infos.append(SnapshotInfo(
                    snapshot_id=data["snapshot_id"],
                    created_at=data["created_at"],
                    application=data.get("application"),
                    element_count=len(data.get("elements", [])),
                    has_screenshot=has_screenshot,
                ))
            except Exception as exc:
                logger.warning("Skipping corrupt snapshot %s: %s", snap_dir.name, exc)
        return infos

    # ------------------------------------------------------------------
    # Clean
    # ------------------------------------------------------------------

    async def clean(self, snapshot_id: str) -> bool:
        """Remove a single snapshot directory.

        Returns True if the snapshot existed and was removed.
        """
        snap_dir = self._snapshot_dir / snapshot_id
        if not snap_dir.exists():
            return False
        await self._rmtree(snap_dir)
        logger.debug("Snapshot cleaned: %s", snapshot_id)
        return True

    async def clean_all(self) -> int:
        """Remove all snapshot directories.

        Returns the number of snapshots removed.
        """
        if not self._snapshot_dir.exists():
            return 0

        count = 0
        for snap_dir in list(self._snapshot_dir.iterdir()):
            if snap_dir.is_dir():
                try:
                    await self._rmtree(snap_dir)
                    count += 1
                except Exception as exc:
                    logger.warning("Failed to clean %s: %s", snap_dir.name, exc)
        logger.debug("Cleaned all snapshots: %d removed", count)
        return count

    # ------------------------------------------------------------------
    # find_elements (TASK-03)
    # ------------------------------------------------------------------

    async def find_elements(
        self,
        snapshot_id: str,
        *,
        query: str | None = None,
        role: str | None = None,
        element_id: str | None = None,
    ) -> list[SnapshotElement]:
        """Search snapshot elements by name, role, or element_id.

        Args:
            snapshot_id: The snapshot to search.
            query: Case-insensitive substring match on element name.
            role: Exact role match.
            element_id: Exact element ID match.

        Returns:
            List of matching SnapshotElement objects.
            Empty list if snapshot not found or no matches.
        """
        record = await self.get(snapshot_id)
        if record is None:
            return []

        results: list[SnapshotElement] = []
        for elem in record.elements:
            if element_id is not None and elem.element_id != element_id:
                continue
            if role is not None and elem.role != role:
                continue
            if query is not None:
                name = (elem.name or "").lower()
                if query.lower() not in name:
                    continue
            results.append(elem)
        return results

    # ------------------------------------------------------------------
    # get_element (TASK-03)
    # ------------------------------------------------------------------

    async def get_element(
        self, snapshot_id: str, element_id: str
    ) -> SnapshotElement | None:
        """Get a single element from a snapshot by ID.

        Returns None if snapshot or element not found.
        """
        record = await self.get(snapshot_id)
        if record is None:
            return None
        for elem in record.elements:
            if elem.element_id == element_id:
                return elem
        return None

    # ------------------------------------------------------------------
    # is_stale (TASK-02)
    # ------------------------------------------------------------------

    async def is_stale(
        self,
        snapshot_id: str,
        *,
        current_bounds: dict | None = None,
        current_title: str | None = None,
        window_exists: bool | None = None,
        jitter_tolerance: int = 10,
    ) -> StaleResult:
        """Check if a snapshot is stale relative to current window state.

        A snapshot is stale if:
        - The snapshot doesn't exist (reason: "not_found")
        - The window no longer exists (reason: "window_closed")
        - The window moved by >jitter_tolerance pixels (reason: "window_moved")
        - The window was resized by >jitter_tolerance pixels (reason: "window_resized")
        - The window title changed (reason: "title_changed")

        Small position changes within jitter_tolerance are ignored to
        prevent false stale detection from minor window manager jitter.
        """
        record = await self.get(snapshot_id)
        if record is None:
            return StaleResult(is_stale=True, reason="not_found")

        # Window existence check
        if window_exists is False:
            return StaleResult(is_stale=True, reason="window_closed")

        # Title check
        if current_title is not None and record.window_title is not None:
            if current_title != record.window_title:
                return StaleResult(is_stale=True, reason="title_changed")

        # Bounds check (position + size)
        if current_bounds is not None and record.window_bounds is not None:
            dx = abs(current_bounds.get("x", 0) - record.window_bounds.get("x", 0))
            dy = abs(current_bounds.get("y", 0) - record.window_bounds.get("y", 0))
            dw = abs(current_bounds.get("width", 0) - record.window_bounds.get("width", 0))
            dh = abs(current_bounds.get("height", 0) - record.window_bounds.get("height", 0))

            # Check resize first (more severe)
            if dw > jitter_tolerance or dh > jitter_tolerance:
                return StaleResult(is_stale=True, reason="window_resized")

            # Check move
            if dx > jitter_tolerance or dy > jitter_tolerance:
                return StaleResult(is_stale=True, reason="window_moved")

        return StaleResult(is_stale=False, reason="")

    # ------------------------------------------------------------------
    # Metrics (BATCH-31)
    # ------------------------------------------------------------------

    async def get_metrics(self) -> SnapshotMetrics:
        """Return current LRU cache metrics.

        Computes size and count by scanning the snapshot directory.
        Hits, misses, and evictions are tracked in memory.
        """
        count = 0
        total_size = 0
        if self._snapshot_dir.exists():
            for snap_dir in self._snapshot_dir.iterdir():
                if snap_dir.is_dir():
                    json_path = snap_dir / "snapshot.json"
                    if json_path.exists():
                        count += 1
                        try:
                            for f in snap_dir.iterdir():
                                if f.is_file():
                                    total_size += f.stat().st_size
                        except Exception:
                            pass

        return SnapshotMetrics(
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
            total_size_bytes=total_size,
            count=count,
        )

    def reset_metrics(self) -> None:
        """Reset in-memory metrics counters. For testing."""
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _write_snapshot(
        self,
        snap_dir: Path,
        record: SnapshotRecord,
        screenshot_bytes: bytes | None,
    ) -> None:
        """Write snapshot files to disk (threaded for I/O)."""
        def _write():
            snap_dir.mkdir(parents=True, exist_ok=True)
            json_path = snap_dir / "snapshot.json"
            json_path.write_text(
                json.dumps(record.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if screenshot_bytes:
                (snap_dir / "raw.png").write_bytes(screenshot_bytes)

        import asyncio
        await asyncio.to_thread(_write)

    async def _read_json(self, path: Path) -> dict:
        """Read and parse a JSON file (threaded for I/O)."""
        import asyncio

        def _read():
            return json.loads(path.read_text(encoding="utf-8"))

        return await asyncio.to_thread(_read)

    async def _rmtree(self, path: Path) -> None:
        """Remove a directory tree (threaded for I/O)."""
        import asyncio
        await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)

    async def _evict_if_needed(self) -> None:
        """LRU eviction: delete oldest snapshots when MAX_SNAPSHOTS exceeded.

        AR-04: Runs on every create(). Evicts the oldest snapshot (by
        created_at timestamp) when the count exceeds max_snapshots.
        Uses directory mtime as secondary sort key for stable ordering
        when timestamps collide (fast sequential creates).
        """
        if not self._snapshot_dir.exists():
            return

        # Collect all snapshot directories with (created_at, mtime) for sorting
        snapshots: list[tuple[str, str, float]] = []
        for snap_dir in self._snapshot_dir.iterdir():
            if not snap_dir.is_dir():
                continue
            json_path = snap_dir / "snapshot.json"
            if not json_path.exists():
                continue
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                created = data.get("created_at", "")
                mtime = snap_dir.stat().st_mtime
                snapshots.append((snap_dir.name, created, mtime))
            except Exception:
                snapshots.append((snap_dir.name, "", snap_dir.stat().st_mtime))

        # Sort by (created_at, mtime) — oldest first
        snapshots.sort(key=lambda x: (x[1], x[2]))

        # Evict oldest until we're within limit
        while len(snapshots) > self._max_snapshots:
            oldest_id, _, _ = snapshots.pop(0)
            oldest_dir = self._snapshot_dir / oldest_id
            await self._rmtree(oldest_dir)
            self._evictions += 1
            logger.debug("LRU eviction: removed snapshot %s", oldest_id)
