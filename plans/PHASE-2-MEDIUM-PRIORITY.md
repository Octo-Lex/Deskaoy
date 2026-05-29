# Phase 2: Fix MEDIUM-Priority Issues — Detailed Implementation Plan

> 22 issues, ~38 hours total. Focusing on top ~12 most impactful (~12 hours).
> Prerequisites: Phase 0 (C1–C5) + Phase 1 (H1–H8) — all 1086 tests pass.

---

## Issue Selection

Not all 22 MEDIUM issues are equal. Many are feature requests masquerading as bugs
(M3: no vision providers wired, M5: VLM_FULL is stub, M8: no 3-tier CrashWatchdog).
Others are pure code quality (M17: no async I/O batching, M14: no Chrome header morphing).

**This plan focuses on 12 issues that fix real bugs or prevent silent data loss.**

Excluded (feature work, not bugs):
- M3: Vision providers — config/deployment issue, not a code fix
- M5: VLM_FULL stub — requires cloud API integration
- M8: 3-tier CrashWatchdog — new feature
- M9: Coarse StaleElementWatchdog — works, just coarse
- M10: Text-only selector similarity — new feature
- M13: CircuitBreaker integration — design decision
- M14: Chrome header morphing — new feature
- M17: Async I/O batching in tracing — perf optimization
- M18: SQLiteSink async — perf optimization
- M20: Header redaction in tracing — already partially done
- M22: Recovery private attr access — works, just fragile

---

## Execution Order

```
M1:  Replace __import__() hack           (15 min)  — recovery, trivial
M11: Unbounded event history              (1 hour)  — recovery, memory leak
M19: Silent event drop at cap             (30 min)  — tracing, silent data loss
M21: Level 1 truncation is flag-only      (1 hour)  — results, data integrity
M15: No step timeout in AgentLoop         (1 hour)  — agent, hangs forever
M16: Duplicate of C2 (already fixed)      (—)       — skip
M4:  No normalized coordinates            (2 hours)  — interaction, wrong coords
M7:  Verification not wired into controller (2 hours) — verification, dead code
M6:  No verification level escalation     (2 hours)  — verification, degrades
M2:  Vision sync calls block event loop   (2 hours)  — vision, stalls everything
M12: No budget-aware cascade stopping     (1 hour)  — budget, overspend
M23: Recovery accesses private attributes (30 min)  — recovery, fragile coupling
```

**Total: ~13.5 hours for 12 fixes**

---

## M1: Replace `__import__()` Hack — 15 min

### The Bug

`RecoveryCoordinator._attempt_recovery()` uses:
```python
await self._event_bus.emit(
    __import__("super_browser.recovery.types", fromlist=["WatchdogEventData"])
    .WatchdogEventData(...)
)
```

This is fragile — breaks if the module path changes, no IDE support, no type checking.

### The Fix

**File**: `src/super_browser/recovery/coordinator.py`

`WatchdogEventData` is already imported at the top of the file:
```python
from super_browser.recovery.types import (
    ActionRecord,
    ClassifiedError,
    RecoveryEvent,
    RecoveryStrategy,
    WatchdogEvent,
)
```

Just add `WatchdogEventData` to the existing import and replace the `__import__` call:

```python
# Add to existing imports:
from super_browser.recovery.types import (
    ActionRecord,
    ClassifiedError,
    RecoveryEvent,
    RecoveryStrategy,
    WatchdogEvent,
    WatchdogEventData,  # M1: was using __import__ hack
)
```

Then replace:
```python
# Before:
await self._event_bus.emit(
    __import__("super_browser.recovery.types", fromlist=["WatchdogEventData"])
    .WatchdogEventData(...)

# After:
await self._event_bus.emit(
    WatchdogEventData(...)
)
```

### New Tests

Update existing test to verify no `__import__` usage:
```python
def test_no_import_hack():
    """M1: RecoveryCoordinator should not use __import__."""
    import inspect
    from super_browser.recovery.coordinator import RecoveryCoordinator
    source = inspect.getsource(RecoveryCoordinator)
    assert "__import__" not in source
```

---

## M11: Unbounded Event History — 1 hour

### The Bug

