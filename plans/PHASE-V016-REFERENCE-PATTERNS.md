# v0.16: Reference Tour Patterns — Quick Wins

> **v0.15.0 → v0.16.0** | ~7h | 6 workstreams
> **Sources:** OSWorld, Skyvern, Stagehand, UI-TARS Desktop

---

## Overview

6 patterns from the reference tour that deliver the highest ROI. Three of them
build on existing systems (failure classifier, routines, action validation)
rather than creating new ones.

---

## Workstream A: Schedule Enhancements (~1h)

**Source:** Skyvern `workflow/schedules.py`

Our `RoutineScheduler` uses naive `time.time()` with no timezone awareness.
Skyvern's `croniter`-based approach validates cron expressions, enforces
minimum intervals, and computes next runs in configurable timezones.

### Changes to `src/agent_core/routines/__init__.py`

1. Add timezone support via `zoneinfo` (stdlib in Python 3.9+)
2. Add `MIN_CRON_INTERVAL_SECONDS = 300` (5 minutes minimum)
3. Add `validate_cron_expression()` function
4. Add `compute_previous_fire_time()` for catch-up logic
5. Add `calculate_next_runs(schedule, tz, count)` for batch preview
6. Update `compute_next_run()` to accept optional `timezone` param

### New exports

```python
MIN_CRON_INTERVAL_SECONDS: int = 300
SUPPORTED_ACTION_TYPES: list[str]  # For Workstream C

def validate_cron_expression(expr: str) -> None: ...  # Raises ValueError
def compute_previous_fire_time(schedule: str, tz: str = "UTC") -> float: ...
def calculate_next_runs(schedule: str, tz: str = "UTC", count: int = 5) -> list[float]: ...
```

### Tests (~8)
- validate_cron_expression rejects invalid cron
- validate_cron_expression rejects too-frequent cron (< 5 min)
- validate_cron_expression accepts valid cron
- compute_next_run with timezone "America/New_York"
- compute_previous_fire_time returns past timestamp
- calculate_next_runs returns N future timestamps
- calculate_next_runs respects timezone
- Schedule "every 1m" raises on validate (< 5 min minimum)

---

## Workstream B: pyautogui `<` Bug Fix (~15min)

**Source:** OSWorld `desktop_env.py`

Known pyautogui bug: typing `<` produces `>` instead. OSWorld's fix converts
`press('<')` to `hotkey("shift", ",")` and handles `<` in `typewrite()` strings.

### New function in `src/agent_core/input/types.py`

```python
def fix_pyautogui_less_than(command: str) -> str:
    """Fix the pyautogui '<' bug.

    Converts press('<') → hotkey("shift", ",") and
    replaces '<' in typewrite strings with the hotkey equivalent.
    """
```

### Tests (~3)
- fix converts press('<') to hotkey
- fix handles '<' in typewrite string
- fix passes through strings without '<'

---

## Workstream C: Action Parameter Validation (~1.5h)

**Source:** OSWorld `desktop_env/actions.py`

OSWorld defines formal action spaces with typed parameter ranges. Our
`CAPABILITIES` dict is metadata-only — no validation of parameter values
before dispatch.

### New file: `src/agent_core/safety/action_validator.py`

```python
@dataclass
class ParameterSpec:
    """Declares valid ranges for an action parameter."""
    name: str
    type: type = str
    required: bool = True
    min_value: float | None = None  # For numeric types
    max_value: float | None = None
    allowed_values: list[Any] | None = None  # Enum-like
    max_length: int | None = None  # For string types

@dataclass
class ValidationIssue:
    param: str
    message: str
    severity: str = "error"  # "error" | "warning"

@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue]
    sanitized_params: dict[str, Any]

# Action definitions (from OSWorld's ACTION_SPACE + our CAPABILITIES)
ACTION_SPECS: dict[str, list[ParameterSpec]] = {
    "click": [
        ParameterSpec("target", str, required=False),
        ParameterSpec("x", float, required=False, min_value=0, max_value=7680),
        ParameterSpec("y", float, required=False, min_value=0, max_value=4320),
        ParameterSpec("button", str, required=False, allowed_values=["left", "right", "middle"]),
        ParameterSpec("num_clicks", int, required=False, allowed_values=[1, 2, 3]),
    ],
    "fill": [
        ParameterSpec("target", str, required=True),
        ParameterSpec("value", str, required=True, max_length=10000),
    ],
    "type_text": [
        ParameterSpec("target", str, required=True),
        ParameterSpec("text", str, required=True, max_length=50000),
    ],
    "key_press": [
        ParameterSpec("key", str, required=True),  # Validated against KEYBOARD_KEYS
    ],
    "scroll": [
        ParameterSpec("direction", str, required=True, allowed_values=["up", "down", "left", "right"]),
        ParameterSpec("amount", (int, float), required=False, min_value=0, max_value=10000),
    ],
    "screenshot": [],  # No parameters
    "snapshot": [],
    "navigate": [
        ParameterSpec("url", str, required=True, max_length=2048),
    ],
    "evaluate": [
        ParameterSpec("expression", str, required=True, max_length=50000),
    ],
}

def validate_action(action: str, params: dict) -> ValidationResult:
    """Validate action parameters against specs.

    Returns ValidationResult with:
    - valid: True if no errors
    - issues: list of ValidationIssue
    - sanitized_params: params with types coerced and defaults applied
    """
```

