# v0.14: Compensation Plans — Structured Undo with Rollback Managers

> **v0.13.0 → v0.14.0** | ~4h | 2 workstreams
> **Source:** `C:\Next AI\ref\deterministic-agent-control-protocol-main\src\rollback\manager.ts`

---

## Why

Our `undo()` is best-effort — it tries to guess the inverse operation from the `Snapshot` object and usually fails. `compensate()` just tells the user "you're on your own." Neither one generates a *plan* — they react to a single mutation.

det-acp solves this properly: before executing actions, register what each action *would* need to undo itself. Then when rollback is needed, the `RollbackManager` builds a `CompensationPlan` from those registered undo steps, executes them in reverse order (last-in-first-out), and records every rollback in the evidence ledger.

This gives us:
1. **Per-action undo strategies** — each action type knows how to reverse itself
2. **Structured compensation plans** — ordered list of rollback steps, not ad-hoc guessing
3. **Evidence-trail rollback** — every undo recorded in the evidence ledger we built in v0.13

---

## Current State

| Component | What We Have | Gap |
|-----------|-------------|-----|
| `undo()` | Guesses inverse from `Snapshot.before_state` → calls `surface.fill()` | No per-action strategy, fails for most actions |
| `compensate()` | Returns "cannot be automatically compensated" always | Never works |
| `MutationRecord` | Records `before_state`/`after_state` but no inverse operation | No undo instruction stored |
| `DesktopAgent` | Stores `_execution_snapshots` dict but never uses it for intelligent rollback | Dead code |

---

## Workstream A: Compensation Plan Engine (~2h)

**New file:** `src/agent_core/safety/compensation.py` (~180 lines)

### Design

```python
@dataclass
class CompensatingAction:
    """A single undo step in a compensation plan."""
    action: str              # Original action name: "click", "fill", "type_text"
    target: str              # Original target
    inverse_action: str      # What to do: "fill", "key_press", "click", "none"
    inverse_params: dict     # Params for the inverse: {"target": ..., "value": ...}
    strategy: str            # "restore_state", "delete_created", "compensate", "none"
    can_rollback: bool       # Whether we have enough info to undo
    priority: int = 0        # Higher = undo first (LIFO by default)

@dataclass
class CompensationPlan:
    """Ordered list of undo steps for a session or execution."""
    plan_id: str
    execution_id: str
    steps: list[CompensatingAction]
    created_at: str

@dataclass
class RollbackStepResult:
    action: str
    success: bool
    description: str
    error: str = ""

@dataclass
class RollbackReport:
    plan_id: str
    total_steps: int
    succeeded: int
    failed: int
    skipped: int
    results: list[RollbackStepResult]

class CompensationEngine:
    """Build and execute compensation plans.

    Before each action, call register() with the before-state.
    When rollback is needed, call build_plan() then execute_plan().
    """

    def __init__(self, surface: SurfaceAdapter | None = None, ledger: EvidenceLedger | None = None): ...

    def register(self, execution_id: str, action: str, target: str,
                 before_state: dict, params: dict) -> CompensatingAction:
        """Register an undo strategy for a just-completed action.

        Maps each action type to its inverse:
          fill("email", "foo@bar.com") → fill("email", before_value)
          type_text("hello") → key_press("Backspace" × 5)  [strategy=none, can_rollback=False]
          click("button") → strategy=none (clicking is not meaningfully reversible)
          key_press("Enter") → strategy=none
          scroll("down", 500) → scroll("up", 500)
          navigate("url") → navigate(previous_url)  [if available]
          screenshot() → read_only, no undo needed
          snapshot() → read_only, no undo needed
        """

    def build_plan(self, execution_id: str) -> CompensationPlan:
        """Build a compensation plan from registered actions.

        Steps are ordered in reverse (LIFO — last action undone first).
        Skips read-only actions and actions with strategy="none".
        """

    async def execute_plan(self, plan: CompensationPlan) -> RollbackReport:
        """Execute a compensation plan against the surface adapter.

        Best-effort: continues even if individual rollbacks fail.
        Records every rollback step in the evidence ledger.
        """

    def clear(self, execution_id: str) -> None:
        """Clear registered actions for an execution (after plan execution or session end)."""
```

### Action → Inverse Mapping

