"""RedactingExporter — wrapper that redacts secrets before delegating.

Does NOT mutate OTel span internals — creates redacted copies of the
span attributes dict and passes them to the delegate exporter.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

# Default patterns that match common secret formats.
_DEFAULT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"Bearer\s+\S+", "Bearer [REDACTED]"),
    (r"Basic\s+\S+", "Basic [REDACTED]"),
    (r"\bsk-[a-zA-Z0-9]{20,}\b", "sk-[REDACTED]"),
    (r"\bkey-[a-zA-Z0-9]{20,}\b", "key-[REDACTED]"),
    (r"\btoken[=:]\s*\S+", "token=[REDACTED]"),
    (r"\bsession_id[=:]\s*\S+", "session_id=[REDACTED]"),
)


class _RedactedSpan:
    """Lightweight wrapper around a ReadableSpan with redacted attributes.

    Only the ``attributes`` property is overridden; everything else
    delegates to the original span.  This avoids mutating OTel internals.
    """

    __slots__ = ("_span", "_redacted_attrs")

    def __init__(self, span: ReadableSpan, redacted_attrs: dict[str, Any]) -> None:
        self._span = span
        self._redacted_attrs = redacted_attrs

    def __getattr__(self, name: str) -> Any:  # noqa: D105
        return getattr(self._span, name)

    @property
    def attributes(self) -> dict[str, Any]:  # type: ignore[override]
        return self._redacted_attrs


class RedactingExporter(SpanExporter):
    """Exporter wrapper that redacts secrets from span attributes.

    Parameters
    ----------
    delegate:
        The underlying exporter that receives redacted spans.
    patterns:
        Tuple of ``(regex, replacement)`` pairs applied to string-valued
        attributes.
    """

    def __init__(
        self,
        delegate: SpanExporter,
        patterns: tuple[tuple[str, str], ...] = _DEFAULT_PATTERNS,
    ) -> None:
        self._delegate = delegate
        self._patterns = [
            (re.compile(p, re.IGNORECASE), r) for p, r in patterns
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _redact_value(self, value: Any) -> Any:
        """Apply redaction patterns to a single attribute value."""
        if isinstance(value, str):
            for pattern, replacement in self._patterns:
                value = pattern.sub(replacement, value)
        return value

    def _redact_span(self, span: ReadableSpan) -> _RedactedSpan:
        """Create a redacted copy of *span* (non-mutating)."""
        original = dict(span.attributes or {})
        redacted = {k: self._redact_value(v) for k, v in original.items()}
        return _RedactedSpan(span, redacted)

    # ------------------------------------------------------------------
    # SpanExporter interface
    # ------------------------------------------------------------------

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Redact attributes then delegate."""
        redacted = [self._redact_span(s) for s in spans]
        return self._delegate.export(redacted)

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        """Delegate flush."""
        return self._delegate.force_flush(timeout_millis)

    def shutdown(self) -> None:
        """Delegate shutdown."""
        self._delegate.shutdown()
