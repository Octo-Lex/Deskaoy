# v0.13: det-acp Adoption — Evidence Ledger + Session Budgets + Policy Evolution

> **v0.12.1 → v0.13.0** | ~9h | 3 workstreams
> **Source:** `C:\Next AI\ref\deterministic-agent-control-protocol-main`

---

## Why

Our `TraceBridge` is **in-memory only** — no persistence, no tamper evidence, no replay. If the process crashes, all trace data is lost. Our `PolicyBridge` is **static** — deny is final, no learning from denials. And our rate limiting is **per-action** only, with no session-level budgets or escalation.

det-acp solves all three with production-grade patterns: SHA-256 chained evidence ledgers, session budget tracking with escalation, and a self-evolving policy suggestion engine.

---

## Current State

| Component | What We Have | Gap |
|-----------|-------------|-----|
| Trace | `TraceBridge` — in-memory `list[ActionSpan]`, no persistence | No disk persistence, no tamper evidence, no integrity verification |
| Policy | `PolicyBridge` — DENY/ASK/ALLOW_DRY_RUN_ONLY, static rules | No learning from denials, no suggestion engine |
| Rate Limiting | `ActionRateGovernor` — per-action sliding window | No session-level budgets (max_actions, max_denials), no escalation |

---

## Workstream A: Evidence Ledger (~3h)

**New file:** `src/agent_core/safety/evidence_ledger.py` (~160 lines)

Append-only JSONL log with SHA-256 hash chaining. Every DesktopAgent action produces an immutable record. Each entry's hash includes the previous entry's hash, forming a tamper-evident chain.

**Design (from det-acp `ledger.ts`):**

```python
GENESIS_HASH = "sha256:" + "0" * 64

@dataclass
class LedgerEntry:
    seq: int                    # Monotonically increasing
    ts: str                     # ISO timestamp
    hash: str                   # sha256(seq|ts|prev|type|json(data))
    prev: str                   # Previous entry's hash
    session_id: str
    event_type: str             # "action:start", "action:result", "gate:requested", etc.
    data: dict                  # Event payload

class EvidenceLedger:
    def __init__(self, file_path: Path): ...
    async def init(self) -> None: ...           # Create/open file, resume chain
    async def append(self, session_id: str, event_type: str, data: dict) -> LedgerEntry: ...
    def read_all(self) -> list[LedgerEntry]: ...
    def verify_integrity(self) -> IntegrityReport: ...
    def get_seq(self) -> int: ...
    def get_last_hash(self) -> str: ...
    async def close(self) -> None: ...

@dataclass
class IntegrityReport:
    valid: bool
    total_entries: int
    first_seq: int
    last_seq: int
    broken_at: Optional[int]
    error: Optional[str]
```

**Wire into:** `DesktopAgent._execute_single_action()` and `_execute_automate()` — append entries at:
- `action:evaluate` (before dispatch)
- `action:result` (after adapter call)
- `gate:requested` / `gate:resolved` (if policy gate triggered)

Also wire into `TraceBridge.emit()` — when ledger is configured, append trace spans as ledger entries.

**Storage:** One JSONL file per session in `{AIOS_HOME}/ledgers/{session_id}.jsonl`

**Tests (~15):**
- Init creates file
- Append writes entry
- Hash chain is correct (entry N hash includes entry N-1 hash)
- Genesis hash for first entry
- Resume from existing file preserves chain
- Read all entries
- Integrity verification passes for clean chain
- Integrity verification detects tampering (modified entry)
- Integrity verification detects missing entry
- Verify integrity on empty ledger
- Concurrent appends are safe (file lock)
- Close and reopen preserves state
- Multiple sessions write to separate files
- Entry serialization round-trip
- Large number of entries (1000+) performance

---

## Workstream B: Session Budgets + Escalation (~3h)

**New file:** `src/agent_core/safety/session_budget.py` (~120 lines)

Session-level budget tracking with escalation rules. Goes beyond per-action rate limiting to track cumulative session state.