| Action | Strategy | Inverse | Can Rollback |
|--------|----------|---------|-------------|
| `fill` | `restore_state` | `fill(target, before_value)` | ✅ Yes (if before_value captured) |
| `type_text` | `restore_state` | `key_press(Ctrl+A) + fill(target, before)` | ✅ Yes (if focused element + before text captured) |
| `scroll` | `restore_state` | `scroll(opposite_direction, same_amount)` | ✅ Yes |
| `navigate` | `restore_state` | `navigate(previous_url)` | ✅ Yes (if previous URL captured) |
| `click` | `none` | — | ❌ No (clicking triggers side effects) |
| `key_press` | `none` | — | ❌ No (keys trigger actions) |
| `screenshot` | `none` | — | N/A (read-only) |
| `snapshot` | `none` | — | N/A (read-only) |

### Tests (~15)
- register fill → CompensatingAction with restore_state strategy
- register click → CompensatingAction with none strategy
- register type_text → CompensatingAction with restore_state strategy
- register scroll → CompensatingAction with opposite direction
- register navigate → CompensatingAction with previous URL
- register screenshot → CompensatingAction with none
- build_plan returns steps in reverse order
- build_plan skips read-only actions
- build_plan for empty registry
- execute_plan calls surface methods in order
- execute_plan continues on individual failures
- execute_plan records to evidence ledger
- execute_plan without surface returns all failed
- RollbackReport counts are correct
- clear removes registered actions

---

## Workstream B: Wire into DesktopAgent (~2h)

### Changes to `desktop_agent.py`

**1. Replace dead `_execution_snapshots` dict with `CompensationEngine`:**
```python
# Before:
self._execution_snapshots: dict[str, list[MutationRecord]] = {}

# After:
self._compensation = CompensationEngine(
    surface=self._surface,
    ledger=self._evidence_ledger,
)
```

**2. Register undo in `_execute_single_action()`:**
After capturing `before_state` and before adapter call:
```python
self._compensation.register(
    execution_id=context.execution_id,
    action=goal.capability,
    target=params.get("target", ""),
    before_state=before_state,
    params=params,
)
```

**3. Replace `undo()` implementation:**
```python
async def undo(self, execution_id: str, snapshot: Snapshot) -> UndoResult:
    plan = self._compensation.build_plan(execution_id)
    if not plan.steps:
        return UndoResult(execution_id=execution_id, success=False, ...)
    report = await self._compensation.execute_plan(plan)
    return UndoResult(
        execution_id=execution_id,
        success=report.failed == 0,
        summary=f"Rolled back {report.succeeded}/{report.total_steps} steps",
        ...
    )
```

**4. Replace `compensate()` implementation:**
Same pattern — build plan, execute, return report.

**5. Add `build_undo_plan()` public API:**
```python
async def build_undo_plan(self, execution_id: str) -> CompensationPlan:
    """Preview what undo would do without executing it."""
```

### Tests (~12)
- undo with compensation plan succeeds for fill action
- undo with compensation plan skips click (strategy=none)
- undo for empty execution returns failure
- compensate uses compensation engine
- build_undo_plan returns plan without executing
- _execute_single_action registers compensation
- compensation engine updated when surface changes
- undo plan recorded in evidence ledger
- undo after multiple actions reverses in LIFO order
- undo handles missing surface gracefully
- compensation clear called after session termination
- smoke: register 3 actions → build plan → execute → verify 3 rollbacks

---

## Execution Order

```
Step 1: A — Compensation Plan Engine    (~2h)   Core engine + tests
Step 2: B — Wire into DesktopAgent      (~2h)   Replace undo/compensate
Step 3: Full test suite → version bump
```

---

## Files Changed

| # | File | Action | Δ Lines |
|---|------|--------|---------|
| 1 | `src/agent_core/safety/compensation.py` | Create | ~180 |
| 2 | `src/agent_core/safety/__init__.py` | Edit: add exports | +5 |
| 3 | `src/agent_core/desktop_agent.py` | Edit: wire A–B, replace undo/compensate | +60/-40 |
| 4 | `tests/test_safety/test_compensation.py` | Create | ~180 |
| 5 | `tests/test_agent_core/test_os_contract.py` | Edit: update undo tests if needed | ~10 |
| 6 | `pyproject.toml` | Edit: bump v0.14.0 | +1 |

## Expected Outcome

| Metric | Before (v0.13.0) | After (v0.14.0) |
|--------|-------------------|------------------|
| Tests | 2,190 | ~2,217 |
| `undo()` | Best-effort guessing from Snapshot | **Structured compensation plan with per-action strategies** |
| `compensate()` | Always returns "cannot compensate" | **Builds + executes rollback plan** |
| Rollback audit | None | **Every rollback step in evidence ledger** |
| Preview undo | Not possible | **`build_undo_plan()` shows what would happen** |
