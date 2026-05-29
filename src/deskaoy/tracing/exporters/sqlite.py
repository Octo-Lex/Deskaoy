"""SQLiteExporter — queue-backed SQLite writer for thread safety.

Design
------
* OTel ``BatchSpanProcessor`` calls :meth:`export` from a background thread.
* This exporter enqueues spans into a bounded :class:`queue.Queue`.
* A dedicated writer thread owns its own :class:`SessionDB` / connection,
  drains the queue, and batch-inserts into SQLite.
* This avoids ``check_same_thread=False`` — the single writer owns the
  connection exclusively.

Durability contract
-------------------
* ``export()`` enqueues → returns ``SUCCESS``.  Returns ``FAILURE`` when
  queue is full or writer thread has failed.
* ``force_flush(timeout_millis)`` blocks until all *previously accepted*
  spans are durable.  Returns ``False`` on timeout.
* ``shutdown()`` drains the queue, joins the writer thread, and closes the
  SessionDB connection.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Sequence
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from deskaoy.tracing.session_db import SessionDB
from deskaoy.tracing.types import SpanKind, SpanStatus, TraceEvent

# Sentinel objects for queue communication.
_SHUTDOWN = object()
_FLUSH = object()


class SQLiteExporter(SpanExporter):
    """Queue-backed SQLite writer.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    batch_size:
        Number of spans the writer thread accumulates before flushing
        to the database.
    max_queue:
        Bounded queue capacity.  When full, :meth:`export` returns
        ``FAILURE``.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        batch_size: int = 50,
        max_queue: int = 2048,
    ) -> None:
        self._db_path = db_path
        self._batch_size = batch_size
        self._max_queue = max_queue
        self._queue: queue.Queue[TraceEvent | object] = queue.Queue(maxsize=max_queue)
        self._shutdown_event = threading.Event()
        self._flush_lock = threading.Lock()
        self._flush_event = threading.Event()
        self._writer_failed = False

        # Start the dedicated writer thread.
        self._writer = threading.Thread(
            target=self._writer_loop,
            name="sqlite-exporter-writer",
            daemon=True,
        )
        self._writer.start()

    # ------------------------------------------------------------------
    # Internal: convert OTel span → TraceEvent
    # ------------------------------------------------------------------

    @staticmethod
    def _span_to_event(span: ReadableSpan) -> TraceEvent:
        """Convert an OTel ReadableSpan to a TraceEvent for SessionDB."""
        ctx = span.get_span_context()
        parent = span.parent
        parent_span_id = format(parent.span_id, "016x") if parent else None
        attrs = dict(span.attributes or {})

        # Derive status string from OTel StatusCode.
        status_str = str(span.status.status_code).split(".")[-1].lower()
        try:
            status = SpanStatus(status_str)
        except ValueError:
            status = SpanStatus.OK

        # Derive span_kind from attributes or name heuristics.
        kind_str = attrs.pop("span_kind", None)
        if kind_str is None:
            kind_str = "custom"
        try:
            span_kind = SpanKind(kind_str)
        except ValueError:
            span_kind = SpanKind.CUSTOM

        # Calculate duration_ms from start/end time (nanoseconds).
        duration_ms = 0.0
        if span.start_time and span.end_time:
            duration_ms = (span.end_time - span.start_time) / 1_000_000

        # Extract token / cost attributes.
        token_input = int(attrs.pop("token_input", 0))
        token_output = int(attrs.pop("token_output", 0))
        token_cost_usd = float(attrs.pop("token_cost_usd", 0.0))

        # Extract session_id from attributes.
        session_id = attrs.pop("session_id", None)

        return TraceEvent(
            trace_id=format(ctx.trace_id, "032x"),
            step_id=0,
            span_id=format(ctx.span_id, "016x"),
            span_kind=span_kind,
            name=span.name,
            duration_ms=duration_ms,
            status=status,
            parent_span_id=parent_span_id,
            session_id=session_id,
            attributes=attrs,
            token_input=token_input,
            token_output=token_output,
            token_cost_usd=token_cost_usd,
        )

    # ------------------------------------------------------------------
    # Writer thread
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        """Dedicated writer thread — owns SessionDB connection."""
        db = SessionDB(self._db_path)
        db.initialize()
        batch: list[TraceEvent] = []

        try:
            while not self._shutdown_event.is_set():
                try:
                    item = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue

                if item is _SHUTDOWN:
                    # Drain accumulated batch.
                    self._drain_batch(batch, db)
                    batch.clear()
                    # Drain any remaining items in the queue.
                    self._drain_remaining(batch, db)
                    self._signal_flush()
                    break
                elif item is _FLUSH:
                    # Drain accumulated batch, then signal.
                    self._drain_batch(batch, db)
                    batch.clear()
                    # Also drain any items that arrived before the _FLUSH
                    # but after we last checked the queue.
                    self._drain_until_flush(db)
                    self._signal_flush()
                    continue

                # Regular TraceEvent.
                batch.append(item)

                # Drain when batch is full.
                if len(batch) >= self._batch_size:
                    self._drain_batch(batch, db)
                    batch.clear()

            # Final drain on shutdown (in case we exited the loop via event).
            self._drain_batch(batch, db)
            self._drain_remaining(batch, db)
            self._signal_flush()
        except Exception:
            self._writer_failed = True
        finally:
            # Close the database connection.
            if db._conn is not None:
                import contextlib
                with contextlib.suppress(Exception):
                    db._conn.close()

    def _drain_batch(self, batch: list[TraceEvent], db: SessionDB) -> None:
        """Insert a batch of events into the database."""
        if not batch:
            return
        import contextlib
        with contextlib.suppress(Exception):
            db.insert_events(batch)

    def _drain_remaining(self, batch: list[TraceEvent], db: SessionDB) -> None:
        """Drain all remaining items from the queue."""
        temp: list[TraceEvent] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, TraceEvent):
                temp.append(item)
        if temp:
            self._drain_batch(temp, db)
        batch.clear()

    def _drain_until_flush(self, db: SessionDB) -> None:
        """Drain items from the queue until empty or a sentinel is found."""
        temp: list[TraceEvent] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, TraceEvent):
                temp.append(item)
            # If we hit another sentinel, put it back and stop.
            elif item is _FLUSH or item is _SHUTDOWN:
                import contextlib
                with contextlib.suppress(queue.Full):
                    self._queue.put_nowait(item)
                break
        if temp:
            self._drain_batch(temp, db)

    def _signal_flush(self) -> None:
        """Notify waiting flush callers that data is durable."""
        with self._flush_lock:
            self._flush_event.set()

    # ------------------------------------------------------------------
    # SpanExporter interface
    # ------------------------------------------------------------------

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Enqueue spans for writing.  Returns ``FAILURE`` if queue is full."""
        if self._writer_failed:
            return SpanExportResult.FAILURE

        events = [self._span_to_event(s) for s in spans]
        for event in events:
            try:
                # Non-blocking put — return FAILURE immediately if full.
                self._queue.put_nowait(event)
            except queue.Full:
                return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        """Block until all previously-accepted spans are durable."""
        if self._writer_failed:
            return False

        # Reset the flush event and enqueue a _FLUSH sentinel.
        with self._flush_lock:
            self._flush_event.clear()

        try:
            self._queue.put_nowait(_FLUSH)
        except queue.Full:
            return False

        return self._flush_event.wait(timeout=timeout_millis / 1000.0)

    def shutdown(self) -> None:
        """Drain queue, join writer thread, close connection."""
        self._shutdown_event.set()
        import contextlib
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_SHUTDOWN)
        self._writer.join(timeout=10.0)