**Design (from det-acp `session.ts` BudgetTracker):**

```python
@dataclass
class SessionBudget:
    """Tracks cumulative resource usage within a session."""
    session_id: str
    started_at: float = field(default_factory=time.monotonic)
    actions_evaluated: int = 0
    actions_allowed: int = 0
    actions_denied: int = 0
    actions_gated: int = 0
    cost_usd: float = 0.0
    total_duration_ms: float = 0.0
    retries: int = 0

@dataclass
class SessionLimits:
    """Hard limits for a session."""
    max_actions: int = 100        # Max total actions per session
    max_denials: int = 10         # Max denials before auto-terminate
    max_cost_usd: float = 1.0     # Max cumulative cost
    max_duration_ms: float = 1800_000  # 30 minutes
    escalation_after_actions: int = 50  # Require human check-in after N actions

@dataclass
class EscalationEvent:
    """Triggered when session crosses a threshold."""
    session_id: str
    threshold: str     # "max_actions", "max_denials", "escalation"
    current_value: Any
    limit_value: Any
    timestamp: float

class SessionBudgetTracker:
    def __init__(self, limits: SessionLimits): ...
    def check(self, budget: SessionBudget) -> list[EscalationEvent]: ...  # Check thresholds
    def record_action(self, budget: SessionBudget, allowed: bool, duration_ms: float, cost_usd: float = 0.0) -> None: ...
    def snapshot(self, budget: SessionBudget) -> dict: ...
    def should_terminate(self, budget: SessionBudget) -> tuple[bool, str]: ...
    def should_escalate(self, budget: SessionBudget) -> bool: ...
```

**Wire into:** `DesktopAgent.execute()` — create `SessionBudget` at start of execution, pass through `_execute_single_action()` and `_execute_automate()`, check limits before each action.

`should_terminate()` returns `(True, reason)` when max_actions or max_denials or max_cost or max_duration is exceeded — agent returns `RATE_LIMITED` or `FAILURE` immediately.

`should_escalate()` returns `True` when escalation threshold is hit — logged as WARNING, potentially triggers human check-in (future: AI-OS notification).

**Tests (~14):**
- Budget tracks actions_evaluated
- Budget tracks allowed/denied/gated counts
- Budget tracks cost and duration
- should_terminate on max_actions exceeded
- should_terminate on max_denials exceeded
- should_terminate on max_cost exceeded
- should_terminate on max_duration exceeded
- should_escalate triggers at threshold
- should_escalate doesn't trigger below threshold
- should_escalate triggers only once
- check returns escalation events
- snapshot includes all fields
- record_action updates counts correctly
- SessionLimits defaults are sensible

---

## Workstream C: Policy Self-Evolution (~3h)

**New file:** `src/agent_core/safety/policy_evolution.py` (~140 lines)

When a policy denial occurs, analyze the denial reason and propose a minimal policy change. User can approve (add to policy permanently) or allow-once (in-memory override) or deny (keep blocking).

**Design (from det-acp `evolution/suggestion.ts` + `types.ts`):**

```python
class DenialCategory(StrEnum):
    NO_CAPABILITY = "no_capability"
    SCOPE_VIOLATION = "scope_violation"
    FORBIDDEN_MATCH = "forbidden_match"
    BUDGET_EXCEEDED = "budget_exceeded"      # Not suggestible
    SESSION_CONSTRAINT = "session_constraint" # Not suggestible
    UNKNOWN = "unknown"

@dataclass
class PolicySuggestion:
    category: DenialCategory
    tool: str
    description: str          # Human-readable: 'Add "click" capability for path "/tmp"?'
    change: dict              # Type-specific change payload

class EvolutionDecision(StrEnum):
    ADD_TO_POLICY = "add_to_policy"   # Mutate policy + persist
    ALLOW_ONCE = "allow_once"         # In-memory override only
    DENY = "deny"                     # Keep blocking

@dataclass
class EvolutionResult:
    decision: EvolutionDecision
    suggestion: PolicySuggestion

EvolutionHandler = Callable[[PolicySuggestion], Awaitable[EvolutionDecision]]

class PolicyEvolutionEngine:
    def __init__(self, handler: Optional[EvolutionHandler] = None, timeout_ms: int = 30000): ...
    def suggest(self, action: str, reason: str, policy: Any) -> Optional[PolicySuggestion]: ...
    async def evolve(self, suggestion: PolicySuggestion) -> EvolutionResult: ...
    def apply_change(self, suggestion: PolicySuggestion, policy: Any) -> None: ...

def suggest_policy_change(action: str, reason: str) -> Optional[PolicySuggestion]:
    """Pattern-match denial reasons to propose policy changes.

    Maps denial reasons to one of:
    - Add capability for tool X
    - Widen scope (allow path/domain/pattern X)
    - Remove forbidden pattern X

    Budget/session violations are NOT suggestible.
    """
```