`WatchdogEventBus._history` grows without bound. A long-running session can accumulate
thousands of events, causing steady memory growth.

### The Fix

**File**: `src/super_browser/recovery/event_bus.py`

Add a `max_history` parameter and cap the list:

```python
class WatchdogEventBus:
    def __init__(self, max_queue_size: int = 100, max_history: int = 1000) -> None:
        ...
        self._max_history = max_history
        self._history: list[WatchdogEventData] = []

    async def emit(self, event: WatchdogEventData) -> None:
        self._history.append(event)
        # M11: cap history to prevent unbounded memory growth
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        ...
```

### New Tests

```python
def test_history_capped_at_max():
    """M11: Event history should be capped."""
    bus = WatchdogEventBus(max_history=10)
    for i in range(20):
        asyncio.run(bus.emit(WatchdogEventData(
            event_type=WatchdogEvent.RECOVERY_STARTED,
            source="test", detail=f"event {i}",
        )))
    assert len(bus._history) == 10

def test_history_keeps_recent_events():
    """M11: When capped, most recent events are preserved."""
    bus = WatchdogEventBus(max_history=5)
    for i in range(10):
        asyncio.run(bus.emit(WatchdogEventData(
            event_type=WatchdogEvent.RECOVERY_STARTED,
            source="test", detail=f"event {i}",
        )))
    events = bus.drain()
    assert events[0].detail == "event 5"  # oldest kept
    assert events[-1].detail == "event 9"  # newest
```

---

## M19: Silent Event Drop at Cap — 30 min

### The Bug

`FlowLogger._store_event()` silently drops events when `_max_events` is reached:
```python
def _store_event(self, event: TraceEvent) -> None:
    events = self._events.setdefault(event.trace_id, [])
    if len(events) < self._max_events:
        events.append(event)
    # else: silently dropped — no log, no counter, no warning
```

Operators have no way to know events are being lost.

### The Fix

**File**: `src/super_browser/tracing/flow_logger.py`

Add a drop counter and log warning:

```python
def __init__(self, ...):
    ...
    self._dropped_events: int = 0

def _store_event(self, event: TraceEvent) -> None:
    events = self._events.setdefault(event.trace_id, [])
    if len(events) < self._max_events:
        events.append(event)
    else:
        self._dropped_events += 1
        if self._dropped_events <= 3 or self._dropped_events % 100 == 0:
            logger.warning("Trace event dropped (cap=%d, dropped=%d): %s",
                           self._max_events, self._dropped_events, event.name)

@property
def dropped_event_count(self) -> int:
    return self._dropped_events
```

### New Tests

```python
def test_dropped_event_count():
    """M19: Dropped events should be counted and accessible."""
    logger = FlowLogger(max_events_per_trace=3)
    for i in range(5):
        asyncio.run(logger.emit_event(SpanKind.CUSTOM, f"event-{i}"))
    assert logger.dropped_event_count == 2

def test_no_drop_when_under_cap():
    """M19: No drops when under cap."""
    logger = FlowLogger(max_events_per_trace=100)
    asyncio.run(logger.emit_event(SpanKind.CUSTOM, "event"))
    assert logger.dropped_event_count == 0
```

---

## M21: Level 1 Truncation Is Flag-Only — 1 hour

### The Bug

`OutputDefender._truncate_data()` only sets a `truncated` flag — it doesn't actually
truncate the data:
```python
def _truncate_data(self, result: ActionResult, max_chars: int) -> ActionResult:
    if isinstance(result.data, dict):
        result.data["truncated"] = True  # flag only, data still huge
    return result
```

The result is still serialized at full size, then the next check (Level 2 spill) has
to handle it. If the data is a string or list, nothing happens at all.

### The Fix

**File**: `src/super_browser/results/output.py`

Actually truncate the data:

