"""Core result envelope, error types, enums, and factory functions."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ActionMethod(StrEnum):
    """Which interaction tier produced this result."""
    SELECTOR = "selector"
    COORDINATE = "coordinate"
    VISION = "vision"


class ErrorCategory(StrEnum):
    """Fixed taxonomy of error kinds for programmatic recovery."""
    TIMEOUT = "timeout"
    SELECTOR_NOT_FOUND = "selector_not_found"
    NAVIGATION = "navigation"
    SECURITY = "security"
    BROWSER_CRASH = "browser_crash"
    VALIDATION = "validation"
    CONTEXT_OVERFLOW = "context_overflow"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CompletionReason(StrEnum):
    """Why a delegated/composite action terminated."""
    SUCCESS = "success"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"
    CANCELLED = "cancelled"
    MAX_STEPS = "max_steps"


# ---------------------------------------------------------------------------
# Core Envelope
# ---------------------------------------------------------------------------

@dataclass
class ActionError:
    """Structured error with machine-readable code and LLM-consumable hint.

    The ``code`` field is a stable machine-readable identifier (e.g.
    ``"stale_ref"``, ``"ambiguous"``) that calling code can switch on.
    The ``hint`` field is a human/LLM-readable suggestion for recovery.
    """
    category: ErrorCategory
    message: str
    code: str = ""                    # machine-readable: "stale_ref", "not_found", "ambiguous"
    hint: str = ""                    # LLM-readable: "Re-run snapshot() to refresh element refs"
    candidates: list[str] = field(default_factory=list)  # alternative targets found
    matches_n: int = 0               # how many elements matched (for ambiguous)
    selector: str | None = None
    recoverable: bool = True
    retry_hint: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ActionError:
        d["category"] = ErrorCategory(d["category"])
        # Backward compat: old serializations lack the new fields
        d.setdefault("code", "")
        d.setdefault("hint", "")
        d.setdefault("candidates", [])
        d.setdefault("matches_n", 0)
        return cls(**d)


# ---------------------------------------------------------------------------
# Error code catalog — canonical codes + default hints
# ---------------------------------------------------------------------------

ERROR_CODES: dict[str, tuple[ErrorCategory, str]] = {
    "not_found":    (ErrorCategory.SELECTOR_NOT_FOUND, "Try snapshot() to see available elements"),
    "stale_ref":    (ErrorCategory.SELECTOR_NOT_FOUND, "Element changed since last snapshot. Try snapshot() to refresh"),
    "ambiguous":    (ErrorCategory.VALIDATION,        "Narrow target: use a more specific name or role prefix (e.g. button:Submit)"),
    "timeout":      (ErrorCategory.TIMEOUT,           "The app may be busy. Wait and retry"),
    "window_gone":  (ErrorCategory.BROWSER_CRASH,     "The window was closed. Re-launch the app"),
    "access_denied":(ErrorCategory.SECURITY,          "Action blocked by security policy"),
}


def make_error(code: str, message: str = "", **overrides: Any) -> ActionError:
    """Build an ActionError from a canonical error code.

    Looks up ``code`` in :data:`ERROR_CODES` for category + default hint.
    Any kwarg overrides the default (e.g. ``candidates=["btn1", "btn2"]``).
    """
    category, hint = ERROR_CODES.get(code, (ErrorCategory.UNKNOWN, ""))
    return ActionError(
        category=category,
        message=message or code,
        code=code,
        hint=hint,
        **overrides,
    )


@dataclass
class ResultMeta:
    trace_id: str
    duration_ms: float
    method: ActionMethod | None = None
    screenshot_hash: str | None = None
    token_cost: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.method is not None:
            d["method"] = str(self.method)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ResultMeta:
        if "method" in d and d["method"] is not None:
            d["method"] = ActionMethod(d["method"])
        return cls(**d)


@dataclass
class ActionResult:
    """Standard envelope for every browser action.

    Invariants:
      - ok=True  => error is None
      - ok=False => error is not None
      - meta is always present
    """
    ok: bool
    data: Any = None
    error: ActionError | None = None
    meta: ResultMeta = field(default_factory=lambda: ResultMeta(
        trace_id=str(uuid.uuid4()), duration_ms=0.0,
    ))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "data": _serialize_data(self.data),
            "error": self.error.to_dict() if self.error else None,
            "meta": self.meta.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ActionResult:
        meta = ResultMeta.from_dict(d["meta"])
        error = ActionError.from_dict(d["error"]) if d.get("error") else None
        return cls(ok=d["ok"], data=d.get("data"), error=error, meta=meta)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _resolve_trace_id() -> str:
    """Return trace_id from FlowLogger context, or a random UUID."""
    try:
        from deskaoy.tracing.flow_logger import _current_context
        ctx = _current_context.get()
        if ctx is not None:
            return ctx.trace_id
    except Exception:
        pass
    return str(uuid.uuid4())

def action_result(
    ok: bool,
    data: Any = None,
    error: ActionError | None = None,
    method: ActionMethod | None = None,
    screenshot_hash: str | None = None,
    token_cost: float = 0.0,
) -> ActionResult:
    """Convenience factory matching Hermes's jsonResult() pattern."""
    trace_id = _resolve_trace_id()
    return ActionResult(
        ok=ok, data=data, error=error,
        meta=ResultMeta(
            trace_id=trace_id, duration_ms=0.0,
            method=method, screenshot_hash=screenshot_hash,
            token_cost=token_cost,
        ),
    )


def timed_action_result(
    ok: bool,
    start_ns: float,
    data: Any = None,
    error: ActionError | None = None,
    method: ActionMethod | None = None,
    screenshot_hash: str | None = None,
    token_cost: float = 0.0,
) -> ActionResult:
    """Factory that computes duration from a monotonic start timestamp."""
    duration_ms = (time.monotonic() - start_ns) * 1000
    trace_id = _resolve_trace_id()
    return ActionResult(
        ok=ok, data=data, error=error,
        meta=ResultMeta(
            trace_id=trace_id, duration_ms=duration_ms,
            method=method, screenshot_hash=screenshot_hash,
            token_cost=token_cost,
        ),
    )


def _serialize_data(data: Any) -> Any:
    """Serialize typed result payloads for JSON output."""
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    try:
        from deskaoy.results.typed import TYPED_RESULT_TYPES
        if isinstance(data, TYPED_RESULT_TYPES):
            return asdict(data)
    except ImportError:
        pass
    return str(data)
