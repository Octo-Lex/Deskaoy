# AI-OS Batch 38 Alignment — Desktop-Agent Gap Analysis

> Maps AI-OS Batch 38 (Runtime Execution Hardening v1) requirements to Desktop-Agent's current implementation.

## What Batch 38 Requires

| Concept | Batch 38 Spec | Desktop-Agent Status |
|---------|--------------|---------------------|
| **RuntimeExecutionRequest** | Unified request type with adapter_id, runtime_kind, resource_budget, secret_handle | We use `AgentGoal` + `AgentContext` — different shape |
| **28-check Canonical Preflight** | Immutable checklist every adapter passes (no shell wrapper, cwd confinement, etc.) | We have `validate_instruction()` (5 checks) + `policy_bridge.preflight()` — **partial** |
| **Policy Obligation Enforcement** | `dry_run_required` blocks live, `quarantine_on_failure`, `approval_required` | We have `PolicyEffect.ALLOW_WITH_OBLIGATIONS` but no obligation **enforcement** — **gap** |
| **Resource Guard** | Shared limits: timeout, output_size, memory, network | We have `TimeoutGuard`, `LatencyBudget`, `CostTracker`, `SessionBudget` — **partial** (no output_size/memory/network guards) |
| **Adapter Health Registry** | Adapters declare capabilities (`supports_filesystem_sandbox`, etc.) | We have `HealthCheck` (6 probes) but no capability declarations — **gap** |
| **Attempt Lifecycle** | `preflight_passed` → `running` → `completed`/`failed`/`cancelled`/`timed_out`/`blocked` | We have `_execute_single_action()` but no formal attempt states — **gap** |
| **RuntimeExecutionReceipt** | Truthful receipt: `runtime_execution_performed`, `simulated`, `dry_run`, `side_effects_performed` | We have `AgentResult` with `ResultStatus` — **partial** (no receipt concept) |
| **Hermetic Environment** | Empty env, allowlisted vars, no raw secrets | Not implemented — **gap** (Desktop-Agent runs locally, not sandboxed) |
| **Preflight Fingerprint** | Registry state + policy version + approval state + adapter health | Not implemented — **gap** |
| **RuntimeResourceBudget** | Explicit budget: timeout_ms, max_output_bytes, max_memory_bytes, network_policy | We have `SessionLimits` but no resource-level budget — **partial** |

## What Applies to Desktop-Agent

Batch 38 explicitly states: *"The Desktop-Agent bridge adapter remains metadata/simulation-only."*

This means:
1. Desktop-Agent is NOT a runtime adapter (it doesn't execute arbitrary code)
2. Desktop-Agent IS a bridge adapter (GUI automation, not code execution)
3. The shared preflight checks still apply to Desktop-Agent's execution paths
4. Desktop-Agent must align its **receipt** and **attempt** patterns with Batch 38

## What We Must Adopt

### Must-Have (Blocks AI-OS Integration)

1. **Canonical Preflight** — Desktop-Agent's `_execute_single_action()` must run a shared preflight suite before execution. Our existing checks (policy, rate, session budget) are ad-hoc. Batch 38 demands a formalized, fingerprinted preflight.

2. **Policy Obligation Enforcement** — `ALLOW_WITH_OBLIGATIONS` must mechanically enforce obligations. Currently we have the enum value but no enforcement logic.

3. **Adapter Capability Declarations** — Our surface adapters must declare what they support (filesystem, network, sandboxing). The health registry must include these.

4. **Attempt Lifecycle** — Formalize execution as: `pending` → `preflight_passed` → `running` → terminal state. Record in receipt.

5. **Truthful Receipt** — Every execution produces a `RuntimeExecutionReceipt`-compatible record. This extends our `AgentResult` with Batch 38 truth fields.

### Nice-to-Have (Future)

6. **Hermetic Environment** — Desktop-Agent runs on the host, not in a sandbox. This doesn't apply directly but we should be aware.

7. **Secret Handling** — Desktop-Agent doesn't inject secrets into code. Our credential handling is already separate.

## Implementation Plan

### New types in `os_types.py`:

```python
class RuntimeExecutionRequest  # Wraps AgentGoal with resource budget + adapter_id
class RuntimeExecutionReceipt  # Truthful receipt with attempt lifecycle
class RuntimeAttemptState(StrEnum)  # pending, preflight_passed, running, completed, failed, cancelled, timed_out, blocked
class RuntimeResourceBudget  # timeout_ms, max_output_bytes, max_memory_bytes, network_policy
class AdapterCapabilities  # supports_filesystem_sandbox, supports_network_deny, etc.
class PolicyObligation(StrEnum)  # dry_run_required, approval_required, quarantine_on_failure
class PreflightFingerprint  # Hash of registry + policy + health state
```

### New modules:

- `safety/preflight.py` — 28-check canonical preflight (desktop-relevant subset)
- `safety/resource_budget.py` — RuntimeResourceBudget enforcement
- `safety/attempt_lifecycle.py` — Attempt state machine
- `adapters/capabilities.py` — Adapter capability declarations

### Wired into:

- `desktop_agent.py._execute_single_action()` — preflight → obligation → attempt lifecycle → receipt
- `adapters/windows.py` — declares capabilities
- `health.py` — includes adapter capability checks

---

*Analysis Date: 2026-04-26*
