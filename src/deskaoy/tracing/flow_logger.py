"""FlowLogger — core tracing engine with contextvars propagation."""

from __future__ import annotations

import contextlib
import contextvars
import logging
import re
import uuid
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from deskaoy.tracing.sinks import TraceSink
from deskaoy.tracing.types import (
    SpanKind,
    SpanStatus,
    TraceContext,
    TraceEvent,
    TraceSpan,
)

logger = logging.getLogger(__name__)

_current_context: contextvars.ContextVar[TraceContext | None] = \
    contextvars.ContextVar("sb_trace_context", default=None)


class FlowLogger:

    def __init__(
        self,
        sinks: list[TraceSink] | None = None,
        *,
        runtime: Any = None,
        max_events_per_trace: int = 10_000,
        redact_patterns: tuple[str, ...] = (
            "password", "token", "key", "secret", "credential",
        ),
    ) -> None:
        self._sinks = sinks or []
        if sinks:
            warnings.warn(
                "FlowLogger(sinks=[...]) is deprecated. Use TelemetryRuntime.",
                DeprecationWarning,
                stacklevel=2,
            )
        self._runtime = runtime  # TelemetryRuntime | None — None = legacy behavior
        self._max_events = max_events_per_trace
        self._redact_patterns = redact_patterns
        self._events: dict[str, list[TraceEvent]] = {}
        self._dropped_events: int = 0  # M19: track silently dropped events

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for sink in self._sinks:
            try:
                await sink.flush()
                await sink.close()
            except Exception:
                pass

    def trace(self, session_id: str) -> TraceScope:
        return TraceScope(self, session_id)

    def span(
        self,
        kind: SpanKind,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> SpanScope:
        return SpanScope(self, kind, name, attributes)

    async def emit_event(
        self,
        kind: SpanKind,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
        duration_ms: float = 0.0,
        status: SpanStatus = SpanStatus.OK,
    ) -> None:
        ctx = _current_context.get()
        if ctx is None:
            return
        step_id = ctx.next_step()
        event = TraceEvent(
            trace_id=ctx.trace_id,
            step_id=step_id,
            span_id=str(uuid.uuid4()),
            span_kind=kind,
            name=name,
            duration_ms=duration_ms,
            status=status,
            parent_span_id=ctx.current_span_id,
            session_id=ctx.session_id,
            attributes=self._redact(attributes or {}),
        )
        self._store_event(event)
        await self._fan_out(event)

    @staticmethod
    def current_context() -> TraceContext | None:
        return _current_context.get()

    @staticmethod
    def resolve_reentry_context(stored: TraceContext) -> TraceContext | None:
        current = _current_context.get()
        if current is None:
            return stored
        if stored is None:
            return current
        if stored.depth > current.depth:
            return stored
        return current

    def enrich_result(self, meta: dict[str, Any]) -> dict[str, Any]:
        ctx = _current_context.get()
        if ctx:
            meta["trace_id"] = ctx.trace_id
            meta["step_id"] = ctx.step_id
        return meta

    async def query_events(
        self,
        trace_id: str,
        *,
        span_kind: SpanKind | None = None,
        status: SpanStatus | None = None,
    ) -> list[TraceEvent]:
        events = self._events.get(trace_id, [])
        result = events
        if span_kind is not None:
            result = [e for e in result if e.span_kind == span_kind]
        if status is not None:
            result = [e for e in result if e.status == status]
        return result

    async def export_trajectory(self, trace_id: str, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{trace_id}.jsonl"
        events = self._events.get(trace_id, [])
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(event.to_json() + "\n")
        return path

    async def _fan_out(self, event: TraceEvent) -> None:
        for sink in self._sinks:
            with contextlib.suppress(Exception):
                await sink.emit(event)

    def _store_event(self, event: TraceEvent) -> None:
        events = self._events.setdefault(event.trace_id, [])
        if len(events) < self._max_events:
            events.append(event)
        else:
            self._dropped_events += 1
            if self._dropped_events <= 3 or self._dropped_events % 100 == 0:
                logger.warning(
                    "Trace event dropped (cap=%d, dropped=%d): %s",
                    self._max_events, self._dropped_events, event.name,
                )

    @property
    def dropped_event_count(self) -> int:
        """M19: Number of events silently dropped at cap."""
        return self._dropped_events

    def _redact(self, attributes: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for k, v in attributes.items():
            if isinstance(v, str):
                v = self._redact_string(v)
                v = self._redact_secrets(v)
            elif isinstance(v, dict):
                v = self._redact(v)
            result[k] = v
        return result

    # Patterns that match common secret formats in header values / strings.
    _SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"Bearer\s+\S+", "Bearer [REDACTED]"),
        (r"Basic\s+\S+", "Basic [REDACTED]"),
        (r"\bsk-[a-zA-Z0-9]{20,}\b", "sk-[REDACTED]"),
        (r"\bkey-[a-zA-Z0-9]{20,}\b", "key-[REDACTED]"),
        (r"\btoken[=:]\s*\S+", "token=[REDACTED]"),
        (r"\bsession_id[=:]\s*\S+", "session_id=[REDACTED]"),
    )

    def _redact_secrets(self, s: str) -> str:
        """Redact secret patterns like Bearer tokens and API keys."""
        import re as _re
        for pattern, replacement in self._SECRET_PATTERNS:
            s = _re.sub(pattern, replacement, s, flags=_re.IGNORECASE)
        return s

    def _redact_string(self, s: str) -> str:
        if "://" not in s:
            return s
        try:
            parsed = urlparse(s)
            if not parsed.query:
                return s
            params = parse_qs(parsed.query, keep_blank_values=True)
            redacted_keys = set()
            for key in list(params.keys()):
                for pattern in self._redact_patterns:
                    if re.search(pattern, key, re.IGNORECASE):
                        redacted_keys.add(key)
                        break
            if not redacted_keys:
                return s
            clean_params = {k: v for k, v in params.items() if k not in redacted_keys}
            new_query = urlencode(clean_params, doseq=True)
            return urlunparse(parsed._replace(query=new_query))
        except Exception:
            return s


class TraceScope:

    def __init__(self, logger: FlowLogger, session_id: str) -> None:
        self._logger = logger
        self._session_id = session_id
        self._token: Any | None = None
        self._trace_id = ""
        self._otel_cm: Any | None = None  # OTel span context manager
        self._otel_span: Any | None = None  # OTel Span

    async def __aenter__(self) -> TraceContext:
        if self._logger._runtime is not None:
            tracer = self._logger._runtime.tracer()
            self._otel_cm = tracer.start_as_current_span("session.start")
            self._otel_span = self._otel_cm.__enter__()
            span_context = self._otel_span.get_span_context()
            trace_id = format(span_context.trace_id, '032x')
        else:
            trace_id = str(uuid.uuid4())
        self._trace_id = trace_id
        ctx = TraceContext(trace_id=trace_id, session_id=self._session_id)
        self._token = _current_context.set(ctx)
        await self._logger.emit_event(
            SpanKind.SESSION, "session.start",
            attributes={"session_id": self._session_id},
        )
        return ctx

    async def __aexit__(self, *exc: Any) -> None:
        await self._logger.emit_event(
            SpanKind.SESSION, "session.end",
            attributes={"session_id": self._session_id},
        )
        if self._token is not None:
            _current_context.reset(self._token)
        if self._otel_cm is not None:
            self._otel_cm.__exit__(exc[0], exc[1], exc[2])


class SpanScope:

    def __init__(
        self,
        logger: FlowLogger,
        kind: SpanKind,
        name: str,
        attributes: dict[str, Any] | None,
    ) -> None:
        self._logger = logger
        self._kind = kind
        self._name = name
        self._attributes = attributes
        self._span: TraceSpan | None = None
        self._token: Any | None = None
        self._otel_cm: Any | None = None  # OTel span context manager
        self._otel_span: Any | None = None  # OTel Span

    async def __aenter__(self) -> TraceSpan:
        ctx = _current_context.get()
        span_id = str(uuid.uuid4())
        parent_id = ctx.current_span_id if ctx else None
        trace_id = ctx.trace_id if ctx else str(uuid.uuid4())
        session_id = ctx.session_id if ctx else None

        self._span = TraceSpan(
            span_id=span_id,
            trace_id=trace_id,
            span_kind=self._kind,
            name=self._name,
            parent_span_id=parent_id,
            session_id=session_id,
            attributes=self._attributes or {},
        )
        self._span.start()

        # OTel path: create real OTel span when runtime is provided
        if self._logger._runtime is not None:
            tracer = self._logger._runtime.tracer()
            otel_name = f"deskaoy.{self._kind}.{self._name}"
            self._otel_cm = tracer.start_as_current_span(otel_name)
            self._otel_span = self._otel_cm.__enter__()
            if self._attributes:
                redacted = self._logger._redact(self._attributes)
                for k, v in redacted.items():
                    if isinstance(v, (bool, int, float, str)):
                        self._otel_span.set_attribute(k, v)
                    else:
                        self._otel_span.set_attribute(k, str(v))

        if ctx:
            ctx.push_span(span_id)
            new_ctx = TraceContext(
                trace_id=ctx.trace_id,
                step_id=ctx.step_id,
                span_stack=list(ctx.span_stack),
                session_id=ctx.session_id,
            )
            self._token = _current_context.set(new_ctx)

        return self._span

    async def __aexit__(self, *exc: Any) -> None:
        if self._span is None:
            return

        status = SpanStatus.ERROR if exc[0] is not None else SpanStatus.OK
        if exc[0] is not None:
            error = exc[1] if exc[1] is not None else exc[0]()
            self._span.set_error(error)
        event = self._span.end(status)

        ctx = _current_context.get()
        if ctx:
            event.step_id = ctx.next_step()
        event.attributes = self._logger._redact(event.attributes)

        self._logger._store_event(event)
        await self._logger._fan_out(event)

        # OTel: set error status if needed, then end span
        if self._otel_cm is not None:
            if exc[0] is not None and self._otel_span is not None:
                from opentelemetry.trace import StatusCode
                error_msg = str(exc[1]) if exc[1] is not None else ""
                self._otel_span.set_status(StatusCode.ERROR, error_msg)
                if exc[1] is not None:
                    self._otel_span.record_exception(exc[1])
            self._otel_cm.__exit__(exc[0], exc[1], exc[2])

        if ctx:
            ctx.pop_span()
        if self._token is not None:
            _current_context.reset(self._token)

    def set_error(self, error: Exception) -> None:
        if self._span:
            self._span.set_error(error)