```python
def _truncate_data(self, result: ActionResult, max_chars: int) -> ActionResult:
    """Level 1: Truncate the data payload to fit within max_chars."""
    if isinstance(result.data, dict):
        serialized = json.dumps(result.data, default=str)
        if len(serialized) > max_chars:
            # Truncate string values in the dict
            truncated = {}
            for k, v in result.data.items():
                if isinstance(v, str) and len(v) > max_chars // max(len(result.data), 1):
                    truncated[k] = v[:max_chars // max(len(result.data), 1)] + "\n... [truncated]"
                else:
                    truncated[k] = v
            truncated["truncated"] = True
            result.data = truncated
    elif isinstance(result.data, str):
        if len(result.data) > max_chars:
            result.data = result.data[:max_chars] + "\n... [truncated]"
    elif isinstance(result.data, list):
        serialized = json.dumps(result.data, default=str)
        if len(serialized) > max_chars:
            # Keep first portion of list
            result.data = result.data[:max_chars // 100]  # rough heuristic
            result.data.append("... [truncated]")
    return result
```

### New Tests

```python
def test_truncate_dict_actually_truncates():
    """M21: Level 1 should actually truncate dict data, not just flag it."""
    from super_browser.results import action_result
    defender = OutputDefender()
    huge_data = {"content": "x" * 100_000, "other": "y"}
    result = action_result(ok=True, data=huge_data)
    defended = defender.defend(result, max_chars=500)
    # Data should be significantly smaller than original
    assert len(json.dumps(defended.data)) < 10_000
    assert defended.data.get("truncated") is True

def test_truncate_string_actually_truncates():
    """M21: Level 1 should truncate string data."""
    defender = OutputDefender()
    result = action_result(ok=True, data="x" * 100_000)
    defended = defender.defend(result, max_chars=500)
    assert len(str(defended.data)) < 1000
```

---

## M15: No Step Timeout in AgentLoop — 1 hour

### The Bug

`AgentLoop._run_loop()` has `max_steps` but no per-step timeout. If an action hangs
(e.g., CDP call stalls), the entire agent loop hangs forever.

### The Fix

**File**: `src/super_browser/agent/loop.py`

Add `step_timeout` parameter and wrap each step in `asyncio.wait_for`:

```python
class AgentLoop:
    def __init__(
        self,
        ...
        step_timeout: float = 30.0,  # M15: per-step timeout
    ) -> None:
        ...
        self._step_timeout = step_timeout
```

In `_run_loop`, wrap the action dispatch:

```python
try:
    result = await asyncio.wait_for(
        self._dispatch_action(action_name, action_params),
        timeout=self._step_timeout,
    )
except asyncio.TimeoutError:
    duration = (time.monotonic() - step_start) * 1000
    steps.append(StepResult(step_num, "timeout", {}, None, duration, error="Step timed out"))
    await self._emit(StepEvent.STEP_ERROR, {"step_number": step_num, "error": "timeout"})
    continue  # move to next step
```

### New Tests

```python
def test_step_timeout_moves_to_next_step():
    """M15: If a step times out, the loop should continue."""
    async def _test():
        call_count = 0
        async def slow_llm(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(100)  # hangs forever
            return {"done": True}

        loop = AgentLoop(
            controller=_make_controller(),
            registry=_make_registry(),
            llm_client=MagicMock(propose_action=AsyncMock(side_effect=[
                {"action": "scroll", "params": {}},  # times out
                {"done": True},  # succeeds
            ])),
            max_steps=5,
            step_timeout=0.1,  # very short timeout
        )
        result = await loop.run("test")
        assert result.total_steps >= 1
    asyncio.run(_test())
```

---

## M4: No Normalized Coordinates — 2 hours

### The Bug

`MultimodalController._resolve_to_coordinates()` returns raw pixel coordinates.
When the viewport size changes (responsive layout, resize), these coordinates are
wrong — they need to be normalized to [0,1] and then scaled to the current viewport.

### The Fix

**File**: `src/super_browser/interaction/controller.py`

Add coordinate normalization:

```python
async def _resolve_to_coordinates(
    self, target: str
) -> Optional[tuple[float, float]]:
    ...
    # After getting raw coords (x, y):
    # M4: normalize to viewport-relative coordinates
    if coords:
        x, y = coords
        viewport = await self._get_viewport_size()
        if viewport:
            vw, vh = viewport
            # Normalize to [0,1] range
            return (x / vw, y / vh)
    return coords

async def _get_viewport_size(self) -> Optional[tuple[int, int]]:
    """Get current viewport dimensions for coordinate normalization."""
    try:
        result = await self._cdp.send("Runtime.evaluate", {
            "expression": "JSON.stringify({w: window.innerWidth, h: window.innerHeight})",
            "returnByValue": True,
        })
        if result.ok and result.data:
            val = result.data.get("result", {}).get("value")
            if val:
                d = json.loads(val)
                return (d["w"], d["h"])
    except Exception:
        pass
    return None
```

