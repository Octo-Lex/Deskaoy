BLUEPRINT
═══════════════════════════════════════════════════════════

Sprint / Batch ID:        BATCH-02
Blueprint Version:        1.0
Lead Programmer:          Lead AI Instance
Date Issued:              2026-04-26
Review SLA:               30 minutes
Execution SLA:            2 hours

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Provide a `scripts/demo_e2e_desktop.py` that demonstrates the full desktop
    agent stack end-to-end: CLI → DesktopAgent → mock surface → result
  - Provide a `scripts/demo_routine_skill_fact.py` that demonstrates routines,
    skills, facts, and soul aspects working together
  - Add integration tests that prove the CLI dispatches correctly through
    the full stack with a mock surface
  - Wire facts_for_context and soul_for_context into the REPL prompt so
    extracted facts appear in subsequent instructions

What the code MUST NOT do:
  - Must NOT require real desktop, real LLM, or real network
  - Must NOT modify any existing production code (only additions)
  - Must NOT add new dependencies

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: All demos and tests MUST use mock surfaces and mock LLMs. No real
         desktop interaction or API calls.

  HB-02: Existing test files MUST NOT be modified. Only new test files allowed.

  HB-03: The demo scripts MUST be runnable via `python scripts/demo_*.py`
         with zero configuration (no env vars needed).

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────
No new types. Uses existing:
  - MockSurface (implements SurfaceAdapter protocol)
  - MockLLM (returns canned responses)
  - DesktopAgent with injected mocks

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────
  AUTH-01: Demo scripts are self-contained. They create mock dependencies
           inline rather than importing from test fixtures.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────
  DEP-01: BATCH-01 (CLI) ✅
  DEP-02: DesktopAgent ✅
  DEP-03: RoutineScheduler ✅
  DEP-04: SkillLoader ✅
  DEP-05: FactStore ✅

───────────────────────────────────────────────────────────
REQUIRED TEST COVERAGE
───────────────────────────────────────────────────────────

| Test ID   | Type        | Pass Criteria                                           |
|:----------|:------------|:--------------------------------------------------------|
| T02-01    | integration | CLI execute with mock surface returns SUCCESS           |
| T02-02    | integration | CLI execute --dry-run returns DRY_RUN status            |
| T02-03    | integration | CLI schedule add + list round-trip via agent             |
| T02-04    | integration | CLI skills list returns discovered skills               |
| T02-05    | integration | CLI facts list returns stored facts                     |
| T02-06    | integration | Full stack: CLI → DesktopAgent → mock surface → result  |
| T02-07    | integration | Demo script imports and runs without error              |
| T02-08    | integration | Demo routine+skill+fact script runs without error       |

───────────────────────────────────────────────────────────
ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  AC-01: `python scripts/demo_e2e_desktop.py` runs and prints results with no errors.
  AC-02: `python scripts/demo_routine_skill_fact.py` runs and prints results with no errors.
  AC-03: All 8 integration tests pass.
  AC-04: No existing tests broken (full suite passes).

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────

Reviewer Report ID:
Review Cycle:
Lead Decision:            [X] ACCEPT

Blueprint Version after response: 1.0
Lead Sign:                Lead AI Instance — 2026-04-26 20:40

═══════════════════════════════════════════════════════════
