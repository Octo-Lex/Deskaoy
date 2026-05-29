"""Trace bridge — emit action spans to AI-OS TraceService.

AI-OS TraceService is authoritative. Deskaoy logs are diagnostic.

Each action can report:
  trace_id, span_id, surface_id, window_id, action, target_description,
  action_method, tier_used, fallbacks_attempted, duration_ms, confidence,
  screenshot_hash, snapshot_ref, policy_decision_id, approval_id
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Span types
# ---------------------------------------------------------------------------

@dataclass
class ActionSpan:
    """A single action execution span for AI-OS TraceService."""
    trace_id: str = ""
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    surface_id: str = ""
    window_id: str = ""
    action: str = ""
    target_description: str = ""
    action_method: str = ""       # selector, coordinate, vision
    tier_used: int = 0            # 1=selector, 2=coordinate, 3=vision
    fallbacks_attempted: int = 0
    duration_ms: float = 0.0
    confidence: float = 0.0
    screenshot_hash: str = ""
    snapshot_ref: str = ""
    policy_decision_id: str = ""
    approval_id: str = ""
    ok: bool = True
    error_code: str = ""
    error_category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "surface_id": self.surface_id,
            "window_id": self.window_id,
            "action": self.action,
            "target_description": self.target_description,
            "action_method": self.action_method,
            "tier_used": self.tier_used,
            "fallbacks_attempted": self.fallbacks_attempted,
            "duration_ms": self.duration_ms,
            "confidence": self.confidence,
            "screenshot_hash": self.screenshot_hash,
            "snapshot_ref": self.snapshot_ref,
            "policy_decision_id": self.policy_decision_id,
            "approval_id": self.approval_id,
            "ok": self.ok,
            "error_code": self.error_code,
            "error_category": self.error_category,
        }


# ---------------------------------------------------------------------------
# Trace bridge
# ---------------------------------------------------------------------------

SpanEmitFn = Callable[[ActionSpan], Awaitable[None]]


class TraceBridge:
    """Integration point for AI-OS TraceService.

    When connected, emits action spans to AI-OS. When standalone,
    logs spans for diagnostic purposes only.
    """

    def __init__(
        self,
        *,
        emit_fn: SpanEmitFn | None = None,
    ) -> None:
        self._emit_fn = emit_fn
        self._diagnostic_spans: list[ActionSpan] = []

    @property
    def is_connected(self) -> bool:
        return self._emit_fn is not None

    async def emit(self, span: ActionSpan) -> None:
        """Emit an action span.

        If connected to AI-OS TraceService, delegates there.
        Otherwise, stores locally for diagnostics.
        """
        if self._emit_fn is not None:
            try:
                await self._emit_fn(span)
            except Exception as exc:
                logger.warning("Trace emit failed: %s", exc)
        else:
            self._diagnostic_spans.append(span)
            logger.debug(
                "Diagnostic span: action=%s ok=%s duration=%.1fms",
                span.action, span.ok, span.duration_ms,
            )

    @property
    def diagnostic_spans(self) -> list[ActionSpan]:
        """Return locally-stored diagnostic spans (standalone mode only)."""
        return list(self._diagnostic_spans)

    @property
    def span_count(self) -> int:
        """Number of spans emitted."""
        return len(self._diagnostic_spans)

    def clear_diagnostics(self) -> None:
        self._diagnostic_spans.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

trace_bridge = TraceBridge()
