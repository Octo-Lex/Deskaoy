"""Tests for OTel exporters (BATCH-43 / TASK-03).

TEST-43-03-01 through TEST-43-03-11.
"""

from __future__ import annotations

import json
import sqlite3
import warnings

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from deskaoy.tracing.exporters.jsonl import JSONLExporter
from deskaoy.tracing.exporters.redacting import RedactingExporter
from deskaoy.tracing.exporters.sqlite import SQLiteExporter
from deskaoy.tracing.runtime import TelemetryConfig, TelemetryRuntime
from deskaoy.tracing.session_db import SessionDB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime():
    """Create a TelemetryRuntime with InMemorySpanExporter."""
    cfg = TelemetryConfig()
    rt = TelemetryRuntime(cfg)
    exporter = InMemorySpanExporter()
    rt.tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    return rt, exporter


def _make_provider_with_exporter(exporter):
    """Create a TracerProvider wired to *exporter* via SimpleSpanProcessor."""
    from opentelemetry.sdk.resources import Resource

    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider


# ===================================================================
# TEST-43-03-01  JSONLExporter writes spans to file
# ===================================================================


class TestJSONLExporter:

    def test_writes_spans_to_file(self, tmp_path):
        """File has 1+ non-empty lines after exporting spans."""
        path = tmp_path / "trace.jsonl"
        exporter = JSONLExporter(path)

        provider = _make_provider_with_exporter(exporter)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("key", "value")

        exporter.force_flush(5000)
        exporter.shutdown()

        assert path.exists(), "JSONL file should exist"
        lines = [l for l in path.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        assert len(lines) >= 1, f"Expected >= 1 line, got {len(lines)}"

        parsed = json.loads(lines[0])
        assert "trace_id" in parsed
        assert "name" in parsed

    def test_output_is_valid_json(self, tmp_path):
        """Each line is valid JSON."""
        path = tmp_path / "trace.jsonl"
        exporter = JSONLExporter(path)

        provider = _make_provider_with_exporter(exporter)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("span1"):
            pass
        with tracer.start_as_current_span("span2"):
            pass

        exporter.force_flush(5000)
        exporter.shutdown()

        lines = [l for l in path.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        for line in lines:
            parsed = json.loads(line)  # should not raise
            assert isinstance(parsed, dict)


# ===================================================================
# TEST-43-03-02  SQLiteExporter batch inserts spans
# ===================================================================


class TestSQLiteExporter:

    def test_batch_inserts_spans(self, tmp_path):
        """SessionDB has matching events after export."""
        db_path = tmp_path / "test.db"
        exporter = SQLiteExporter(db_path, batch_size=1, max_queue=128)

        provider = _make_provider_with_exporter(exporter)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("test.span"):
            pass

        exporter.force_flush(5000)
        exporter.shutdown()

        # Verify data landed in SQLite.
        conn = sqlite3.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
            assert count >= 1, f"Expected >= 1 event in DB, got {count}"
        finally:
            conn.close()

    def test_multiple_spans_inserted(self, tmp_path):
        """Multiple spans are all written."""
        db_path = tmp_path / "test.db"
        exporter = SQLiteExporter(db_path, batch_size=1, max_queue=128)

        provider = _make_provider_with_exporter(exporter)
        tracer = provider.get_tracer("test")

        for i in range(5):
            with tracer.start_as_current_span(f"span.{i}"):
                pass

        exporter.force_flush(5000)
        exporter.shutdown()

        conn = sqlite3.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
            assert count == 5, f"Expected 5 events in DB, got {count}"
        finally:
            conn.close()


# ===================================================================
# TEST-43-03-03  SQLiteExporter returns FAILURE on full queue
# ===================================================================


class TestSQLiteExporterQueueFull:

    def test_failure_on_full_queue(self, tmp_path):
        """Second export returns FAILURE when max_queue=1 and queue is full."""
        from opentelemetry.sdk.trace.export import SpanExportResult

        db_path = tmp_path / "test.db"
        exporter = SQLiteExporter(db_path, batch_size=100, max_queue=1)

        # Fill the queue manually (maxsize=1, one item fills it).
        from deskaoy.tracing.types import SpanKind, TraceEvent
        dummy_event = TraceEvent(
            trace_id="x", step_id=0, span_id="y",
            span_kind=SpanKind.CUSTOM, name="blocker",
        )
        exporter._queue.put_nowait(dummy_event)

        # Now export should fail — queue is full.
        provider = _make_provider_with_exporter(exporter)
        tracer = provider.get_tracer("test")
        span = tracer.start_span("overflow")
        span.end()
        result = exporter.export([span])

        exporter.shutdown()
        assert result == SpanExportResult.FAILURE, (
            "Expected FAILURE when queue is full"
        )


# ===================================================================
# TEST-43-03-04  SQLiteExporter force_flush durable
# ===================================================================


class TestSQLiteExporterFlush:

    def test_force_flush_returns_true(self, tmp_path):
        """force_flush returns True and data is on disk."""
        db_path = tmp_path / "test.db"
        exporter = SQLiteExporter(db_path, batch_size=50, max_queue=128)

        provider = _make_provider_with_exporter(exporter)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("test.span"):
            pass

        result = exporter.force_flush(5000)
        assert result is True, "force_flush should return True"

        # Verify data persisted.
        conn = sqlite3.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
            assert count >= 1
        finally:
            conn.close()

        exporter.shutdown()


# ===================================================================
# TEST-43-03-05  RedactingExporter strips secrets
# ===================================================================


class TestRedactingExporter:

    def test_strips_bearer_tokens(self, tmp_path):
        """No 'Bearer' followed by a real token in output."""
        inner = InMemorySpanExporter()
        redacting = RedactingExporter(inner)

        provider = _make_provider_with_exporter(redacting)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("api.call") as span:
            span.set_attribute("authorization", "Bearer sk-abc123def456ghi789jkl012mno345")

        spans = inner.get_finished_spans()
        assert len(spans) >= 1
        for span in spans:
            for _key, val in (span.attributes or {}).items():
                if isinstance(val, str):
                    assert "Bearer sk-" not in val, (
                        f"Bearer token should be redacted, got: {val}"
                    )

    def test_strips_sk_keys(self, tmp_path):
        """No 'sk-' API keys in output."""
        inner = InMemorySpanExporter()
        redacting = RedactingExporter(inner)

        provider = _make_provider_with_exporter(redacting)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("llm.call") as span:
            span.set_attribute("api_key", "sk-abcdefghijklmnopqrstuvwxyz123456")

        spans = inner.get_finished_spans()
        assert len(spans) >= 1
        for span in spans:
            for _key, val in (span.attributes or {}).items():
                if isinstance(val, str):
                    assert not any(
                        tok.startswith("sk-") and len(tok) > 24
                        for tok in val.split()
                    ), f"API key should be redacted, got: {val}"

    def test_does_not_mutate_original_spans(self):
        """RedactingExporter creates redacted copies — originals unchanged."""
        inner = InMemorySpanExporter()
        redacting = RedactingExporter(inner)

        provider = _make_provider_with_exporter(redacting)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("sensitive") as span:
            span.set_attribute("auth", "Bearer super-secret-token-here-1234567890")

        # The *inner* exporter got redacted spans.
        inner_spans = inner.get_finished_spans()
        assert len(inner_spans) >= 1
        auth_val = inner_spans[0].attributes.get("auth", "")
        assert "super-secret" not in auth_val, (
            f"Inner exporter should have redacted value, got: {auth_val}"
        )


# ===================================================================
# TEST-43-03-06  RedactingExporter delegates to inner
# ===================================================================


class TestRedactingExporterDelegation:

    def test_inner_exporter_received_spans(self):
        """Inner exporter received the spans."""
        inner = InMemorySpanExporter()
        redacting = RedactingExporter(inner)

        provider = _make_provider_with_exporter(redacting)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("delegated"):
            pass

        spans = inner.get_finished_spans()
        assert len(spans) >= 1, "Inner exporter should have received spans"

    def test_delegates_force_flush(self):
        """force_flush is delegated."""
        inner = InMemorySpanExporter()
        redacting = RedactingExporter(inner)
        assert redacting.force_flush(1000) is True

    def test_delegates_shutdown(self):
        """shutdown is delegated without error."""
        inner = InMemorySpanExporter()
        redacting = RedactingExporter(inner)
        redacting.shutdown()  # should not raise


# ===================================================================
# TEST-43-03-07  Concrete sinks emit DeprecationWarning
# ===================================================================


class TestSinkDeprecationWarnings:

    def test_console_sink_warns(self):
        """ConsoleSink.__init__ emits DeprecationWarning."""
        from deskaoy.tracing.sinks import ConsoleSink
        from deskaoy.tracing.types import SpanKind

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ConsoleSink(min_level=SpanKind.ACTION)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "ConsoleSink should emit DeprecationWarning"
            assert "ConsoleSink is deprecated" in str(dep_warnings[0].message)

    def test_file_sink_warns(self, tmp_path):
        """FileSink.__init__ emits DeprecationWarning."""
        from deskaoy.tracing.sinks import FileSink

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FileSink(tmp_path / "x.jsonl")
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "FileSink should emit DeprecationWarning"
            assert "FileSink is deprecated" in str(dep_warnings[0].message)

    def test_sqlite_sink_warns(self, tmp_path):
        """SQLiteSink.__init__ emits DeprecationWarning."""
        from deskaoy.tracing.sinks import SQLiteSink

        db = SessionDB(tmp_path / "test.db")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            SQLiteSink(db)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "SQLiteSink should emit DeprecationWarning"
            assert "SQLiteSink is deprecated" in str(dep_warnings[0].message)

    def test_prometheus_sink_warns(self):
        """PrometheusSink.__init__ emits DeprecationWarning."""
        from deskaoy.tracing.sinks import PrometheusSink

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            PrometheusSink()
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "PrometheusSink should emit DeprecationWarning"
            assert "PrometheusSink is deprecated" in str(dep_warnings[0].message)


# ===================================================================
# TEST-43-03-08  FlowLogger(sinks=) emits DeprecationWarning
# ===================================================================


class TestFlowLoggerSinksDeprecation:

    def test_sinks_param_emits_warning(self):
        """FlowLogger(sinks=[...]) emits DeprecationWarning."""
        from deskaoy.tracing.flow_logger import FlowLogger
        from deskaoy.tracing.sinks import TraceSink
        from deskaoy.tracing.types import TraceEvent

        class NoopSink(TraceSink):
            async def emit(self, event: TraceEvent) -> None:
                pass
            async def flush(self) -> None:
                pass
            async def close(self) -> None:
                pass

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FlowLogger(sinks=[NoopSink()])
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            fl_warnings = [
                x for x in dep_warnings
                if "FlowLogger" in str(x.message)
            ]
            assert len(fl_warnings) >= 1, (
                "FlowLogger(sinks=[...]) should emit DeprecationWarning"
            )
            assert "deprecated" in str(fl_warnings[0].message).lower()

    def test_no_warning_without_sinks(self):
        """FlowLogger() without sinks does NOT emit warning."""
        from deskaoy.tracing.flow_logger import FlowLogger

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FlowLogger()
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) == 0, (
                f"FlowLogger() without sinks should not warn, got: {dep_warnings}"
            )


# ===================================================================
# TEST-43-03-09  No import-time deprecation warnings
# ===================================================================


class TestNoImportTimeWarnings:

    def test_no_warnings_on_import(self):
        """Importing sinks module does not emit deprecation warnings."""
        import importlib

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Re-import the module (forces fresh module-level execution).
            import deskaoy.tracing.sinks as sinks_mod
            importlib.reload(sinks_mod)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) == 0, (
                f"No import-time warnings expected, got: {dep_warnings}"
            )