**Wire into:** `DesktopAgent._execute_single_action()` — after `policy_bridge.preflight()` returns DENY, call `suggest_policy_change()`. If suggestion exists and handler is configured, await handler decision. If `ADD_TO_POLICY`, apply change and retry.

**Denial reason patterns (from det-acp):**
- `"No capability defined for tool 'X'"` → `no_capability` → suggest add
- `"Action blocked by policy"` → parse policy_decision.reason → `scope_violation`
- `"Rate limited"` → `budget_exceeded` → NOT suggestible
- Unknown → `unknown` → NOT suggestible

**Tests (~14):**
- NO_CAPABILITY suggestion for unknown tool
- SCOPE_VIOLATION suggestion for blocked path
- BUDGET_EXCEEDED is not suggestible
- SESSION_CONSTRAINT is not suggestible
- Unknown reason is not suggestible
- EvolutionDecision.ADD_TO_POLICY applies change
- EvolutionDecision.ALLOW_ONCE applies in-memory only
- EvolutionDecision.DENY keeps blocking
- Timeout returns DENY
- Handler receives correct suggestion
- Multiple suggestions for different tools
- apply_change modifies policy correctly
- Suggestion description is human-readable
- Engine with no handler returns None

---

## Execution Order

```
Step 1: A — Evidence Ledger       (~3h)   Audit foundation
Step 2: B — Session Budgets        (~3h)   Runtime safety
Step 3: C — Policy Self-Evolution  (~3h)   Adaptive governance
Step 4: Wire all three into DesktopAgent + TraceBridge
Step 5: Full test suite → version bump
```

---

## Files Changed

| # | File | Action | Δ Lines |
|---|------|--------|---------|
| 1 | `src/agent_core/safety/evidence_ledger.py` | Create | ~160 |
| 2 | `src/agent_core/safety/session_budget.py` | Create | ~120 |
| 3 | `src/agent_core/safety/policy_evolution.py` | Create | ~140 |
| 4 | `src/agent_core/safety/__init__.py` | Edit | +6 |
| 5 | `src/agent_core/desktop_agent.py` | Edit: wire A–C | +50 |
| 6 | `src/agent_core/trace_bridge.py` | Edit: optional ledger | +20 |
| 7 | `tests/test_safety/test_evidence_ledger.py` | Create | ~150 |
| 8 | `tests/test_safety/test_session_budget.py` | Create | ~140 |
| 9 | `tests/test_safety/test_policy_evolution.py` | Create | ~140 |
| 10 | `pyproject.toml` | Edit: bump v0.13.0 | +1 |

## Expected Outcome

| Metric | Before (v0.12.1) | After (v0.13.0) |
|--------|-------------------|------------------|
| Tests | 2,139 | ~2,182 |
| Audit trail | In-memory only (lost on crash) | **SHA-256 chained JSONL ledger** |
| Session governance | Per-action rate limiting | **Session budgets + escalation** |
| Policy adaptation | Static (deny is final) | **Self-evolving with suggestions** |
| Tamper evidence | None | **Hash chain verification** |