Actually — wait. The issue is that coordinates come from `getBoundingClientRect()` which
is already in CSS pixels relative to the viewport. These are correct for the current
viewport. The real problem is when coordinates are *cached* and the viewport changes.

The better fix is to normalize coordinates only when they're used for CDP input events,
which use device pixels. Let me reconsider.

The actual issue from the report: coordinates from `_resolve_to_coordinates()` are used
directly in `compositor_click(x, y)` and `Input.dispatchMouseEvent`, but if the browser
viewport doesn't match the expected dimensions, the click lands in the wrong place.

The fix: Store viewport dimensions alongside coordinates and scale when dispatching.

### Revised Fix

Add a `_viewport_size` cache to the controller, and scale coordinates when dispatching
CDP input events:

```python
async def _ensure_viewport(self) -> tuple[int, int]:
    """Cache current viewport size."""
    if not hasattr(self, '_viewport_cache') or self._viewport_cache is None:
        try:
            result = await self._cdp.send("Runtime.evaluate", {
                "expression": "JSON.stringify({w: window.innerWidth, h: window.innerHeight})",
                "returnByValue": True,
            })
            if result.ok and result.data:
                val = result.data.get("result", {}).get("value")
                if val:
                    d = json.loads(val)
                    self._viewport_cache = (d["w"], d["h"])
        except Exception:
            pass
    return self._viewport_cache or (1280, 720)
```

Actually, `getBoundingClientRect()` returns CSS pixels which are exactly what CDP
`Input.dispatchMouseEvent` expects. So coordinates ARE correct. The "normalized
coordinates" issue is about vision providers that return coordinates in model-space
(e.g., UITARS uses 1280x720) that need to be scaled to actual viewport. That's
already handled by `resize_coordinates()` in `vision/coords.py`.

**Revised conclusion**: M4 is actually working correctly for CSS selectors. The
"normalized coordinates" issue only applies to vision providers, which already have
`resize_coordinates()`. The real gap is that `_resolve_to_coordinates` doesn't account
for CSS transform/scale — but that's an edge case.

Let me reprioritize: skip M4, do M23 instead.

---

## M23: Recovery Accesses Private Attributes — 30 min

### The Bug

`RecoveryCoordinator` accesses `self._controller._cdp`, `self._controller._page`
directly. If the controller changes its internal structure, recovery breaks silently.

### The Fix

**File**: `src/super_browser/interaction/controller.py`

Add public accessor properties:

```python
@property
def cdp(self) -> CDPBridge:
    """Public accessor for CDP bridge (used by RecoveryCoordinator)."""
    return self._cdp

@property
def page(self) -> PageHandle:
    """Public accessor for page handle."""
    return self._page
```

**File**: `src/super_browser/recovery/coordinator.py`

Replace all `_cdp` and `_page` private access:

```python
# Before:
cdp = getattr(self._controller, "_cdp", None)
page = getattr(self._controller, "_page", None)

# After:
cdp = getattr(self._controller, "cdp", None)
page = getattr(self._controller, "page", None)
```

### New Tests

```python
def test_controller_cdp_property():
    """M23: Controller should expose cdp as public property."""
    ctrl = _make_controller()
    assert ctrl.cdp is ctrl._cdp

def test_controller_page_property():
    """M23: Controller should expose page as public property."""
    ctrl = _make_controller()
    assert ctrl.page is ctrl._page

def test_recovery_uses_public_properties():
    """M23: RecoveryCoordinator should not access private attrs."""
    import inspect
    from super_browser.recovery.coordinator import RecoveryCoordinator
    source = inspect.getsource(RecoveryCoordinator)
    # Should use .cdp and .page, not ._cdp and ._page
    assert '"_cdp"' not in source and "'_cdp'" not in source
```

---

## M7: Verification Not Wired into Controller — 2 hours

### The Bug

