BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-16
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
Install runtime dependencies (comtypes, pyautogui, mss) and validate
that the Windows desktop adapter can perform real (non-mocked) desktop
automation: launch Notepad, find its window handle, type text, and
capture a screenshot. This batch proves the core loop works on a live
desktop for the first time.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Install comtypes, pyautogui, mss via pip
  - Verify each package imports successfully
  - Create a validated real-dep smoke test that launches Notepad,
    resolves its hwnd, types text via WindowsAdapter, reads it back,
    and captures a screenshot — all without mocks
  - Create a scripts/hello_desktop.py standalone demo

What the code MUST NOT do:
  - Modify any existing source files under src/agent_core/
  - Change the public API of SurfaceAdapter or WindowsAdapter
  - Add new abstract methods to SurfaceAdapter
  - Require LLM API keys (pure desktop interaction only)
  - Leave any Notepad processes running after tests complete

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────
  Lint command:  python -m pytest --co -q

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────
  HB-01: Every launched process (Notepad, Calculator, etc.) MUST be
         terminated in a finally block — no orphan processes allowed.
  HB-02: Real desktop tests MUST be gated behind pytest.mark.integration
         and MUST NOT run under default `pytest` invocation.
  HB-03: No modification to files under src/agent_core/ — new files only
         in tests/ and scripts/.
  HB-04: All 2,914 existing tests MUST continue to pass with zero failures.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────
No new data models. Uses existing:
  - WindowsAdapter(hwnd=int) from agent_core.adapters.windows
  - ActionResult / action_result() from agent_core.results.types
  - AXSnapshot from agent_core.cascade.types

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────
  - WindowsAdapter is the sole adapter under test
  - Tests run on the current Windows desktop session
  - No network calls — purely local desktop interaction

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────
  - BATCH-05 (WindowsAdapter) — must be complete
  - Python 3.11+ on Windows 10/11
  - pip packages: comtypes, pyautogui, mss (to be installed)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────
  Baseline at Blueprint issuance:  2,914 existing tests
  Expected delta (all Tasks):      +15 new tests
  Expected total at Batch close:   2,929

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-16/TASK-01
  Description:      Install runtime dependencies and verify imports
  Files in scope:   (no source files — pip install only)
  Depends on:       None
  Required Tests:
    | Test ID          | Type      | Pass Criteria                          |
    |:-----------------|:----------|:---------------------------------------|
    | TEST-16-01-01    | unit      | import comtypes succeeds               |
    | TEST-16-01-02    | unit      | import pyautogui succeeds              |
    | TEST-16-01-03    | unit      | import mss succeeds                    |
    | TEST-16-01-04    | unit      | WindowsAdapter._ensure_imports() works |
  Acceptance Criteria:
    AC-01-01: comtypes, pyautogui, mss all pip-installed and importable
    AC-01-02: WindowsAdapter._ensure_imports() completes without error
    AC-01-03: All 2,914 existing tests still pass

TASK-02: BATCH-16/TASK-02
  Description:      Create real desktop integration tests — Notepad automation
  Files in scope:   tests/integration/test_real_desktop.py (new)
  Depends on:       TASK-01
  Required Tests:
    | Test ID          | Type        | Pass Criteria                                   |
    |:-----------------|:------------|:------------------------------------------------|
    | TEST-16-02-01    | integration | Launch Notepad and find hwnd via PID             |
    | TEST-16-02-02    | integration | WindowsAdapter created with real hwnd            |
    | TEST-16-02-03    | integration | adapter.type_text("Hello") writes to Notepad     |
    | TEST-16-02-04    | integration | adapter.screenshot() returns valid PNG bytes     |
    | TEST-16-02-05    | integration | adapter.snapshot() returns AXSnapshot with nodes |
    | TEST-16-02-06    | integration | adapter.click("100,100") moves and clicks        |
    | TEST-16-02-07    | integration | adapter.key_press("a") types a character         |
    | TEST-16-02-08    | integration | Notepad terminated in finally block (no orphans) |
  Acceptance Criteria:
    AC-02-01: All 8 integration tests pass with real desktop interaction
    AC-02-02: No Notepad processes left running after test session
    AC-02-03: Tests gated behind pytest.mark.integration

TASK-03: BATCH-16/TASK-03
  Description:      Create standalone demo script and validate full loop
  Files in scope:   scripts/hello_desktop.py (new)
  Depends on:       TASK-02
  Required Tests:
    | Test ID          | Type        | Pass Criteria                                  |
    |:-----------------|:------------|:-----------------------------------------------|
    | TEST-16-03-01    | manual      | python scripts/hello_desktop.py runs end-to-end|
    | TEST-16-03-02    | unit        | Script file exists and is syntactically valid   |
    | TEST-16-03-03    | integration | Script launches, types, captures, exits cleanly |
  Acceptance Criteria:
    AC-03-01: hello_desktop.py runs without error on Windows desktop
    AC-03-02: Script demonstrates: launch → type → screenshot → cleanup
    AC-03-03: Script exits with code 0

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: All 3 Tasks have APPROVED Partial Sign-Offs
  BAC-02: At least 8 real desktop integration tests pass (non-mocked)
  BAC-03: CHANGELOG.md updated with BATCH-16 entry
  BAC-04: All documents archived under /docs/aiv/BATCH-16/

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────
Reviewer Report ID:       REVIEW-BATCH-16-2026-05-03
Review Cycle:             1
Lead Decision:            [x] ACCEPT   [ ] ACCEPT WITH MODIFICATIONS   [ ] REJECT

If ACCEPT WITH MODIFICATIONS — list each Reviewer flag acted on:
  N/A — zero flags raised.

Blueprint Version after response: 1.0
Lead Sign:                Lead AI Instance — 2026-05-03 19:09:00
