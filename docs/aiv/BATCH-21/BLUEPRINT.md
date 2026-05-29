BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-21
Blueprint Version:        1.0
Cycle Mode:               SIMPLIFIED
Lead Programmer:          Lead AI Instance
Date Issued:              2026-05-03

SIMPLIFIED CYCLE ELIGIBILITY:
  [x] Exactly 1 Task
  [x] Adds real API integration to existing CUA loop
  [x] No Hard Boundaries required
  [x] Single deliverable

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Wire CUALoop._get_proposal() to real OpenAI/Anthropic API calls
and add real LLM response handling to AgentLoop, with live tests
gated behind API key environment variables.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Implement real OpenAI CUA API call in CUALoop._get_proposal()
  - Implement real Anthropic computer use API call
  - Add live integration tests gated behind OPENAI_API_KEY / ANTHROPIC_API_KEY
  - Tests must skip gracefully when no API key is present

What the code MUST NOT do:
  - Break the existing stub mode (no API key = stub behavior)
  - Require API keys for existing tests to pass
  - Change the CUALoop constructor signature

───────────────────────────────────────────────────────────
TASK DEFINITION
───────────────────────────────────────────────────────────
  Description:      Wire CUA to real APIs + LLM integration tests
  Files in scope:   src/agent_core/agent/cua_loop.py (modified)
                    tests/test_agent/test_cua_live.py (new)
  Required Tests:
    | Test ID    | Type        | Pass Criteria                                    |
    |:-----------|:------------|:-------------------------------------------------|
    | TEST-21-01 | unit        | CUA loop stub mode still works without API key    |
    | TEST-21-02 | unit        | _get_proposal returns DONE when no adapter        |
    | TEST-21-03 | unit        | OpenAI parser handles tool_calls format            |
    | TEST-21-04 | unit        | Anthropic parser handles content blocks            |
    | TEST-21-05 | unit        | _execute_action dispatches click correctly         |
    | TEST-21-06 | integration | Live CUA loop with OpenAI (skips without key)     |
    | TEST-21-07 | integration | Live CUA loop with Anthropic (skips without key)   |
  Acceptance Criteria:
    AC-01: CUA loop works in stub mode without API keys
    AC-02: Live tests skip gracefully without API keys
    AC-03: Response parsers handle real API response formats

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: CUA loop has real API integration (OpenAI + Anthropic)
  BAC-02: 7 tests pass (unit tests always, integration skip without keys)
  BAC-03: Documents archived under /docs/aiv/BATCH-21/