`MultimodalController.enable_verification(verifier)` sets `self._two_phase = True`
and stores the verifier, but `_cascade()` never uses it. The verifier is dead code.

### The Fix

**File**: `src/super_browser/interaction/controller.py`

Add post-action verification in the cascade loop:

```python
# In _cascade(), after a successful action:
if result.ok:
    # M7: post-action verification if two-phase is enabled
    if self._two_phase and self._verifier:
        try:
            verification = await self._verifier.verify(
                screenshot_before=getattr(self, '_last_screenshot', None),
                screenshot_after=await self._take_screenshot(),
            )
            if not verification.passed:
                # Verification failed — try next tier
                attempts.append(TierAttempt(tier, TierOutcome.FAILED, duration,
                                           error=f"verification: {verification.detail}"))
                if self._cache:
                    self._cache.record_failure(domain, pattern, tier)
                continue  # try next tier
        except Exception as exc:
            logger.debug("Verification failed: %s", exc)
            # Don't block the action on verification error

    attempts.append(TierAttempt(tier, TierOutcome.SUCCESS, duration))
    ...
```

Also add `_take_screenshot` helper:

```python
async def _take_screenshot(self) -> Optional[bytes]:
    try:
        import base64
        result = await self._cdp.capture_screenshot(format="png")
        if result.ok and result.data:
            return base64.b64decode(result.data.get("data", ""))
    except Exception:
        pass
    return None
```

### New Tests

```python
def test_verification_rejects_triggers_next_tier():
    """M7: When verification fails, cascade should try next tier."""
    ...

def test_verification_passes_succeeds():
    """M7: When verification passes, action succeeds normally."""
    ...
```

---

## M6: No Verification Level Escalation — 2 hours

### The Bug

The verifier has structural and semantic levels but the controller always uses the
same level. If structural verification passes but the result looks wrong, there's no
escalation to semantic.

### The Fix

**File**: `src/super_browser/interaction/controller.py`

Start at STRUCTURAL, escalate to SEMANTIC on repeat failure:

```python
# In the cascade loop:
from super_browser.recovery.types import ValidationLevel

validation_level = ValidationLevel.STRUCTURAL
...
# In verification:
verification = await self._verifier.verify(
    ...,
    level=validation_level,
)
if not verification.passed:
    # Escalate verification level for next attempt
    if validation_level == ValidationLevel.STRUCTURAL:
        validation_level = ValidationLevel.SEMANTIC
```

This naturally pairs with M7 — the cascade already retries on failure, we just
escalate the verification rigor.

### New Tests

```python
def test_verification_escalates_on_failure():
    """M6: Verification should escalate from STRUCTURAL to SEMANTIC."""
    ...
```

---

## M2: Vision Sync Calls Block Event Loop — 2 hours

### The Bug

Both `AnthropicCUAProvider` and `OpenAIResponseProvider` call synchronous SDK methods
in async functions. These block the entire event loop for 1-15 seconds.

```python
# AnthropicCUAProvider.locate():
message = self._client.messages.create(...)  # sync! blocks for seconds

# OpenAIResponseProvider.locate():
response = self._client.chat.completions.create(...)  # sync!
```

### The Fix

**File**: `src/super_browser/vision/providers.py`

Wrap all sync SDK calls in `asyncio.to_thread()`:

```python
# AnthropicCUAProvider:
async def locate(self, request: VisionRequest) -> VisionResponse:
    ...
    # M2: run sync call in thread pool to avoid blocking event loop
    message = await asyncio.to_thread(
        self._client.messages.create,
        model=self._model,
        max_tokens=self._max_tokens,
        tools=[...],
        messages=[...],
    )

# OpenAIResponseProvider:
async def locate(self, request: VisionRequest) -> VisionResponse:
    ...
    response = await asyncio.to_thread(
        self._client.chat.completions.create,
        model=self._model,
        ...
    )

# UITARSProvider (model.generate is also sync):
output = await asyncio.to_thread(
    self._model.generate,
    **inputs,
    max_new_tokens=self._max_new_tokens,
)

# health_check methods too:
async def health_check(self) -> bool:
    ...
    await asyncio.to_thread(self._client.messages.create, ...)
```

### New Tests

