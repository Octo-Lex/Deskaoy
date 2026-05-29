"""Trace sinks — abstract interface and concrete implementations."""

from __future__ import annotations

import asyncio
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deskaoy.tracing.types import SpanKind, TraceEvent

if TYPE_CHECKING:
    from deskaoy.tracing.session_db import SessionDB

import abc


class TraceSink(abc.ABC):

    @abc.abstractmethod
    async def emit(self, event: TraceEvent) -> None:
        ...

    @abc.abstractmethod
    async def flush(self) -> None:
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        ...


_LEVEL_ORDER: dict[SpanKind, int] = {
    SpanKind.CUSTOM: 0,
    SpanKind.SESSION: 1,
    SpanKind.CDP: 2,
    SpanKind.LLM: 3,
    SpanKind.PAGE: 4,
    SpanKind.ACTION: 5,
    SpanKind.ERROR: 6,
}


class ConsoleSink(TraceSink):

    def __init__(self, *, min_level: SpanKind = SpanKind.ACTION) -> None:
        warnings.warn(
            "ConsoleSink is deprecated. Use OTel ConsoleSpanExporter.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._min_level = _LEVEL_ORDER.get(min_level, 0)

    async def emit(self, event: TraceEvent) -> None:
        if _LEVEL_ORDER.get(event.span_kind, 0) >= self._min_level:
            line = f"[TRACE] {event.span_kind} {event.name} {event.duration_ms:.1f}ms {event.status}\n"
            sys.stderr.write(line)

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass


class FileSink(TraceSink):

    def __init__(self, path: Path, *, buffer_size: int = 100) -> None:
        warnings.warn(
            "FileSink is deprecated. Use OTel JSONLExporter.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._path = path
        self._buffer_size = buffer_size
        self._buffer: list[str] = []
        self._file: Any = None

    def _ensure_open(self) -> None:
        if self._file is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115

    async def emit(self, event: TraceEvent) -> None:
        self._ensure_open()
        self._buffer.append(event.to_json())
        if len(self._buffer) >= self._buffer_size:
            await self.flush()

    def _write_lines(self, lines: list[str]) -> None:
        """Sync helper — writes buffered lines to disk."""
        for line in lines:
            self._file.write(line + "\n")
        self._file.flush()

    async def flush(self) -> None:
        if self._buffer and self._file is not None:
            lines = self._buffer[:]
            self._buffer.clear()
            await asyncio.to_thread(self._write_lines, lines)

    async def close(self) -> None:
        await self.flush()
        if self._file is not None:
            self._file.close()
            self._file = None


class SQLiteSink(TraceSink):

    def __init__(self, db: SessionDB) -> None:
        warnings.warn(
            "SQLiteSink is deprecated. Use OTel SQLiteExporter.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._db = db
        self._buffer: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self._buffer.append(event)
        if len(self._buffer) >= 50:
            await self.flush()

    async def flush(self) -> None:
        if self._buffer:
            events = self._buffer[:]
            self._buffer.clear()
            try:
                await asyncio.to_thread(self._db.insert_events, events)
            except Exception:
                # Fallback: if to_thread fails (e.g. SQLite thread restrictions),
                # do a synchronous insert. Better than losing events.
                self._db.insert_events(events)

    async def close(self) -> None:
        await self.flush()


class PrometheusSink(TraceSink):

    def __init__(
        self,
        *,
        port: int | None = None,
        start_server: bool = False,
    ) -> None:
        warnings.warn(
            "PrometheusSink is deprecated. Use OTel PrometheusExporter.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._available = False
        self._metrics: dict[str, Any] = {}
        try:
            from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

            self._registry = CollectorRegistry()

            self._metrics["cdp_calls"] = Counter(
                "sb_cdp_calls_total",
                "Total CDP calls",
                ["method"],
                registry=self._registry,
            )
            self._metrics["cdp_duration"] = Histogram(
                "sb_cdp_call_duration_seconds",
                "CDP call duration",
                registry=self._registry,
            )
            self._metrics["llm_tokens"] = Counter(
                "sb_llm_tokens_used",
                "LLM tokens used",
                ["model"],
                registry=self._registry,
            )
            self._metrics["actions"] = Counter(
                "sb_actions_total",
                "Actions by tier",
                ["tier"],
                registry=self._registry,
            )
            self._metrics["errors"] = Counter(
                "sb_errors_total",
                "Errors by category",
                ["category"],
                registry=self._registry,
            )
            self._metrics["active_sessions"] = Gauge(
                "sb_active_sessions",
                "Active sessions",
                registry=self._registry,
            )
            self._available = True

            if start_server and port is not None:
                from prometheus_client import start_http_server

                start_http_server(port, registry=self._registry)
        except ImportError:
            pass

    async def emit(self, event: TraceEvent) -> None:
        if not self._available:
            return
        if event.span_kind == SpanKind.CDP:
            self._metrics["cdp_calls"].labels(method=event.name).inc()
            self._metrics["cdp_duration"].observe(event.duration_ms / 1000)
        elif event.span_kind == SpanKind.LLM:
            model = event.attributes.get("model", "unknown")
            self._metrics["llm_tokens"].labels(model=model).inc(
                event.token_input + event.token_output
            )
        elif event.span_kind == SpanKind.ACTION:
            tier = event.attributes.get("tier", "unknown")
            self._metrics["actions"].labels(tier=tier).inc()
        elif event.span_kind == SpanKind.ERROR:
            category = event.attributes.get("category", "unknown")
            self._metrics["errors"].labels(category=category).inc()

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass
