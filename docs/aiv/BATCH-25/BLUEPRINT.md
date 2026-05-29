# BATCH-25 BLUEPRINT — Action-First Windows Automation

**Batch:**                BATCH-25
**Version:**              v0.32.0 → v0.33.0
**Cycle Type:**           STANDARD
**AIV Framework:**        v5.2
**Date:**                 2026-05-10
**Lead:**                 Craft Agent (Lead Override per §5.3)
**Blueprint Version:**    1.1

---

## 1. Batch Identity

**Batch Name:**           Action-First Windows Automation
**Strategic Bet:**        AX/UIA pattern-based actions before pyautogui synthetic input — faster, DPI-independent, position-agnostic. Peekaboo pattern gap #2.
**Priority:**             HIGH

**Context:**              Peekaboo uses accessibility actions as the primary interaction method, falling back to synthetic input only when accessibility isn't available. Desktop-Agent currently does the reverse: click/fill/type always use pyautogui coordinate-based input, with UIA only used for element resolution. This batch inverts the order.

---

## 2. Scope

### In Scope
- Add UIA pattern helpers: InvokePattern, ValuePattern, TogglePattern, ExpandCollapsePattern, SelectionItemPattern, ScrollItemPattern
- Refactor `click()` in WindowsAdapter to try InvokePattern first, fallback to pyautogui
- Refactor `invoke_element()` to use pattern-based actions for all supported actions
- Refactor `fill()` / `type_text()` to try ValuePattern first, fallback to synthetic typing
- Add `invoke_action()` method to UIAWalker for clean pattern dispatch
- Add `find_element_by_element_id()` in UIAWalker that resolves snapshot element IDs
- Tests for all new pattern helpers and refactored methods

### Out of Scope
- macOS / Linux adapter changes
- New CLI commands
- Snapshot Store changes (BATCH-24 delivered this)
- Performance benchmarking (BATCH-31)

---

## 3. Hard Boundaries

| ID  | Constraint |
|-----|-----------|
| HB-01 | pyautogui fallback must be preserved — UIA patterns are optional |
| HB-02 | Existing test signatures must not change |
| HB-03 | No new required dependencies |
| HB-04 | All 2,999 baseline tests must pass |

---

## 4. Data Models

### UIA Pattern Helper Results

```python
@dataclass
class PatternActionResult:
    """Result of a UIA pattern-based action."""
    success: bool
    pattern_used: str          # "InvokePattern", "ValuePattern", etc.
    fallback_used: bool        # True if fell back to pyautogui
    element_id: Optional[str]  # Snapshot element ID if resolved
    error: Optional[str] = None
```

### Pattern Constants

```python
# UIA Pattern IDs (Windows UI Automation)
UIA_INVOKE_PATTERN_ID = 10000
UIA_VALUE_PATTERN_ID = 10002
UIA_TOGGLE_PATTERN_ID = 10004
UIA_EXPAND_COLLAPSE_PATTERN_ID = 10005
UIA_SELECTION_ITEM_PATTERN_ID = 10010
UIA_SCROLL_ITEM_PATTERN_ID = 10017
```

---

## 5. Task Sequence

**Sequencing:** SEQUENTIAL (T01 → T02 → T03 → T04)

### TASK-01: UIA Pattern Helpers in uia_walker.py

**Description:** Add pattern action methods to `UIAWalker` that directly invoke UIA patterns on elements.

**New Methods:**
| Method | Pattern | Action |
|--------|---------|--------|
| `invoke_element(el)` | InvokePattern | Click/activate element |
| `set_value(el, value)` | ValuePattern | Set text value directly |
| `get_value(el)` | ValuePattern | Read current value |
| `toggle_element(el)` | TogglePattern | Toggle check/radio |
| `expand_element(el)` | ExpandCollapsePattern | Expand combo/tree |
| `collapse_element(el)` | ExpandCollapsePattern | Collapse combo/tree |
| `select_element(el)` | SelectionItemPattern | Select item in list |
| `scroll_into_view(el)` | ScrollItemPattern | Scroll to make visible |

**Files Modified:**
- `src/agent_core/adapters/uia_walker.py` — Add ~150 lines of pattern helpers

**Expected Tests:** 12
- 8 pattern helper unit tests (mock comtypes patterns)
- 2 element resolution tests (find by name, by AutomationId)
- 2 fallback tests (pattern not available → returns None)

**Acceptance Criteria:**
- AC-01-01: All 8 pattern helpers callable with UIAElement
- AC-01-02: Each helper returns PatternActionResult or None if pattern unsupported
- AC-01-03: Existing UIAWalker tests still pass

---

### TASK-02: find_element_by_element_id in UIAWalker

**Description:** Add a method to resolve snapshot element IDs (from BATCH-24) to UIA elements. This bridges the snapshot state system with the action-first system.

**Method:**
```python
def find_element_by_element_id(self, hwnd: int, element_id: str) -> Optional[UIAElement]:
    """Resolve a snapshot element ID (E1, T2, B3) to a UIA element.
    
    Uses the deterministic element ordering from assign_element_ids()
    to find the Nth element matching the role prefix.
    """
```