```python
def test_anthropic_locate_does_not_block():
    """M2: Anthropic locate should use asyncio.to_thread."""
    import inspect
    source = inspect.getsource(AnthropicCUAProvider.locate)
    assert "to_thread" in source

def test_openai_locate_does_not_block():
    """M2: OpenAI locate should use asyncio.to_thread."""
    import inspect
    source = inspect.getsource(OpenAIResponseProvider.locate)
    assert "to_thread" in source
```

---

## M12: No Budget-Aware Cascade Stopping — 1 hour

### The Bug

When the budget is exhausted mid-cascade, the controller continues trying all 3 tiers.
Each failed tier may trigger an LLM call (for vision), spending more tokens.

### The Fix

**File**: `src/super_browser/interaction/controller.py`

Add a budget check at the start of each tier attempt:

```python
# In _cascade(), before each tier:
# M12: check budget before attempting next tier
if self._budget_client is not None:
    from super_browser.budget.types import BudgetScope
    block = self._budget_client._governor.check_budget(BudgetScope.PER_ACTION)
    if block:
        attempts.append(TierAttempt(tier, TierOutcome.UNAVAILABLE, 0.0,
                                    error="budget_exhausted"))
        continue
```

This requires the controller to have a reference to the budget client. Add it:

```python
class MultimodalController:
    def __init__(self, ...,
                 budget_client: Optional[Any] = None,  # M12
                 ) -> None:
        ...
        self._budget_client = budget_client
```

Wire it in `facade.py`:
```python
self._controller = MultimodalController(
    self._page, self._page.cdp,
    budget_client=self._budget_client,  # M12
)
```

### New Tests

```python
def test_cascade_skips_tiers_when_budget_exhausted():
    """M12: Cascade should skip tiers when budget is exhausted."""
    ...
```

---

## Verification Checklist

After all fixes:

```bash
# Full regression
pytest tests/ -v --tb=short

# Per-fix verification
pytest tests/test_recovery/test_coordinator.py -v   # M1, M23
pytest tests/test_recovery/test_event_bus.py -v      # M11
pytest tests/test_tracing/test_flow_logger.py -v     # M19
pytest tests/test_results/test_output.py -v          # M21
pytest tests/test_agent/test_loop.py -v              # M15
pytest tests/test_interaction/test_controller.py -v  # M7, M6, M12, M23
pytest tests/test_vision/test_providers.py -v        # M2
```

---

## Effort Summary

| Fix | Issue | Effort | Risk | Lines Changed |
|-----|-------|--------|------|---------------|
| M1 | `__import__` hack | 15 min | Low | ~5 (coordinator.py) |
| M11 | Unbounded event history | 1 hour | Low | ~10 (event_bus.py) |
| M19 | Silent event drop | 30 min | Low | ~15 (flow_logger.py) |
| M21 | Truncation flag-only | 1 hour | Low | ~30 (output.py) |
| M15 | No step timeout | 1 hour | Medium | ~20 (loop.py) |
| M23 | Private attr access | 30 min | Low | ~15 (controller.py, coordinator.py) |
| M7 | Verification not wired | 2 hours | Medium | ~40 (controller.py) |
| M6 | Verification escalation | 2 hours | Medium | ~20 (controller.py) |
| M2 | Vision sync blocks | 2 hours | Low | ~30 (providers.py) |
| M12 | Budget-aware cascade | 1 hour | Low | ~25 (controller.py, facade.py) |
| **Total** | **10 fixes** | **~11 hours** | | **~210 lines** |

### Skipped (12 of 22 MEDIUM issues)

| ID | Reason |
|----|--------|
| M3 | Feature request (vision provider wiring) |
| M4 | Already handled by `resize_coordinates()` |
| M5 | Feature request (VLM_FULL needs cloud API) |
| M8 | Feature request (3-tier CrashWatchdog) |
| M9 | Works, just coarse — enhancement |
| M10 | Feature request (similarity scoring) |
| M13 | Design decision (CB integration) |
| M14 | Feature request (header morphing) |
| M16 | Duplicate of C2 (already fixed) |
| M17 | Perf optimization (async batching) |
| M18 | Perf optimization (SQLiteSink async) |
| M20 | Partially done (URL query redaction exists) |
