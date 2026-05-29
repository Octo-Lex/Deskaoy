BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-20
Blueprint Version:        1.0
Cycle Mode:               SIMPLIFIED
Lead Programmer:          Lead AI Instance
Date Issued:              2026-05-03

SIMPLIFIED CYCLE ELIGIBILITY:
  [x] Exactly 1 Task
  [x] No existing source files modified (new method implementations + new test file)
  [x] No Hard Boundaries required
  [x] Single deliverable

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Add list_displays, list_windows, set_window_bounds, and focus_window
to WindowsAdapter, closing Clawd Cursor patterns P16, P29, P30.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - list_displays(): enumerate monitors with bounds and DPI
  - list_windows(): enumerate top-level visible windows
  - set_window_bounds(x, y, width, height): resize/reposition window
  - focus_window(query): focus by process name/title/PID
  - Add methods to SurfaceAdapter as non-abstract defaults
  - Add 10+ tests

What the code MUST NOT do:
  - Add new abstract methods to SurfaceAdapter
  - Break existing tests

───────────────────────────────────────────────────────────
TASK DEFINITION
───────────────────────────────────────────────────────────
  Description:      Window & display management in WindowsAdapter
  Files in scope:   src/agent_core/cascade/protocol.py (modified)
                    src/agent_core/adapters/windows.py (modified)
                    tests/test_adapters/test_window_management.py (new)
  Required Tests:   10 tests covering all 4 methods
  Acceptance Criteria:
    AC-01: list_displays returns at least 1 display
    AC-02: list_windows returns a list
    AC-03: set_window_bounds repositions a window
    AC-04: focus_window focuses by title

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: 4 new methods implemented
  BAC-02: 10 tests pass
  BAC-03: Documents archived under /docs/aiv/BATCH-20/
