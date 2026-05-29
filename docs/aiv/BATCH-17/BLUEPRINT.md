BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-17
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
Expand the real E2E test suite to cover 5 Windows applications
(Notepad, Calculator, Explorer, Paint, Settings) and validate
the MCP and REST transports work with real requests.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Add real E2E tests for Calculator (button clicks, result readback)
  - Add real E2E tests for Explorer (folder navigation)
  - Add real E2E tests for Paint (canvas interaction)
  - Add a transport validation test for MCP stdio (real subprocess)
  - Add a transport validation test for REST HTTP (real server start/stop)

What the code MUST NOT do:
  - Modify any existing source files under src/agent_core/
  - Require LLM API keys
  - Leave any launched processes running after tests

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────
  Lint command:  python -m pytest --co -q

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────
  HB-01: Every launched process MUST be terminated in a finally block.
  HB-02: All real desktop tests MUST be gated behind pytest.mark.integration.
  HB-03: No modification to files under src/agent_core/ -- new files only.
  HB-04: All existing tests MUST continue to pass with zero failures.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────
No new data models. Uses existing WindowsAdapter, ActionResult, AXSnapshot.

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────
  - WindowsAdapter is the sole adapter under test
  - MCP transport tested via subprocess
  - REST transport tested via aiohttp test client

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────
  - BATCH-16 (real deps installed, Notepad E2E proven)
  - Python 3.11+ on Windows 10/11

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────
  Baseline at Blueprint issuance:  2,926 existing tests
  Expected delta (all Tasks):      +20 new tests
  Expected total at Batch close:   2,946

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-17/TASK-01
  Description:      Add Calculator and Explorer E2E tests
  Files in scope:   tests/integration/test_real_calculator.py (new)
                    tests/integration/test_real_explorer.py (new)
  Depends on:       None
  Required Tests:
    | Test ID          | Type        | Pass Criteria                                      |
    |:-----------------|:------------|:---------------------------------------------------|
    | TEST-17-01-01    | integration | Launch Calculator and find window                   |
    | TEST-17-01-02    | integration | Click number buttons via adapter.click()            |
    | TEST-17-01-03    | integration | Snapshot shows calculator buttons                   |
    | TEST-17-01-04    | integration | Screenshot returns valid PNG                        |
    | TEST-17-01-05    | integration | Calculator terminated in finally block              |
    | TEST-17-01-06    | integration | Launch Explorer and find window                     |
    | TEST-17-01-07    | integration | Explorer snapshot has file listing nodes            |
    | TEST-17-01-08    | integration | Explorer screenshot returns valid PNG               |
    | TEST-17-01-09    | integration | Explorer terminated in finally block                |
  Acceptance Criteria:
    AC-01-01: All 9 Calculator/Explorer tests pass with real interaction
    AC-01-02: No orphan processes

TASK-02: BATCH-17/TASK-02
  Description:      Add Paint E2E test and transport validation
  Files in scope:   tests/integration/test_real_paint.py (new)
                    tests/integration/test_transport_live.py (new)
  Depends on:       TASK-01
  Required Tests:
    | Test ID          | Type        | Pass Criteria                                      |
    |:-----------------|:------------|:---------------------------------------------------|
    | TEST-17-02-01    | integration | Launch Paint (mspaint) and find window              |
    | TEST-17-02-02    | integration | Paint screenshot returns valid PNG                  |
    | TEST-17-02-03    | integration | Paint snapshot has canvas element                   |
    | TEST-17-02-04    | integration | Paint terminated in finally block                   |
    | TEST-17-02-05    | integration | MCP subprocess starts and responds to JSON-RPC      |
    | TEST-17-02-06    | integration | REST server starts and /health returns 200          |
    | TEST-17-02-07    | integration | REST /execute endpoint accepts goal                 |
    | TEST-17-02-08    | integration | REST server stops cleanly                           |
  Acceptance Criteria:
    AC-02-01: All 8 Paint and transport tests pass
    AC-02-02: No orphan processes or hanging servers

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: All 2 Tasks have APPROVED Partial Sign-Offs
  BAC-02: At least 17 real E2E tests pass across 5 applications
  BAC-03: CHANGELOG.md updated with BATCH-17 entry
  BAC-04: All documents archived under /docs/aiv/BATCH-17/

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────
[To be completed after review]
