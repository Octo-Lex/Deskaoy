"""JSONLExporter — write OTel spans as JSON Lines for file-based durability."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

if TYPE_CHECKING:
    pass


class JSONLExporter(SpanExporter):
    """Writes each exported span as one JSON line.

    Format matches existing :class:`FileSink` output (``TraceEvent.to_dict()``
    shape) for backward compatibility.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _span_to_dict(span: ReadableSpan) -> dict[str, Any]:
        """Convert an OTel ReadableSpan to a FileSink-compatible dict."""
        ctx = span.get_span_context()
        parent = span.parent
        parent_span_id = format(parent.span_id, "016x") if parent else None
        attrs = dict(span.attributes or {})

        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
            "parent_span_id": parent_span_id,
            "name": span.name,
            "kind": str(span.kind),
            "status": {
                "code": str(span.status.status_code),
                "description": span.status.description,
            },
            "start_time": span.start_time,
            "end_time": span.end_time,
            "attributes": attrs,
            "events": [
                {
                    "name": ev.name,
                    "timestamp": ev.timestamp,
                    "attributes": dict(ev.attributes or {}),
                }
                for ev in (span.events or [])
            ],
        }

    # ------------------------------------------------------------------
    # SpanExporter interface
    # ------------------------------------------------------------------

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Write *spans* as JSON lines.  Always returns ``SUCCESS``."""
        try:
            for span in spans:
                line = json.dumps(self._span_to_dict(span), default=str)
                self._file.write(line + "\n")
            self._file.flush()
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        """Flush the underlying file buffer."""
        try:
            self._file.flush()
            return True
        except Exception:
            return False

    def shutdown(self) -> None:
        """Close the file handle."""
        if self._file and not self._file.closed:
            self._file.flush()
            self._file.close()