# ===================================================================
# TEST-43-03-10  Runtime + JSONL integration
# ===================================================================


class TestRuntimeJSONLIntegration:

    def test_spans_in_jsonl_file(self, tmp_path):
        """Spans appear in JSONL file when wired via TelemetryRuntime."""
        jsonl_path = tmp_path / "trace.jsonl"
        jsonl_exporter = JSONLExporter(jsonl_path)

        cfg = TelemetryConfig()
        rt = TelemetryRuntime(cfg)
        rt.tracer_provider.add_span_processor(
            SimpleSpanProcessor(jsonl_exporter)
        )

        tracer = rt.tracer()
        with tracer.start_as_current_span("integration.test") as span:
            span.set_attribute("test_key", "test_value")

        rt.force_flush(timeout_ms=5000)
        jsonl_exporter.shutdown()

        assert jsonl_path.exists()
        lines = [
            l for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            if l.strip()
        ]
        assert len(lines) >= 1, f"Expected >= 1 line in JSONL, got {len(lines)}"
        parsed = json.loads(lines[0])
        assert "name" in parsed


# ===================================================================
# TEST-43-03-11  Runtime + SQLite integration
# ===================================================================


class TestRuntimeSQLiteIntegration:

    def test_spans_in_session_db(self, tmp_path):
        """Spans appear in SessionDB when wired via TelemetryRuntime."""
        db_path = tmp_path / "test.db"
        sqlite_exporter = SQLiteExporter(db_path, batch_size=1, max_queue=128)

        cfg = TelemetryConfig()
        rt = TelemetryRuntime(cfg)
        rt.tracer_provider.add_span_processor(
            SimpleSpanProcessor(sqlite_exporter)
        )

        tracer = rt.tracer()
        with tracer.start_as_current_span("integration.sqlite") as span:
            span.set_attribute("test_key", "test_value")

        rt.force_flush(timeout_ms=5000)
        sqlite_exporter.force_flush(5000)
        sqlite_exporter.shutdown()

        conn = sqlite3.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
            assert count >= 1, f"Expected >= 1 event in SessionDB, got {count}"
        finally:
            conn.close()
