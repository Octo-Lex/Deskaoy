"""Tests for FlowLogger OTel integration (BATCH-43 / TASK-02).

TEST-43-02-01 through TEST-43-02-07.
TEST-43-02-08 is verified by running the existing 34 tests unmodified.
"""

from __future__ import annotations

import asyncio
import re

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from deskaoy.tracing.flow_logger import FlowLogger, _current_context
from deskaoy.tracing.runtime import TelemetryConfig, TelemetryRuntime
from deskaoy.tracing.types import SpanKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime():
    """Create a TelemetryRuntime with InMemorySpanExporter for testing."""
    cfg = TelemetryConfig()
    rt = TelemetryRuntime(cfg)
    exporter = InMemorySpanExporter()
    rt.tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    return rt, exporter


# ===================================================================
# TEST-43-02-01  FlowLogger with runtime creates OTel span
# ===================================================================


class TestOTelSpanCreation:

    def test_runtime_creates_otel_span(self):
        """InMemoryExporter has at least 1 span when runtime is provided."""
        rt, exporter = _make_runtime()
        logger = FlowLogger(runtime=rt)

        async def _test():
            async with logger.trace("s1"):
                pass
            rt.force_flush()

        asyncio.run(_test())
        spans = exporter.get_finished_spans()
        assert len(spans) >= 1, f"Expected >= 1 span, got {len(spans)}"

    def test_span_name_is_session_start(self):
        """The root OTel span is named 'session.start'."""
        rt, exporter = _make_runtime()
        logger = FlowLogger(runtime=rt)

        async def _test():
            async with logger.trace("s1"):
                pass
            rt.force_flush()

        asyncio.run(_test())
        spans = exporter.get_finished_spans()
        session_spans = [s for s in spans if s.name == "session.start"]
        assert len(session_spans) >= 1, "Expected a 'session.start' span"


# ===================================================================
# TEST-43-02-02  FlowLogger without runtime unchanged
# ===================================================================


class TestLegacyUnchanged:

    def test_trace_id_is_uuid_format_without_runtime(self):
        """Without runtime, trace_id is UUID format (36 chars with dashes)."""
        logger = FlowLogger()

        async def _test():
            async with logger.trace("s1") as ctx:
                trace_id = ctx.trace_id
            return trace_id

        trace_id = asyncio.run(_test())
        # UUID v4 format: 8-4-4-4-12 with dashes = 36 chars
        assert len(trace_id) == 36, f"Expected 36-char UUID, got {len(trace_id)}"
        assert "-" in trace_id, "UUID should contain dashes"

    def test_sinks_still_work_without_runtime(self):
        """FlowLogger(sinks=[...]) still works (backward compat)."""
        from deskaoy.tracing.sinks import TraceSink

        collected: list = []

        class Collector(TraceSink):
            async def emit(self, event):
                collected.append(event)

            async def flush(self):
                pass

            async def close(self):
                pass

        logger = FlowLogger(sinks=[Collector()])

        async def _test():
            async with logger.trace("s1"):
                await logger.emit_event(SpanKind.CUSTOM, "test")

        asyncio.run(_test())
        assert len(collected) >= 1, "Sink should have received events"


# ===================================================================
# TEST-43-02-03  trace_id is hex when runtime active
# ===================================================================


class TestHexTraceId:

    def test_trace_id_is_hex_with_runtime(self):
        """With runtime, trace_id is 32-char hex (no dashes)."""
        rt, exporter = _make_runtime()
        logger = FlowLogger(runtime=rt)

        async def _test():
            async with logger.trace("s1") as ctx:
                return ctx.trace_id

        trace_id = asyncio.run(_test())
        assert re.match(r"^[0-9a-f]{32}$", trace_id), (
            f"Expected 32-char hex trace_id, got: {trace_id}"
        )


# ===================================================================
# TEST-43-02-04  Span error sets OTel ERROR status
# ===================================================================


class TestSpanErrorStatus:

    def test_error_sets_otel_error_status(self):
        """When a span raises, OTel span status is ERROR."""
        rt, exporter = _make_runtime()
        logger = FlowLogger(runtime=rt)

        async def _test():
            async with logger.trace("s1"):
                try:
                    async with logger.span(SpanKind.ACTION, "fail"):
                        raise RuntimeError("boom")
                except RuntimeError:
                    pass
            rt.force_flush()

        asyncio.run(_test())
        spans = exporter.get_finished_spans()
        # Find the 'deskaoy.action.fail' span
        error_spans = [
            s for s in spans if s.name == "deskaoy.action.fail"
        ]
        assert len(error_spans) == 1, f"Expected 1 error span, found {len(error_spans)}"
        assert error_spans[0].status.status_code == StatusCode.ERROR, (
            f"Expected ERROR status, got {error_spans[0].status.status_code}"
        )


# ===================================================================
# TEST-43-02-05  FlowLogger.events still populated with runtime
# ===================================================================


class TestEventsBuffer:

    def test_events_populated_with_runtime(self):
        """FlowLogger.events buffer still works when runtime is provided."""
        rt, exporter = _make_runtime()
        logger = FlowLogger(runtime=rt)

        async def _test():
            async with logger.trace("s1"), logger.span(SpanKind.ACTION, "click"):
                pass

        asyncio.run(_test())
        # Check internal events dict has entries
        total_events = sum(len(evts) for evts in logger._events.values())
        assert total_events > 0, "Events buffer should be populated"


# ===================================================================
# TEST-43-02-06  current_context works with runtime
# ===================================================================


class TestCurrentContext:

    def test_current_context_returns_trace_context_with_runtime(self):
        """current_context() returns TraceContext when runtime is active."""
        rt, exporter = _make_runtime()
        logger = FlowLogger(runtime=rt)

        async def _test():
            async with logger.trace("s1") as ctx:
                inside = FlowLogger.current_context()
                assert inside is not None
                assert isinstance(inside, type(ctx))
                assert inside.trace_id == ctx.trace_id
                assert inside.session_id == "s1"

        asyncio.run(_test())

    def test_current_context_cleared_after_trace_with_runtime(self):
        """current_context() is None after trace scope exits."""
        rt, exporter = _make_runtime()
        logger = FlowLogger(runtime=rt)

        async def _test():
            async with logger.trace("s1"):
                assert _current_context.get() is not None
            assert _current_context.get() is None

        asyncio.run(_test())


# ===================================================================
# TEST-43-02-07  Redaction preserved with runtime
# ===================================================================


class TestRedactionWithRuntime:

    def test_redacted_attributes_on_otel_span(self):
        """Sensitive keys are redacted from OTel span attributes."""
        rt, exporter = _make_runtime()
        logger = FlowLogger(runtime=rt)

        async def _test():
            async with logger.trace("s1"), logger.span(
                SpanKind.ACTION,
                "login",
                attributes={
                    "url": "https://example.com?password=secret123&user=alice",
                    "normal_field": "visible",
                },
            ):
                pass
            rt.force_flush()

        asyncio.run(_test())
        spans = exporter.get_finished_spans()
        action_spans = [
            s for s in spans if s.name == "deskaoy.action.login"
        ]
        assert len(action_spans) == 1
        span = action_spans[0]
        attrs = dict(span.attributes or {})
        # "password" query param should be redacted from URL
        url_val = attrs.get("url", "")
        assert "password" not in url_val, (
            f"Expected password redacted, got url={url_val}"
        )
        assert "user=alice" in url_val, f"Expected user=alice in url, got {url_val}"
        assert attrs.get("normal_field") == "visible"
