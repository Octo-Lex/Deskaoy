BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-22
Blueprint Version:        1.0
Cycle Mode:               SIMPLIFIED
Lead Programmer:          Lead AI Instance
Date Issued:              2026-05-03

SIMPLIFIED CYCLE ELIGIBILITY:
  [x] Exactly 1 Task
  [x] No source files modified (packaging config only)
  [x] No Hard Boundaries required
  [x] Single deliverable

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Validate the package builds cleanly, passes twine checks,
and is ready for PyPI upload.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - python -m build produces wheel and sdist without errors
  - twine check passes on both artifacts
  - Verify all entry points work in the built wheel
  - Test dry-run upload to TestPyPI (optional)

What the code MUST NOT do:
  - Modify any source code
  - Actually upload to PyPI (dry run only)

───────────────────────────────────────────────────────────
TASK DEFINITION
───────────────────────────────────────────────────────────
  Description:      Validate package build and PyPI readiness
  Files in scope:   (build artifacts in dist/ only)
  Required Tests:
    | Test ID    | Type | Pass Criteria                                    |
    |:-----------|:-----|:-------------------------------------------------|
    | TEST-22-01 | unit | python -m build succeeds                          |
    | TEST-22-02 | unit | Wheel contains agent_core package                 |
    | TEST-22-03 | unit | Entry point desktop-agent is in wheel metadata    |
    | TEST-22-04 | unit | twine check passes on wheel and sdist             |
  Acceptance Criteria:
    AC-01: Package builds cleanly
    AC-02: All entry points present
    AC-03: twine check passes

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: Package builds without errors
  BAC-02: 4 tests pass
  BAC-03: Documents archived under /docs/aiv/BATCH-22/
