# BATCH-29 BLUEPRINT — Agent Interactive Chat & Run Scripts

**Batch:** BATCH-29 | **Version:** v0.36.0 → v0.37.0 | **Cycle:** STANDARD | **AIV:** v5.3
**Lead:** Craft Agent (Lead Override per §5.3) | **Blueprint Version:** 1.0

## Strategic Bet
Peekaboo `--chat` mode + `.peekaboo.json`-style automation scripts adapted for Desktop-Agent.

## Scope
- **IN**: Interactive chat REPL, automation script runner (.desktop-agent.json), CLI commands
- **OUT**: LLM-powered chat (deferred), macOS/Linux changes

## Hard Boundaries
| ID | Constraint |
|----|-----------|
| HB-01 | Chat runs locally — no API calls unless user configures LLM |
| HB-02 | All 3,206 baseline tests pass |
| HB-03 | Scripts are declarative JSON — no eval/exec of arbitrary code |
| HB-04 | No new required dependencies |

## Tasks (SEQUENTIAL)

### TASK-01: Interactive Chat REPL
New module `src/agent_core/agent/chat.py` — `AgentChat` class.
- REPL loop: prompt → parse → execute → display result
- Built-in commands: `/help`, `/observe`, `/click <target>`, `/type <text>`, `/snapshot`, `/screenshot`, `/exit`
- Each command delegates to DesktopAgent facade methods
- History via readline-compatible input
- Tests: 12

### TASK-02: Automation Script Runner
New module `src/agent_core/agent/script_runner.py` — `ScriptRunner` class.
- Loads `.desktop-agent.json` files with action sequences
- Schema: `{ "name": "...", "steps": [{ "action": "click", "target": "..." }, ...] }`
- Sequential execution with error handling and dry-run mode
- Validation: schema check before execution
- Tests: 10

### TASK-03: CLI Integration + MCP/REST
- CLI: `desktop-agent chat` (interactive), `desktop-agent run <script.json>` (batch)
- MCP: `chat_message`, `run_script` tools
- REST: `POST /chat`, `POST /run-script`
- Tests: 10

### TASK-04: Version Bump + Integration
- Version 0.36.0 → 0.37.0
- Full suite validation
- Tests: 5

**Total:** 37 new tests | **Expected suite:** 3,243