**Logic:**
1. Parse element_id prefix (E/T/B/M/C/S) → filter roles
2. Parse element_id number → Nth match
3. Walk UIA tree, filter by role, return Nth match

**Files Modified:**
- `src/agent_core/adapters/uia_walker.py` — Add `find_element_by_element_id()`
- `src/agent_core/cascade/snapshot_types.py` — Export `_ROLE_PREFIXES` and `_ROLE_ALIASES` for walker to use

**Expected Tests:** 8
- 2 prefix parsing tests
- 3 role mapping tests (B→button, T→textbox, E→fallback)
- 2 Nth-element tests (B1=first button, B2=second button)
- 1 not-found test

**Acceptance Criteria:**
- AC-02-01: Element IDs resolve to correct UIA elements
- AC-02-02: Unknown IDs return None gracefully
- AC-02-03: Deterministic — same tree always maps same IDs

---

### TASK-03: Refactor WindowsAdapter to Action-First

**Description:** Refactor `click()`, `fill()`, and `invoke_element()` to try UIA patterns first, falling back to pyautogui only when patterns are unavailable.

**Refactored Methods:**

#### `click()` — Action-First Click
```
1. Resolve target to UIA element (if name/id, not coordinates)
2. Try UIA InvokePattern.Invoke()
3. If InvokePattern not available, fallback to pyautogui
4. If target was coordinates, always use pyautogui
```

#### `fill()` — Action-First Fill
```
1. Resolve target to UIA element
2. Try ValuePattern.SetValue(value)
3. If ValuePattern not available, fallback to click + type
4. Return result with pattern_used flag
```

#### `invoke_element()` — Action-First Invoke
```
1. For "click": try InvokePattern, fallback to pyautogui click
2. For "toggle": try TogglePattern.Toggle(), fallback to click
3. For "expand": try ExpandCollapsePattern.Expand(), fallback to click
4. For "collapse": try ExpandCollapsePattern.Collapse(), fallback to click
5. For "select": try SelectionItemPattern.Select(), fallback to click
6. For "set_value": try ValuePattern.SetValue(), fallback to click+type
7. For "get_value": try ValuePattern, fallback to snapshot
8. For "focus": try SetFocus(), fallback to click
```

**Files Modified:**
- `src/agent_core/adapters/windows.py` — Refactor click/fill/invoke_element (~200 lines changed)

**Expected Tests:** 15
- 5 click tests (InvokePattern hit, InvokePattern miss→pyautogui, coordinate target→pyautogui, dry_run, abort check)
- 4 fill tests (ValuePattern hit, ValuePattern miss→click+type, dry_run, error handling)
- 5 invoke_element tests (toggle pattern, expand pattern, set_value pattern, fallback for each, unknown action)
- 1 integration test (action-first click + fallback in same session)

**Acceptance Criteria:**
- AC-03-01: click() uses InvokePattern when available, pyautogui otherwise
- AC-03-02: fill() uses ValuePattern when available, click+type otherwise
- AC-03-03: invoke_element() dispatches to correct pattern for each action
- AC-03-04: ActionResult.data includes `pattern_used` and `fallback_used` fields
- AC-03-05: All existing click/fill/invoke_element tests still pass (same signatures)

---

### TASK-04: Tests, Version Bump, Integration

**Description:** Integration tests, version bump, full suite validation.

**Files:**
- `tests/test_adapters/test_action_first.py` — All new tests in one file (~35 tests)
- `src/agent_core/cli/version.py` — 0.32.0 → 0.33.0
- `pyproject.toml` — version 0.32.0 → 0.33.0

**Expected Tests:** 3 (version check, full suite count, regression check)
- These are real pytest tests that validate version bump and suite integrity
- Total new tests across all tasks: 12 + 8 + 15 + 3 = 38

**Acceptance Criteria:**
- AC-04-01: Version is 0.33.0 in both files
- AC-04-02: Full test suite passes: 3,037 (2,999 baseline + 38 new)
- AC-04-03: No regression in existing tests

---

## 6. Acceptance Criteria Summary

| AC ID | Criterion | Task |
|-------|-----------|------|
| AC-01-01 | All 8 pattern helpers callable | TASK-01 |
| AC-01-02 | Helpers return PatternActionResult or None | TASK-01 |
| AC-01-03 | Existing UIAWalker tests pass | TASK-01 |
| AC-02-01 | Element IDs resolve to correct UIA elements | TASK-02 |
| AC-02-02 | Unknown IDs return None | TASK-02 |
| AC-02-03 | Deterministic mapping | TASK-02 |
| AC-03-01 | click() uses InvokePattern when available | TASK-03 |
| AC-03-02 | fill() uses ValuePattern when available | TASK-03 |
| AC-03-03 | invoke_element() dispatches to correct pattern | TASK-03 |
| AC-03-04 | ActionResult includes pattern_used + fallback_used | TASK-03 |
| AC-03-05 | Existing click/fill/invoke tests pass | TASK-03 |
| AC-04-01 | Version is 0.33.0 | TASK-04 |
| AC-04-02 | Full suite: 3,034 pass | TASK-04 |
| AC-04-03 | No regression | TASK-04 |

