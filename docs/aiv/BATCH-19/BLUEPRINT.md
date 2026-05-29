BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-19
Blueprint Version:        1.0
Cycle Mode:               SIMPLIFIED
Lead Programmer:          Lead AI Instance
Date Issued:              2026-05-03
Review SLA:               30 min
Execution SLA:            60 min

SIMPLIFIED CYCLE ELIGIBILITY:
  [x] Exactly 1 Task
  [x] No existing source files modified (only implementations added to existing methods)
  [x] No Hard Boundaries required
  [x] Single deliverable: element operations in WindowsAdapter

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Implement invoke_element (9 actions) and get_element_state (6 properties)
in WindowsAdapter using UI Automation, closing Clawd Cursor patterns P26-P27.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Implement invoke_element with actions: click, focus, set_value, get_value, expand, collapse, toggle, select
  - Implement get_element_state returning enabled, focused, selected, expanded, busy, offscreen
  - Implement get_focused_element returning the focused element ref
  - Add 12+ tests covering all actions and state properties

What the code MUST NOT do:
  - Change SurfaceAdapter protocol signatures
  - Add new abstract methods
  - Break existing tests

───────────────────────────────────────────────────────────
TASK DEFINITION
───────────────────────────────────────────────────────────
  Description:      Implement element operations in WindowsAdapter
  Files in scope:   src/agent_core/adapters/windows.py (modified)
                    tests/test_adapters/test_element_ops.py (new)
  Required Tests:
    | Test ID          | Type | Pass Criteria                                      |
    |:-----------------|:-----|:--------------------------------------------------|
    | TEST-19-01       | unit | invoke_element('btn','click') calls click          |
    | TEST-19-02       | unit | invoke_element('btn','focus') returns ok           |
    | TEST-19-03       | unit | invoke_element('btn','set_value') returns ok       |
    | TEST-19-04       | unit | invoke_element('btn','get_value') returns data     |
    | TEST-19-05       | unit | invoke_element('btn','expand') returns ok          |
    | TEST-19-06       | unit | invoke_element('btn','collapse') returns ok        |
    | TEST-19-07       | unit | invoke_element('btn','toggle') returns ok          |
    | TEST-19-08       | unit | invoke_element('btn','select') returns ok          |
    | TEST-19-09       | unit | invoke_element('btn','unknown') returns not supported |
    | TEST-19-10       | unit | get_element_state returns dict with enabled key     |
    | TEST-19-11       | unit | get_focused_element returns ref or None             |
    | TEST-19-12       | unit | All existing tests still pass                       |
  Acceptance Criteria:
    AC-01: All 9 invoke actions implemented
    AC-02: get_element_state returns 6 properties
    AC-03: 12 tests pass

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: invoke_element supports 9 actions
  BAC-02: get_element_state returns 6 state properties
  BAC-03: All documents archived under /docs/aiv/BATCH-19/

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────
[To be completed after review]