### Wiring into DesktopAgent

In `_execute_single_action()`, after policy preflight, before adapter dispatch:

```python
from agent_core.safety.action_validator import validate_action
validation = validate_action(goal.capability, params)
if not validation.valid:
    return AgentResult(
        execution_id=context.execution_id,
        status=ResultStatus.FAILURE,
        summary=f"Invalid parameters: {'; '.join(i.message for i in validation.issues)}",
        ...
    )
params = validation.sanitized_params
```

### Tests (~12)
- click with valid params passes
- click with out-of-range x fails
- click with invalid button fails
- fill missing target fails
- fill with oversized value warns
- type_text with valid params passes
- key_press with valid key passes
- key_press with empty key fails
- scroll with invalid direction fails
- navigate with valid URL passes
- screenshot with no params passes
- unknown action returns valid (no spec = pass through)
- sanitized params coerces types (str→int for num_clicks)

---

## Workstream D: Timeout Guard (~1h)

**Source:** Stagehand `createTimeoutGuard()`

Stagehand creates a guard that tracks remaining time across multiple steps.
Our code uses raw `asyncio.wait_for()` per-operation, losing the shared deadline.

### New file: `src/agent_core/safety/timeout_guard.py`

```python
class TimeoutGuard:
    """Shared deadline tracker for multi-step operations.

    Unlike ``asyncio.wait_for``, this guard:
    - Shares a single deadline across N steps
    - Reports remaining time for adaptive behavior
    - Can be passed to sub-operations
    """

    def __init__(self, total_timeout_ms: float):
        self._deadline = time.monotonic() + total_timeout_ms / 1000.0

    def check(self) -> None:
        """Raise ``TimeoutError`` if deadline passed."""

    @property
    def remaining_ms(self) -> float:
        """Milliseconds remaining until deadline."""

    @property
    def exhausted(self) -> bool:
        """True if deadline has passed."""

    def child(self, timeout_ms: float) -> TimeoutGuard:
        """Create a child guard capped by parent's remaining time."""

    async def sleep(self, seconds: float) -> None:
        """Sleep, but wake early if deadline passes."""
```

### Wiring into DesktopAgent

In `execute()`:

```python
guard = TimeoutGuard(total_timeout_ms=context.timeout_seconds * 1000)
# Pass guard to _execute_single_action, _execute_automate, etc.
```

In `_execute_single_action()`, replace `asyncio.wait_for(adapter_method(...), timeout=...)`:

```python
remaining = guard.remaining_ms / 1000.0
if remaining <= 0:
    raise TimeoutError("Timeout guard exhausted")
action_result = await asyncio.wait_for(adapter_method(**params), timeout=remaining)
```

### Tests (~8)
- check passes when time remaining
- check raises TimeoutError when exhausted
- remaining_ms decreases over time
- exhausted becomes True after deadline
- child guard is capped by parent
- child guard deadline ≤ parent deadline
- sleep respects deadline (wakes early)
- fresh guard has full remaining time

---

## Workstream E: Resource Tracker (~1h)

**Source:** UI-TARS Desktop `resource-cleaner.ts`

Long-running sessions accumulate resources (temp files, screenshots, browser
contexts). No cleanup happens on session termination. UI-TARS has a
`ResourceCleaner` that tracks and disposes resources.

### New file: `src/agent_core/safety/resource_tracker.py`

```python
@dataclass
class TrackedResource:
    resource_type: str   # "temp_file", "screenshot", "browser_context", "ledger"
    resource_id: str
    created_at: float = field(default_factory=time.time)
    cleanup_fn: Callable | None = None
    metadata: dict = field(default_factory=dict)

class ResourceTracker:
    """Track and cleanup resources in long-running sessions.

    Called by DesktopAgent.terminate_session() to release all resources.
    Also provides periodic cleanup for resources older than a threshold.
    """

    def track(self, resource_type: str, resource_id: str,
              cleanup_fn: Callable | None = None, **metadata) -> str: ...

    def untrack(self, resource_id: str) -> bool: ...

    def cleanup(self, resource_id: str) -> bool: ...
        """Run cleanup_fn for a specific resource."""

    def cleanup_all(self) -> int:
        """Run cleanup for all tracked resources. Returns count."""

    def cleanup_older_than(self, max_age_seconds: float) -> int:
        """Cleanup resources older than threshold."""

    def get_by_type(self, resource_type: str) -> list[TrackedResource]: ...

    @property
    def count(self) -> int: ...

    @property
    def tracked_types(self) -> set[str]: ...
```

### Wiring into DesktopAgent

