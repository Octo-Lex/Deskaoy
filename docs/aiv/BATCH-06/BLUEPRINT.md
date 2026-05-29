BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-06
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
Add two-step action verification (Stagehand pattern) and snapshot diffing
so the agent can verify actions succeeded and only send changed state to
the LLM — reducing token cost and improving reliability of multi-step
desktop automation.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - After each action in AgentLoop, take a new observation and compute diff
  - TwoStepVerifier: compare pre/post snapshots, classify the change
  - SnapshotDiffer: compute structural diff between two AXSnapshot objects
  - Diff format: added elements, removed elements, changed elements (value, state)
  - Token savings: send only diff to LLM instead of full tree on subsequent steps
  - AgentLoop integrates two-step mode via `two_step=True` constructor option
  - Two-step mode captures a post-action snapshot and appends diff to step context
  - All existing 2,657 tests continue to pass

What the code MUST NOT do:
  - Must NOT break any existing test
  - Must NOT change AgentLoop's default behavior (two_step defaults to False)
  - Must NOT change the AXSnapshot or AXNode dataclass definitions
  - Must NOT require LLM calls for diff computation (purely structural)
  - Must NOT touch super_browser code
  - Must NOT add new dependencies

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────
  Lint command:  python -m pytest --tb=line -q 2>&1 | tail -3

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────
  HB-01: AgentLoop two_step defaults to False — existing behavior unchanged.
  HB-02: SnapshotDiffer MUST be pure Python with no external dependencies.
  HB-03: Every new module MUST have at least 2 unit tests.
  HB-04: The existing test count of 2,657 MUST NOT decrease.
  HB-05: Diff output MUST be a plain string, not a JSON blob — LLM-readable.
  HB-06: No file outside src/agent_core/ may be modified except test files,
         CHANGELOG.md, and docs/aiv/BATCH-06/.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

SnapshotDiff (cascade/differ.py — new):
  added: list[AXNode]      — elements present in 'after' but not 'before'
  removed: list[AXNode]     — elements present in 'before' but not 'after'
  changed: list[NodeDiff]   — elements present in both but with different state

NodeDiff:
  ref: str                  — element reference (e.g., "e42")
  field: str                — which field changed ("value", "name", "disabled", etc.)
  before: str               — previous value
  after: str                — new value

SnapshotDiffer:
  diff(before: AXSnapshot, after: AXSnapshot) -> SnapshotDiff
  diff_to_text(diff: SnapshotDiff) -> str    — LLM-readable format
  is_significant(diff: SnapshotDiff) -> bool  — True if any meaningful change

TwoStepVerifier (agent/two_step.py — new):
  verify(before: AXSnapshot, after: AXSnapshot, action: str, target: str) -> TwoStepResult
  TwoStepResult:
    action_applied: bool     — did the action have the intended effect?
    evidence: str            — human-readable evidence
    diff: SnapshotDiff       — structural diff
    confidence: float        — 0.0–1.0 confidence the action succeeded

AgentLoop additions (agent/loop.py):
  Constructor: two_step: bool = False
  When two_step=True:
    - After each action dispatch, capture post-snapshot
    - Compute diff between pre/post
    - Append diff text to next LLM prompt
    - Track verification results per step

StepResult additions (agent/types.py):
  verification: Optional[TwoStepResult] = None
  diff_summary: Optional[str] = None

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────
  - Two-step verification is advisory — it does NOT block or retry actions
  - Diff computation is deterministic (no LLM involved)
  - Verification confidence < 0.5 means "inconclusive" (not "failed")
  - AgentLoop still decides what to do based on verification results

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────
  BATCH-05 (CLI + Safety + Transports): DONE
  agent/loop.py (AgentLoop): exists, 562 lines
  cascade/types.py (AXSnapshot, AXNode): exists, stable
  cascade/formatter.py (format_snapshot): exists, used by differ

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────
  Baseline at Blueprint issuance:  2,657 existing tests
  Expected delta (all Tasks):      +35 new tests
  Expected total at Batch close:   ~2,692

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-06/TASK-01 — Snapshot Differ
  Description:      Create cascade/differ.py with structural diff between two
                    AXSnapshot objects. Pure Python, no dependencies.
  Files in scope:   src/agent_core/cascade/differ.py (new)
  Depends on:       None
  Required Tests:
    | Test ID          | Type | Pass Criteria                                    |
    |:-----------------|:-----|:-------------------------------------------------|
    | TEST-06-01-01    | unit | Identical snapshots produce empty diff            |
    | TEST-06-01-02    | unit | Added element detected in 'after' snapshot        |
    | TEST-06-01-03    | unit | Removed element detected from 'before' snapshot   |
    | TEST-06-01-04    | unit | Changed value detected (field, before, after)     |
    | TEST-06-01-05    | unit | diff_to_text produces readable output             |
    | TEST-06-01-06    | unit | is_significant returns False for empty diff       |
    | TEST-06-01-07    | unit | is_significant returns True for added/changed     |
    | TEST-06-01-08    | unit | Large diff (>50 nodes) truncates output           |
    | TEST-06-01-09    | unit | Diff handles empty snapshots gracefully            |
  Acceptance Criteria:
    AC-01-01: SnapshotDiffer.diff() returns SnapshotDiff dataclass
    AC-01-02: diff_to_text() output is <500 chars for typical diffs
    AC-01-03: No external dependencies (stdlib + cascade/types only)
    AC-01-04: All 9 tests pass

