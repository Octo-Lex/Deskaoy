"""AI-OS Platform Contract v2.2 — Shared Types.

All types from the PLATFORM_CONTRACT that citizens use.
Zero internal imports — these define the boundary between
the desktop agent and the AI Operating System.

Reference: PLATFORM_CONTRACT.md §Shared Types, §1–§4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

class OperationCancelled(Exception):
    """Raised by CancellationToken.check() when cancelled."""
    pass


class CancellationToken:
    """Cooperative cancellation token.

    The platform sets cancelled=True; the citizen checks periodically.
    """

    def __init__(self) -> None:
        self._cancelled: bool = False

    def is_cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        """Raise OperationCancelled if cancelled."""
        if self._cancelled:
            raise OperationCancelled()

    def cancel(self) -> None:
        self._cancelled = True


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ResultStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    NEEDS_REVIEW = "needs_review"
    DRY_RUN = "dry_run"
    RATE_LIMITED = "rate_limited"
    RETRYABLE = "retryable"
    EMPTY_RESULTS = "empty_results"
    CONFIG_ERROR = "config_error"


class RestoreMethod(StrEnum):
    RESTORE_STATE = "restore_state"
    DELETE_CREATED = "delete_created"
    COMPENSATE = "compensate"
    NONE = "none"


class IssueSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class ErrorCode(StrEnum):
    AUTH_REQUIRED = "auth_required"
    AUTH_EXPIRED = "auth_expired"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    NETWORK_ERROR = "network_error"
    PERMISSION_DENIED = "permission_denied"
    DEPENDENCY_MISSING = "dependency_missing"
    PROVIDER_ERROR = "provider_error"
    DOMAIN_VIOLATION = "domain_violation"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"
    BUDGET_EXCEEDED = "budget_exceeded"


# ---------------------------------------------------------------------------
# Structured Types
# ---------------------------------------------------------------------------

@dataclass
class Confidence:
    """Structured assessment of result quality.

    Measures trust in execution fidelity, not semantic correctness.
    Deterministic APIs MUST return 1.0.
    """
    score: float            # 0.0–1.0
    reason: str             # Human-readable explanation
    factors: dict = field(default_factory=dict)


@dataclass
class Issue:
    """Single structured type for all problems during execution."""
    severity: IssueSeverity
    code: ErrorCode
    message: str
    details: dict = field(default_factory=dict)
    retry_possible: bool = False
    retry_after_seconds: int = 0


# ---------------------------------------------------------------------------
# Mutation & Undo
# ---------------------------------------------------------------------------

@dataclass
class MutationRecord:
    """What changed during execution. One per mutated resource."""
    resource_type: str            # "desktop_window", "desktop_element"
    resource_id: str              # ID of the affected resource
    operation: str                # "create" | "update" | "delete" | "send" | "move"
    before_state: dict | None  # State before mutation (None for creation)
    after_state: dict | None   # State after mutation (None for deletion)
    restore_method: RestoreMethod
    state_version: str = ""


@dataclass
class Snapshot:
    """Platform-constructed from MutationRecord.

    Citizens NEVER construct Snapshot objects — they return
    MutationRecord and the platform wraps them.
    Included here so citizens can type-check undo signatures.
    """
    snapshot_id: str
    execution_id: str
    resource_type: str
    resource_id: str
    before_state: dict | None
    after_state: dict | None
    restore_method: RestoreMethod
    state_version: str
    created_at: str
    expires_at: str


@dataclass
class UndoResult:
    """Result of undo() or compensate()."""
    execution_id: str
    success: bool
    summary: str
    manual_instructions: str = ""
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Followups & Review
# ---------------------------------------------------------------------------

@dataclass
class SuggestedFollowup:
    """Structured recommendation for what to do next."""
    label: str
    agent: str
    capability: str
    params: dict = field(default_factory=dict)
    priority: str = "normal"
    action_class: str = ""


@dataclass
class ReviewItem:
    """Structured request for user judgment."""
    item: str
    reason: str
    severity: str              # "suggestion" | "warning" | "critical"
    options: list[dict] = field(default_factory=list)
    action_class: str = ""


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------

@dataclass
class Learning:
    """Things learned for future executions."""
    type: str                  # "preference" | "pattern" | "correction" | "observation"
    domain: str                # Must match one of agent's declared domains
    key: str                   # "desktop.preferred_app"
    value: Any                 # JSON-serializable
    confidence: float          # 0.0–1.0
    source: str                # "user_action" | "undo_pattern" | "explicit_feedback"
    expires_at: str = ""


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@dataclass
class ResourceRef:
    """Reference to a binary or large resource."""
    uri: str
    mime_type: str
    size_bytes: int
    filename: str = ""
    expires_at: str = ""


@dataclass
class PaginatedResult:
    """Standard envelope for list/search results."""
    items: list[dict]
    total_count: int | None
    has_more: bool
    cursor: str = ""
    page_size: int = 50


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@dataclass
class HealthCheckResult:
    """Result of headless app health check."""
    healthy: bool
    message: str = ""
    latency_ms: int = 0
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool Protocol Types
# ---------------------------------------------------------------------------

@dataclass
class ToolContext:
    """What a Tool receives from the platform."""
    execution_id: str
    idempotency_key: str
    task_id: str
    user_id: str
    session_id: str
    dry_run: bool
    timeout_seconds: int
    cancellation_token: CancellationToken
    client: Any = None           # ScopedClient or None
    autonomy_mode: str = "autopilot"
    locale: str = "en-US"
    timezone: str = "America/New_York"


@dataclass
class ToolResult:
    """What a Tool returns to the platform."""
    execution_id: str
    status: ResultStatus
    summary: str
    data: dict = field(default_factory=dict)
    artifacts: list[ResourceRef] = field(default_factory=list)
    mutations: list[MutationRecord] = field(default_factory=list)
    confidence: Confidence = field(default_factory=lambda: Confidence(score=0.0, reason="unset"))
    issues: list[Issue] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent Protocol Types
# ---------------------------------------------------------------------------

@dataclass
class AgentGoal:
    """What an Agent receives — high-level goal, not individual tool calls."""
    capability: str              # Which of the agent's capabilities to use
    params: dict = field(default_factory=dict)
    priority: str = "normal"     # "low" | "normal" | "high" | "urgent"
    parent_task_id: str = ""
    related_results: list[dict] = field(default_factory=list)
    user_preferences: dict = field(default_factory=dict)


@dataclass
class AgentContext:
    """Richer context for Agents (vs ToolContext)."""
    # Identity
    execution_id: str
    idempotency_key: str
    task_id: str
    user_id: str
    session_id: str
    # Execution
    dry_run: bool = False
    timeout_seconds: int = 60
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    # Auth
    client: Any = None
    additional_clients: dict = field(default_factory=dict)
    # Agent-specific
    user_memory: dict = field(default_factory=dict)
    recent_activity: list[dict] = field(default_factory=list)
    connected_services: dict = field(default_factory=dict)
    available_tools: list[str] = field(default_factory=list)
    autonomy_mode: str = "autopilot"
    max_cost: float = 0.0
    # User context
    locale: str = "en-US"
    timezone: str = "America/New_York"


@dataclass
class AgentResult:
    """What an Agent returns to the platform."""
    execution_id: str
    status: ResultStatus
    summary: str
    data: dict = field(default_factory=dict)
    artifacts: list[ResourceRef] = field(default_factory=list)
    mutations: list[MutationRecord] = field(default_factory=list)
    confidence: Confidence = field(default_factory=lambda: Confidence(score=0.0, reason="unset"))
    issues: list[Issue] = field(default_factory=list)
    needs_review: list[ReviewItem] = field(default_factory=list)
    suggested_followups: list[SuggestedFollowup] = field(default_factory=list)
    learnings: list[Learning] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentEstimate:
    """Pre-execution estimate for cost/time/confidence."""
    cost_usd: float
    latency_ms: int
    confidence: Confidence
    requires_auth: bool
    can_execute: bool
    refusal_reason: str = ""
    provider_healthy: bool = True
    degradation_note: str = ""
