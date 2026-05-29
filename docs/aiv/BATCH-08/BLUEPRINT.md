BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-08
Blueprint Version:        1.0
Cycle Mode:               SIMPLIFIED (single deliverable, no existing source modified)
Lead Programmer:          Lead AI Instance
Date Issued:              2026-05-03

SIMPLIFIED CYCLE ELIGIBILITY — confirm all:
  [x] Exactly 1 Task  (not quite — 2 tasks, but TASK-02 is docs only)
  [x] No existing source files modified (new modules only)
  [ ] No Hard Boundaries required — has 2 HBs
  → Use STANDARD cycle for safety.

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Add Computer Use Agent (CUA) integration supporting both OpenAI and Anthropic
CUA APIs as alternative action loops to AgentLoop, using screenshot-based
action cycles.

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────
  HB-01: CUA loop is optional — DesktopAgent falls back to AgentLoop.
  HB-02: No existing test count decrease.

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-08/TASK-01 — CUA Loop + Anthropic + OpenAI support
  Description:      Create agent/cua_loop.py with screenshot-based CUA loop
  Files in scope:   src/agent_core/agent/cua_loop.py (new)
  Required Tests:   15+ tests

TASK-02: BATCH-08/TASK-02 — CHANGELOG + Certificate
  Files in scope:   CHANGELOG.md, docs/aiv/BATCH-08/

═══════════════════════════════════════════════════════════