---

## 7. Test Traceability Matrix

| Test ID | Type | Description | AC |
|---------|------|-------------|----|
| TEST-25-01-01 | unit | invoke_element pattern helper success | AC-01-01 |
| TEST-25-01-02 | unit | set_value pattern helper success | AC-01-01 |
| TEST-25-01-03 | unit | get_value pattern helper returns string | AC-01-01 |
| TEST-25-01-04 | unit | toggle_element pattern helper success | AC-01-01 |
| TEST-25-01-05 | unit | expand_element pattern helper success | AC-01-01 |
| TEST-25-01-06 | unit | collapse_element pattern helper success | AC-01-01 |
| TEST-25-01-07 | unit | select_element pattern helper success | AC-01-01 |
| TEST-25-01-08 | unit | scroll_into_view pattern helper success | AC-01-01 |
| TEST-25-01-09 | unit | Pattern helper returns None when unavailable | AC-01-02 |
| TEST-25-01-10 | unit | find_element_by_name returns UIAElement | AC-01-03 |
| TEST-25-01-11 | unit | find_element_by_automation_id returns UIAElement | AC-01-03 |
| TEST-25-01-12 | unit | Existing UIAWalker tests pass | AC-01-03 |
| TEST-25-02-01 | unit | Element ID prefix parsing E/T/B/M/C/S | AC-02-01 |
| TEST-25-02-02 | unit | Role mapping B→button, T→textbox | AC-02-01 |
| TEST-25-02-03 | unit | Nth element: B1=first button, B2=second | AC-02-01 |
| TEST-25-02-04 | unit | Unknown element ID returns None | AC-02-02 |
| TEST-25-02-05 | unit | Deterministic: same tree → same IDs | AC-02-03 |
| TEST-25-02-06 | unit | E-prefix matches any role | AC-02-01 |
| TEST-25-02-07 | unit | M-prefix matches menu/menuitem | AC-02-01 |
| TEST-25-02-08 | unit | Invalid ID format returns None | AC-02-02 |
| TEST-25-03-01 | unit | click with InvokePattern available | AC-03-01 |
| TEST-25-03-02 | unit | click falls back to pyautogui | AC-03-01 |
| TEST-25-03-03 | unit | click coordinate target uses pyautogui | AC-03-01 |
| TEST-25-03-04 | unit | click dry_run still works | AC-03-05 |
| TEST-25-03-05 | unit | fill with ValuePattern available | AC-03-02 |
| TEST-25-03-06 | unit | fill falls back to click+type | AC-03-02 |
| TEST-25-03-07 | unit | invoke toggle uses TogglePattern | AC-03-03 |
| TEST-25-03-08 | unit | invoke expand uses ExpandCollapsePattern | AC-03-03 |
| TEST-25-03-09 | unit | invoke set_value uses ValuePattern | AC-03-03 |
| TEST-25-03-10 | unit | invoke unknown action returns error | AC-03-03 |
| TEST-25-03-11 | unit | ActionResult has pattern_used field | AC-03-04 |
| TEST-25-03-12 | unit | ActionResult has fallback_used field | AC-03-04 |
| TEST-25-03-13 | unit | Existing click tests pass | AC-03-05 |
| TEST-25-03-14 | unit | Existing fill tests pass | AC-03-05 |
| TEST-25-03-15 | unit | Existing invoke_element tests pass | AC-03-05 |
| TEST-25-04-01 | unit | Version is 0.33.0 | AC-04-01 |
| TEST-25-04-02 | unit | Full suite passes: 3,034 | AC-04-02 |
| TEST-25-04-03 | unit | No test regressions | AC-04-03 |

---

## 8. Baseline Metrics

| Metric | Value |
|--------|-------|
| Version at Batch start:       | v0.32.0 |
| Test count at Batch start:    | 2,999 passing |
| Source files at Batch start:  | 264 Python files |
| Expected delta (all Tasks):   | +38 new tests |
| Expected total at Batch close:| 3,037 |

---

## 9. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| UIA patterns not available on target element | LOW | Always preserve pyautogui fallback |
| comtypes pattern QueryInterface fails | LOW | Try/except around every pattern call |
| Refactored click changes behavior | MEDIUM | Keep existing signature, add pattern_used metadata |
| Element ID resolution walks tree multiple times | LOW | Cache walker results per session |

---

## 10. Reviewer Notes

Reviewer Report ID:       REVIEW-BATCH-25-2026-05-10
Review Cycle:             1
Lead Decision:            [x] ACCEPT WITH MODIFICATIONS

If ACCEPT WITH MODIFICATIONS — list each Reviewer flag acted on:
  FLAG-01 (CHK-08) → Test delta corrected from +35 to +38 (3 validation tests in TASK-04 are real pytest tests)
  FLAG-02 (CHK-08) → TASK-04 test count updated from 0 to 3, total suite target 3,037

Blueprint Version after response: 1.1
Lead Sign:                Craft Agent — 2026-05-10

---

**BAC-06:** Full test suite passes: 3,037 tests (2,999 baseline + 38 new).