```python
# In __init__:
self._resource_tracker = ResourceTracker()

# In configure_session():
self._resource_tracker.track("ledger", session_id, cleanup_fn=lambda: ...)

# In terminate_session():
self._resource_tracker.cleanup_all()
```

### Tests (~10)
- track adds resource, count increases
- untrack removes resource
- cleanup runs cleanup_fn
- cleanup_all cleans all resources
- cleanup_older_than respects age threshold
- cleanup_older_than skips recent resources
- get_by_type filters correctly
- tracked_types returns unique types
- cleanup with no cleanup_fn is no-op
- cleanup_all returns count

---

## Workstream F: Observation Protocol (~1h)

**Source:** OSWorld `_get_obs()`

OSWorld standardizes observations as `{screenshot, accessibility_tree, terminal, instruction}`.
We have no standard format — our `ActionResult.data` is a free-form dict.

### New file: `src/agent_core/observation.py`

```python
@dataclass
class DesktopObservation:
    """Standardized observation from the desktop environment.

    Adopted from OSWorld's observation format. Provides a consistent
    interface for benchmarks, logging, and LLM context building.
    """
    screenshot: bytes | None = None
    accessibility_tree: dict | list | None = None
    active_window: str = ""
    focused_element: str = ""
    instruction: str = ""
    step_count: int = 0
    timestamp: float = field(default_factory=time.time)
    extra: dict = field(default_factory=dict)

    def to_context_string(self) -> str:
        """Format as a human-readable string for LLM context."""

    def to_dict(self) -> dict:
        """Serialize (screenshot as base64 if present)."""

    @classmethod
    def from_action_result(cls, result: ActionResult, instruction: str = "",
                           step_count: int = 0) -> DesktopObservation:
        """Construct from an ActionResult."""
```

### Wiring

Called after each action in `_execute_single_action()` and `_execute_automate()`:

```python
obs = DesktopObservation.from_action_result(action_result, instruction, step_count)
```

### Tests (~8)
- construction with all fields
- to_context_string formats nicely
- to_dict serializes (screenshot as base64)
- from_action_result extracts from ActionResult
- from_action_result handles None data
- to_dict without screenshot
- extra dict preserved
- timestamp auto-populated

---

## Execution Order

```
Step 1: A — Schedule Enhancements       (~1h)    routines/__init__.py edits + 8 tests
Step 2: B — pyautogui `<` Bug Fix        (~15m)   input/types.py addition + 3 tests
Step 3: C — Action Parameter Validation  (~1.5h)  safety/action_validator.py + 13 tests
Step 4: D — Timeout Guard                (~1h)    safety/timeout_guard.py + 8 tests
Step 5: E — Resource Tracker             (~1h)    safety/resource_tracker.py + 10 tests
Step 6: F — Observation Protocol         (~1h)    observation.py + 8 tests
Step 7: Wire all into DesktopAgent       (~30m)
Step 8: Full test suite → version bump
```

---

## Files Changed

| # | File | Action | Δ Lines |
|---|------|--------|---------|
| 1 | `src/agent_core/routines/__init__.py` | Edit: timezone, validation | +80 |
| 2 | `src/agent_core/input/types.py` | Edit: add `fix_pyautogui_less_than` | +35 |
| 3 | `src/agent_core/safety/action_validator.py` | Create | ~180 |
| 4 | `src/agent_core/safety/timeout_guard.py` | Create | ~90 |
| 5 | `src/agent_core/safety/resource_tracker.py` | Create | ~100 |
| 6 | `src/agent_core/observation.py` | Create | ~100 |
| 7 | `src/agent_core/desktop_agent.py` | Edit: wire C+D+E+F | +30 |
| 8 | `src/agent_core/safety/__init__.py` | Edit: exports | +5 |
| 9 | `tests/test_routines/test_routines.py` | Edit: +8 tests | +60 |
| 10 | `tests/test_input/test_input.py` | Edit: +3 tests | +25 |
| 11 | `tests/test_safety/test_action_validator.py` | Create | ~180 |
| 12 | `tests/test_safety/test_timeout_guard.py` | Create | ~100 |
| 13 | `tests/test_safety/test_resource_tracker.py` | Create | ~120 |
| 14 | `tests/test_agent_core/test_observation.py` | Create | ~100 |
| 15 | `pyproject.toml` | Edit: bump v0.16.0 | +1 |

## Expected Outcome

| Metric | Before (v0.15.0) | After (v0.16.0) |
|--------|-------------------|------------------|
| Tests | 2,349 | ~2,399 |
| Cron scheduling | Naive UTC | **Timezone-aware, min interval enforced** |
| Input safety | No `<` bug workaround | **Auto-patched** |
| Action params | Unvalidated | **Range-checked, type-coerced** |
| Timeout tracking | Per-operation `wait_for` | **Shared deadline across steps** |
| Resource leaks | No cleanup | **Tracked + auto-cleaned on session end** |
| Observations | Free-form `data` dict | **Standardized `DesktopObservation`** |
