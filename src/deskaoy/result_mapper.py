"""Result mapper — map ActionResult to AI-OS result/evidence structures.

Deskaoy must never claim real-world completion when the action was
dry-run, blocked, failed, approval-required, partial, or uncertain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from deskaoy.results.types import ActionResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AI-OS result/evidence shape
# ---------------------------------------------------------------------------

@dataclass
class AIOSResult:
    """Mapped result for AI-OS consumption."""
    ok: bool
    status: str                # "success", "failure", "dry_run", "blocked", "partial"
    summary: str
    duration_ms: float
    confidence: float
    action_method: str         # "selector", "coordinate", "vision"
    error_code: str = ""
    error_category: str = ""
    error_hint: str = ""
    mutation_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    recovery_events: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual_recovery: str = ""
    trace_id: str = ""
    span_id: str = ""
    policy_decision_id: str = ""
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "duration_ms": self.duration_ms,
            "confidence": self.confidence,
            "action_method": self.action_method,
            "error_code": self.error_code,
            "error_category": self.error_category,
            "error_hint": self.error_hint,
            "mutation_refs": self.mutation_refs,
            "evidence_refs": self.evidence_refs,
            "recovery_events": self.recovery_events,
            "warnings": self.warnings,
            "manual_recovery": self.manual_recovery,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "policy_decision_id": self.policy_decision_id,
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------------
# Sensitive data redaction
# ---------------------------------------------------------------------------

_REDACT_PATTERNS = [
    ("password", "***REDACTED***"),
    ("secret", "***REDACTED***"),
    ("token", "***REDACTED***"),
    ("api_key", "***REDACTED***"),
    ("bearer", "***REDACTED***"),
]


def _redact_value(value: str) -> str:
    """Redact sensitive values in strings."""
    lower = value.lower()
    for pattern, replacement in _REDACT_PATTERNS:
        if pattern in lower:
            return replacement
    if len(value) > 200:
        return value[:200] + "...[truncated]"
    return value


# ---------------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------------

def map_action_result(
    result: ActionResult,
    *,
    dry_run: bool = False,
    trace_id: str = "",
    span_id: str = "",
    policy_decision_id: str = "",
) -> AIOSResult:
    """Map an internal ActionResult to an AI-OS result shape.

    Handles truthfulness rules:
    - dry_run=True → status is "dry_run", never "success"
    - ok=False → status is "failure", never "success"
    - Error hint is preserved for AI-OS recovery
    """
    method = str(result.meta.method) if result.meta.method else "unknown"

    # Determine truthful status
    if dry_run:
        status = "dry_run"
        ok_claim = False  # Never claim completion for dry runs
    elif result.ok:
        status = "success"
        ok_claim = True
    else:
        status = "failure"
        ok_claim = False

    # Build mapped result
    mapped = AIOSResult(
        ok=ok_claim,
        status=status,
        summary=_build_summary(result, dry_run),
        duration_ms=result.meta.duration_ms,
        confidence=0.0,
        action_method=method,
        dry_run=dry_run,
        trace_id=trace_id or result.meta.trace_id,
        span_id=span_id,
        policy_decision_id=policy_decision_id,
    )

    # Map error information
    if result.error:
        mapped.error_code = getattr(result.error, "code", "")
        mapped.error_category = str(result.error.category)
        mapped.error_hint = getattr(result.error, "hint", "")
        mapped.manual_recovery = result.error.retry_hint or ""

    # Map confidence from data
    if isinstance(result.data, dict):
        conf = result.data.get("visual_confidence", result.data.get("confidence"))
        if isinstance(conf, (int, float)):
            mapped.confidence = float(conf)

    return mapped


def _build_summary(result: ActionResult, dry_run: bool) -> str:
    """Build a truthful summary."""
    if dry_run:
        return f"Dry run: action would {'succeed' if result.ok else 'fail'}"
    if result.ok:
        return "Action completed successfully"
    msg = result.error.message if result.error else "Unknown error"
    return f"Action failed: {_redact_value(msg)}"