TASK-02: BATCH-06/TASK-02 — Two-Step Verifier
  Description:      Create agent/two_step.py with TwoStepVerifier that uses
                    SnapshotDiffer to classify whether an action succeeded.
  Files in scope:   src/agent_core/agent/two_step.py (new)
  Depends on:       TASK-01 (SnapshotDiffer)
  Required Tests:
    | Test ID          | Type | Pass Criteria                                    |
    |:-----------------|:-----|:-------------------------------------------------|
    | TEST-06-02-01    | unit | verify() returns TwoStepResult with confidence    |
    | TEST-06-02-02    | unit | Click on button detected as applied when element removed |
    | TEST-06-02-03    | unit | Fill detected as applied when value changes       |
    | TEST-06-02-04    | unit | Inconclusive when no detectable change            |
    | TEST-06-02-05    | unit | Evidence string is human-readable                 |
    | TEST-06-02-06    | unit | Confidence is between 0.0 and 1.0                |
    | TEST-06-02-07    | unit | verify() handles empty snapshots                  |
  Acceptance Criteria:
    AC-02-01: TwoStepResult has action_applied, evidence, diff, confidence
    AC-02-02: Verify works for click, fill, type_text, key_press, scroll actions
    AC-02-03: All 7 tests pass

TASK-03: BATCH-06/TASK-03 — AgentLoop Integration
  Description:      Add two_step mode to AgentLoop that captures post-action
                    snapshots and appends diff context to LLM prompts.
  Files in scope:   src/agent_core/agent/loop.py,
                    src/agent_core/agent/types.py
  Depends on:       TASK-02 (TwoStepVerifier)
  Required Tests:
    | Test ID          | Type       | Pass Criteria                                    |
    |:-----------------|:-----------|:-------------------------------------------------|
    | TEST-06-03-01    | unit       | AgentLoop accepts two_step=True constructor       |
    | TEST-06-03-02    | unit       | two_step=False preserves existing behavior        |
    | TEST-06-03-03    | unit       | StepResult has verification field                |
    | TEST-06-03-04    | unit       | StepResult has diff_summary field                |
    | TEST-06-03-05    | unit       | _build_prompt includes diff context when enabled  |
    | TEST-06-03-06    | unit       | Post-action snapshot captured when two_step=True  |
    | TEST-06-03-07    | unit       | Diff appended to prompt context                   |
    | TEST-06-03-08    | integration| Full loop with two_step produces verified steps   |
  Acceptance Criteria:
    AC-03-01: Default behavior unchanged (two_step defaults to False)
    AC-03-02: When enabled, each step gets verification result
    AC-03-03: Diff text appended to LLM prompt for next step
    AC-03-04: All existing tests pass (no regressions)

TASK-04: BATCH-06/TASK-04 — CHANGELOG + Certificate
  Description:      Update CHANGELOG.md with BATCH-06 entry, write certificate.
  Files in scope:   CHANGELOG.md, docs/aiv/BATCH-06/ (all AIV docs)
  Depends on:       TASK-01 through TASK-03
  Required Tests:
    | Test ID          | Type | Pass Criteria                                |
    |:-----------------|:-----|:---------------------------------------------|
    | TEST-06-04-01    | unit | Full test suite passes (0 failures)          |
  Acceptance Criteria:
    AC-04-01: CHANGELOG.md updated with BATCH-06 entry
    AC-04-02: All AIV documents archived under docs/aiv/BATCH-06/
    AC-04-03: Version bumped to 0.20.0

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: All 2,657+ tests pass with 0 failures
  BAC-02: SnapshotDiffer produces deterministic, LLM-readable diffs
  BAC-03: TwoStepVerifier classifies action outcomes with confidence scores
  BAC-04: AgentLoop two_step mode is backward-compatible (opt-in)
  BAC-05: CHANGELOG.md updated with BATCH-06 entry
  BAC-06: All documents archived under /docs/aiv/BATCH-06/

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────
[To be completed after Phase I-B review]

═══════════════════════════════════════════════════════════
