BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-18
Blueprint Version:        1.0
Cycle Mode:               STANDARD
Lead Programmer:          Lead AI Instance
Date Issued:              2026-05-03
Review SLA:               30 min
Execution SLA per Task:   60 min
Partial Sign-Off SLA:     15 min
Task Sequencing:          Sequential

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Add low-level input primitives (mouse_down, mouse_up, mouse_drag,
key_down, key_up) to the SurfaceAdapter protocol and implement them
in WindowsAdapter, closing Clawd Cursor pattern gaps P23-P25.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Add 5 new abstract methods to SurfaceAdapter: mouse_down, mouse_up,
    mouse_drag, key_down, key_up
  - Implement all 5 in WindowsAdapter using pyautogui
  - Add key blocklist checks to key_down (same as key_press)
  - Wire new methods into the agent tool registry

What the code MUST NOT do:
  - Change the signature of existing methods (click, key_press, etc.)
  - Remove or rename any existing methods
  - Require any new pip dependencies

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────
  Lint command:  python -m pytest --co -q

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────
  HB-01: key_down MUST check the key blocklist before executing.
  HB-02: All 5 new methods MUST have dry_run support.
  HB-03: No existing tests may break — backward compatibility is absolute.
  HB-04: mouse_drag MUST validate start/end points are within target window.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────
  SurfaceAdapter (agent_core.cascade.protocol):
    + mouse_down(button: str = "left") -> ActionResult
    + mouse_up(button: str = "left") -> ActionResult
    + mouse_drag(start: str, end: str, *, button: str = "left") -> ActionResult
    + key_down(key: str, modifiers: int = 0) -> ActionResult
    + key_up(key: str, modifiers: int = 0) -> ActionResult

  WindowsAdapter (agent_core.adapters.windows):
    Implements all 5 with pyautogui.mouseDown/mouseUp/drag/keyDown/keyUp.

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────
  - New methods follow the same ActionResult pattern as existing methods
  - Blocklist checks mirror key_press logic

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────
  - BATCH-05 (SurfaceAdapter protocol)
  - BATCH-16 (pyautogui installed and verified)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────
  Baseline at Blueprint issuance:  2,882 passing tests
  Expected delta (all Tasks):      +30 new tests
  Expected total at Batch close:   2,912

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-18/TASK-01
  Description:      Add abstract methods to SurfaceAdapter and implement in WindowsAdapter
  Files in scope:   src/agent_core/cascade/protocol.py (modified)
                    src/agent_core/adapters/windows.py (modified)
  Depends on:       None
  Required Tests:
    | Test ID          | Type | Pass Criteria                                    |
    |:-----------------|:-----|:-------------------------------------------------|
    | TEST-18-01-01    | unit | SurfaceAdapter has mouse_down abstract method     |
    | TEST-18-01-02    | unit | SurfaceAdapter has mouse_up abstract method       |
    | TEST-18-01-03    | unit | SurfaceAdapter has mouse_drag abstract method     |
    | TEST-18-01-04    | unit | SurfaceAdapter has key_down abstract method       |
    | TEST-18-01-05    | unit | SurfaceAdapter has key_up abstract method         |
    | TEST-18-01-06    | unit | WindowsAdapter.mouse_down calls pyautogui         |
    | TEST-18-01-07    | unit | WindowsAdapter.mouse_up calls pyautogui           |
    | TEST-18-01-08    | unit | WindowsAdapter.mouse_drag calls pyautogui         |
    | TEST-18-01-09    | unit | WindowsAdapter.key_down calls pyautogui           |
    | TEST-18-01-10    | unit | WindowsAdapter.key_up calls pyautogui             |
    | TEST-18-01-11    | unit | key_down blocks Alt+F4 via blocklist              |
    | TEST-18-01-12    | unit | mouse_drag dry_run returns without executing       |
    | TEST-18-01-13    | unit | key_down dry_run returns without executing         |
  Acceptance Criteria:
    AC-01-01: All 5 abstract methods added to SurfaceAdapter
    AC-01-02: All 5 implemented in WindowsAdapter
    AC-01-03: key_down checks blocklist
    AC-01-04: All 13 new tests pass
    AC-01-05: All existing tests still pass

TASK-02: BATCH-18/TASK-02
  Description:      Wire new methods into agent tool registry and add integration tests
  Files in scope:   src/agent_core/agent/types.py (modified if needed)
                    tests/test_adapters/test_low_level_input.py (new)
  Depends on:       TASK-01
  Required Tests:
    | Test ID          | Type        | Pass Criteria                                  |
    |:-----------------|:------------|:-----------------------------------------------|
    | TEST-18-02-01    | unit        | Tool registry exposes mouse_down                |
    | TEST-18-02-02    | unit        | Tool registry exposes key_down                  |
    | TEST-18-02-03    | integration | Real mouse_down/up cycle on Notepad             |
    | TEST-18-02-04    | integration | Real key_down/up cycle on Notepad               |
    | TEST-18-02-05    | integration | Real mouse_drag on Paint                        |
  Acceptance Criteria:
    AC-02-01: Tool registry has entries for new methods
    AC-02-02: Integration tests pass with real desktop
    AC-02-03: All existing tests still pass

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: All 2 Tasks have APPROVED Partial Sign-Offs
  BAC-02: 5 new methods in SurfaceAdapter protocol + WindowsAdapter
  BAC-03: CHANGELOG.md updated with BATCH-18 entry
  BAC-04: All documents archived under /docs/aiv/BATCH-18/

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────
[To be completed after review]
