BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-10
Blueprint Version:        1.0
Cycle Mode:               STANDARD
Lead Programmer:          Lead AI Instance
Date Issued:              2026-05-03

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Add a real-world evaluation framework with OSWorld-compatible task format,
JSON task definitions, built-in evaluators, and a benchmark runner for
scoring DesktopAgent performance on desktop tasks.

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────
  HB-01: Task definitions are pure JSON — no executable code in task files.
  HB-02: Evaluators are deterministic — same input always produces same score.
  HB-03: No external dependencies (pure stdlib).
  HB-04: Existing test count of 2,752 MUST NOT decrease.

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: Evaluation framework (task format + evaluators + runner)
TASK-02: Sample task suite (10 Windows desktop tasks)
TASK-03: CHANGELOG + Certificate

═══════════════════════════════════════════════════════════
