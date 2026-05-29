BLUEPRINT
═══════════════════════════════════════════════════════════

Sprint / Batch ID:        BATCH-03
Blueprint Version:        1.0
Lead Programmer:          Lead AI Instance
Date Issued:              2026-04-26
Review SLA:               30 minutes
Execution SLA:            4 hours

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Introduce a RuntimeExecutionReceipt type that captures truthful execution
    metadata: attempt state, preflight result, obligations enforced, side effects,
    resource observations, and a hard-coded truth message
  - Introduce a RuntimeAttemptState enum with 7 states: pending, preflight_passed,
    running, completed, failed, cancelled, timed_out, blocked
  - Introduce a PolicyObligation enum with 5 obligations: dry_run_required,
    approval_required, quarantine_on_failure, sandbox_required, log_full_payload
  - Introduce an AdapterCapabilities dataclass that surface adapters use to
    declare what they support (filesystem, network, mouse, keyboard, screen_capture,
    accessibility_read, dry_run, sandboxing)
  - Introduce a RuntimePreflight service that performs a canonical 12-check preflight
    (desktop-relevant subset of B38's 28 checks) and produces a PreflightResult
    with a fingerprint hash
  - Introduce a RuntimeResourceBudget type with timeout_ms, max_output_bytes,
    and max_actions (network/memory guards are future — desktop runs locally)
  - Wire the preflight into DesktopAgent._execute_single_action() as a formal
    gate before dispatch, replacing the ad-hoc validation/policy/rate checks
  - Wire AdapterCapabilities into WindowsAdapter (declared on class)
  - Wire PolicyObligation enforcement: dry_run_required forces simulation,
    approval_required blocks without explicit approval, quarantine_on_failure
    triggers compensation engine
  - Wire attempt lifecycle: each execution gets a RuntimeAttempt record with
    state transitions, persisted in the evidence ledger
  - Wire RuntimeExecutionReceipt into AgentResult.data["receipt"]

What the code MUST NOT do:
  - Must NOT modify the AI-OS Platform Contract types in os_types.py (extend only)
  - Must NOT break any existing tests (backward compatibility)
  - Must NOT add new dependencies
  - Must NOT implement shell wrapper checks or cwd confinement (those are for
    code execution runtimes, not desktop bridge adapters)
  - Must NOT grant any adapter authority to bypass the preflight

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: Every execution path through _execute_single_action MUST produce a
         RuntimeExecutionReceipt. The receipt MUST contain a truth_message
         that accurately reflects what happened. The receipt MUST be attached
         to AgentResult.data["receipt"]. This is verified by test assertions.

  HB-02: Policy allow is NOT an execution guarantee. The preflight MUST check
         obligations after policy returns ALLOW. If obligations require dry_run
         and the request is not dry_run, execution MUST be blocked.

  HB-03: The preflight fingerprint MUST include: adapter capabilities hash,
         policy version, session state hash, and health status. If any of these
         change between preflight and execution, the execution MUST be blocked
         with reason "preflight_stale".

  HB-04: All existing tests MUST continue to pass. New types are additive —
         existing AgentResult/AgentGoal/AgentContext are unchanged. The new
         preflight is wired into _execute_single_action but must be compatible
         with existing call patterns.

  HB-05: RuntimeAttemptState is a strict state machine. An attempt can only
         transition forward: pending → preflight_passed → running → terminal.
         Skipping states or backward transitions MUST raise an error.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

RuntimeAttemptState(StrEnum):
  PENDING = "pending"
  PREFLIGHT_PASSED = "preflight_passed"
  RUNNING = "running"
  COMPLETED = "completed"
  FAILED = "failed"
  CANCELLED = "cancelled"
  TIMED_OUT = "timed_out"
  BLOCKED = "blocked"

PolicyObligation(StrEnum):
  DRY_RUN_REQUIRED = "dry_run_required"
  APPROVAL_REQUIRED = "approval_required"
  QUARANTINE_ON_FAILURE = "quarantine_on_failure"
  SANDBOX_REQUIRED = "sandbox_required"
  LOG_FULL_PAYLOAD = "log_full_payload"

AdapterCapabilities:
  supports_mouse: bool = True
  supports_keyboard: bool = True
  supports_screen_capture: bool = True
  supports_accessibility_read: bool = True
  supports_filesystem: bool = False
  supports_network: bool = False
  supports_dry_run: bool = True
  supports_sandboxing: bool = False
  adapter_id: str = ""
  adapter_version: str = ""

RuntimeResourceBudget:
  timeout_ms: int = 60000
  max_output_bytes: int = 1048576  # 1MB
  max_actions: int = 100

RuntimeExecutionReceipt:
  execution_id: str
  attempt_id: str
  attempt_state: RuntimeAttemptState
  truth_message: str
  runtime_execution_performed: bool
  simulated: bool
  dry_run: bool
  side_effects_performed: bool
  preflight_passed: bool
  preflight_fingerprint: str = ""
  obligations_checked: list[str] = []
  obligations_blocked: list[str] = []
  resource_budget: RuntimeResourceBudget | None = None
  timestamp: float = 0.0

PreflightCheck:
  check_id: str
  name: str
  passed: bool
  message: str

PreflightResult:
  passed: bool
  checks: list[PreflightCheck]
  fingerprint: str  # SHA-256 hash of state
  obligations_required: list[PolicyObligation]
  blocked_reason: str = ""

RuntimePreflight:
  12 checks:
    CHK-PF-01: adapter_available — surface adapter is connected
    CHK-PF-02: adapter_capabilities_declared — capabilities registered
    CHK-PF-03: capability_supported — requested action is in adapter capabilities
    CHK-PF-04: policy_checked — policy bridge has returned a decision
    CHK-PF-05: policy_allowed — policy decision is not DENY
    CHK-PF-06: obligations_satisfied — all required obligations are met
    CHK-PF-07: dry_run_consistent — if dry_run_required, request is dry_run
    CHK-PF-08: rate_within_limit — rate governor allows the action
    CHK-PF-09: session_budget_available — session budget not exhausted
    CHK-PF-10: health_check_passed — adapter health is OK
    CHK-PF-11: resource_budget_set — resource budget is defined
    CHK-PF-12: no_raw_secrets — no raw secrets in request params

RuntimeAttempt:
  attempt_id: str
  execution_id: str
  state: RuntimeAttemptState
  preflight_result: PreflightResult | None
  receipt: RuntimeExecutionReceipt | None
  created_at: float
  updated_at: float

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────

  AUTH-01: First-party status does NOT bypass runtime gates. Even DesktopAgent's
           own actions go through the preflight.

  AUTH-02: Adapters are providers, not arbiters. An adapter declaring
           supports_sandboxing=False does NOT block low-risk actions.
           It only blocks actions that require sandboxing.

  AUTH-03: The truth_message in the receipt is auto-generated and MUST NOT be
           overridden by the adapter. It is derived from the attempt state.

  AUTH-04: Receipts are immutable after creation. No field may be modified
           after the receipt is produced.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────

  DEP-01: BATCH-01 (CLI) ✅
  DEP-02: DesktopAgent._execute_single_action() ✅
  DEP-03: PolicyBridge.preflight() ✅
  DEP-04: ActionRateGovernor ✅
  DEP-05: SessionBudgetTracker ✅
  DEP-06: HealthCheck ✅
  DEP-07: EvidenceLedger ✅
  DEP-08: CompensationEngine ✅
  DEP-09: WindowsAdapter ✅

  All dependencies resolved. No blockers.

───────────────────────────────────────────────────────────
REQUIRED TEST COVERAGE
───────────────────────────────────────────────────────────

| Test ID   | Type  | Pass Criteria                                                  |
|:----------|:------|:---------------------------------------------------------------|
| T03-01    | unit  | RuntimeAttemptState transitions forward only                   |
| T03-02    | unit  | RuntimeAttemptState rejects backward transition                |
| T03-03    | unit  | RuntimeAttemptState rejects skip (pending → running)           |
| T03-04    | unit  | PolicyObligation.DRY_RUN_REQUIRED blocks live execution        |
| T03-05    | unit  | PolicyObligation.APPROVAL_REQUIRED blocks without approval     |
| T03-06    | unit  | PolicyObligation.QUARANTINE triggers compensation on failure   |
| T03-07    | unit  | AdapterCapabilities defaults are correct for WindowsAdapter    |
| T03-08    | unit  | AdapterCapabilities custom capabilities work                   |
| T03-09    | unit  | RuntimePreflight passes for valid request                      |
| T03-10    | unit  | RuntimePreflight fails when no adapter                         |
| T03-11    | unit  | RuntimePreflight fails when policy denies                      |
| T03-12    | unit  | RuntimePreflight fails when dry_run_required but not dry_run   |
| T03-13    | unit  | RuntimePreflight fails when rate limited                       |
| T03-14    | unit  | RuntimePreflight fails when session budget exhausted           |
| T03-15    | unit  | RuntimePreflight fails when health check unhealthy             |
| T03-16    | unit  | RuntimePreflight fails when raw secret detected in params      |
| T03-17    | unit  | RuntimePreflight fingerprint changes on policy version change  |
| T03-18    | unit  | RuntimeExecutionReceipt truth_message matches state            |
| T03-19    | unit  | RuntimeExecutionReceipt.runtime_execution_performed is correct |
| T03-20    | unit  | RuntimeExecutionReceipt.simulated is correct for dry_run       |
| T03-21    | unit  | RuntimeResourceBudget defaults are sane                        |
| T03-22    | unit  | RuntimeResourceBudget enforces max_actions                     |
| T03-23    | unit  | RuntimeAttempt creates with PENDING state                      |
| T03-24    | unit  | RuntimeAttempt transitions through full lifecycle              |
| T03-25    | unit  | PreflightResult includes all 12 checks                         |
| T03-26    | unit  | PreflightResult.fingerprint is SHA-256                         |
| T03-27    | unit  | WindowsAdapter declares capabilities                           |
| T03-28    | unit  | Full integration: preflight → attempt → receipt                |
| T03-29    | unit  | Receipt attached to AgentResult.data["receipt"]                |
| T03-30    | unit  | Existing tests still pass (regression gate)                    |
| T03-31    | unit  | RuntimePreflight passes for read-only actions                  |
| T03-32    | unit  | RuntimePreflight fingerprint detects stale state               |
| T03-33    | unit  | AdapterCapabilities.to_dict() round-trips                      |
| T03-34    | unit  | RuntimeExecutionReceipt is immutable after creation            |
| T03-35    | unit  | Preflight passes when policy is ALLOW_WITH_OBLIGATIONS + met   |
| T03-36    | unit  | Preflight blocks when policy is ALLOW_WITH_OBLIGATIONS + unmet |
| T03-37    | unit  | Multiple obligations checked in order                          |
| T03-38    | unit  | Receipt records which obligations were checked                  |
| T03-39    | unit  | RuntimeAttempt terminal states are final                       |
| T03-40    | unit  | Evidence ledger records attempt state transitions              |

───────────────────────────────────────────────────────────
ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  AC-01: RuntimeExecutionReceipt is produced for every execution through
         _execute_single_action, with truthful metadata.

  AC-02: Canonical preflight (12 checks) runs before every action dispatch.
         Blocked executions produce a BLOCKED receipt with reason.

  AC-03: Policy obligations are mechanically enforced. dry_run_required
         blocks live execution. quarantine_on_failure triggers compensation.

  AC-04: WindowsAdapter declares AdapterCapabilities with correct defaults.

  AC-05: All 40 tests pass. All existing tests still pass.

  AC-06: The preflight fingerprint detects state changes between check and
         execution (TOCTOU safety).

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────

Reviewer Report ID:
Review Cycle:
Lead Decision:            [X] ACCEPT

Blueprint Version after response: 1.0
Lead Sign:                Lead AI Instance — 2026-04-26 21:00

═══════════════════════════════════════════════════════════
