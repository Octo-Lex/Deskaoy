BLUEPRINT
═══════════════════════════════════════════════════════════

Sprint / Batch ID:        BATCH-01
Blueprint Version:        1.0
Lead Programmer:          Lead AI Instance
Date Issued:              2026-04-26
Review SLA:               1 hour
Execution SLA:            4 hours

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Provide a `desktop-agent` console entry point registered in pyproject.toml
  - Support 14 subcommands: execute, estimate, schedule (add/list/remove/due),
    skills (list/match), facts (list/search), health, schema, version, repl
  - `execute` accepts a natural-language instruction and dispatches to
    DesktopAgent.execute(), printing a structured result (summary + confidence +
    duration + status)
  - `execute --dry-run` previews the action without executing
  - `execute --json` outputs raw JSON AgentResult
  - `repl` launches an interactive read-eval-print loop that manages session
    lifecycle (configure_session on start, terminate_session on exit) and
    supports special dot-commands (.health, .facts, .soul, .skills, .schema,
    .estimate, .undo, .help, .exit)
  - `schedule add` creates a named routine with cron expression + instruction
  - `schedule list` lists all stored routines
  - `schedule remove` deletes a named routine
  - `schedule due` shows routines whose next_fire_time is within 60s
  - `skills list` lists all discovered skills from SkillLoader
  - `skills match` matches an instruction against loaded skills
  - `facts list` lists stored facts from FactStore
  - `facts search` searches facts by keyword
  - `health` runs DesktopAgent.health_check() and prints results
  - `schema` prints the capability manifest as a table
  - `version` prints package version
  - All output uses pretty-printed tables by default, raw JSON with --json flag
  - Formatters handle AgentResult, AgentEstimate, HealthStatus, Routine,
    SkillDefinition, Fact, and schema dicts

What the code MUST NOT do:
  - Must NOT add any new runtime dependencies (argparse is stdlib)
  - Must NOT import DesktopAgent or any adapter at module level (lazy init only)
  - Must NOT execute real desktop actions during tests (all tests mock the agent)
  - Must NOT hardcode file paths — respect --storage-dir and AIOS_HOME env var
  - Must NOT block the event loop — all agent calls must be async-safe

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: The CLI MUST NOT import DesktopAgent, WindowsAdapter, or any surface
         adapter at module import time. All agent construction MUST be deferred
         to a _get_agent() factory that is called only when a subcommand needs it.
         This ensures `desktop-agent version` works without Windows/pyautogui.

  HB-02: Every test MUST use mocked DesktopAgent instances. No test in this
         batch may depend on a real adapter, real LLM, or real desktop.
         This is verified by the test suite having zero imports from
         agent_core.adapters.windows or agent_core.llm.client in test files.

  HB-03: The CLI entry point MUST exit with code 0 on success and non-zero on
         failure. sys.exit() must be called explicitly in main(), never in
         library code. The argparse error handler must catch all exceptions
         and return non-zero exit codes.

  HB-04: The REPL MUST call configure_session() on entry and terminate_session()
         on exit (including KeyboardInterrupt). Session leak is a hard failure.

  HB-05: No new pip dependencies may be added to any [project] section in
         pyproject.toml. argparse, asyncio, sys, os, json are all stdlib.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

CLI Result (internal, not a new type — uses existing types):
  - AgentResult for execute
  - AgentEstimate for estimate
  - HealthStatus for health
  - Routine for schedule list
  - SkillDefinition for skills list
  - Fact for facts list

Formatter output format:
  - Pretty: table with columns, colored status, human-readable durations
  - JSON: raw dataclass as_dict() serialization

REPL prompt format:
  ```
  desktop-agent> _
  ```

REPL dot-commands:
  .help      Print available commands
  .health    Run health check
  .facts     List stored facts
  .soul      Show soul aspects
  .skills    List loaded skills
  .schema    Show capability schema
  .estimate  Preview without executing (takes instruction)
  .undo      Undo a previous execution (takes execution_id)
  .exit      Exit REPL (also Ctrl+C / Ctrl+D)

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────

  AUTH-01: The CLI is a thin orchestration layer. All business logic stays in
           DesktopAgent and its subsystems. The CLI only parses args, calls
           agent methods, and formats output.

  AUTH-02: Session IDs are auto-generated as UUID4 when not provided via
           --session flag. No two concurrent sessions may share a session ID.

  AUTH-03: The REPL runs in a single async event loop. No threading or
           multiprocessing within the REPL.

  AUTH-04: --storage-dir defaults to $AIOS_HOME if set, else ~/.aios/desktop-agent.
           The CLI creates this directory on first use if it does not exist.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────

  DEP-01: DesktopAgent.execute() — BATCH-01 calls it, implemented in v0.3.0 ✅
  DEP-02: DesktopAgent.estimate() — implemented in v0.3.0 ✅
  DEP-03: DesktopAgent.health_check() — implemented in v0.11.0 ✅
  DEP-04: RoutineScheduler — implemented in v0.15.0 ✅
  DEP-05: SkillLoader — implemented in v0.15.0 ✅
  DEP-06: FactStore — implemented in v0.15.0 ✅
  DEP-07: DesktopAgent.configure_session() / terminate_session() — v0.13.0 ✅
  DEP-08: os_types (AgentResult, AgentEstimate, etc.) — v0.6.0 ✅
  DEP-09: pyproject.toml [project.scripts] — build system ✅

  All dependencies resolved. No blockers.

───────────────────────────────────────────────────────────
REQUIRED TEST COVERAGE
───────────────────────────────────────────────────────────

| Test ID         | Type  | Pass Criteria                                                    |
|:----------------|:------|:-----------------------------------------------------------------|
| T01-01          | unit  | `desktop-agent execute "click OK"` parses instruction string     |
| T01-02          | unit  | `execute --dry-run` sets context.dry_run=True                    |
| T01-03          | unit  | `execute --json` sets json_mode=True in formatter                |
| T01-04          | unit  | `execute --timeout 30` passes timeout_seconds to AgentContext    |
| T01-05          | unit  | `execute` with mocked agent returns success + prints summary     |
| T01-06          | unit  | `execute` with mocked agent failure prints error + exits 1       |
| T01-07          | unit  | `estimate "do thing"` calls agent.estimate() with goal           |
| T01-08          | unit  | `schedule add --name daily --cron "0 8 * * *" --prompt "check"` creates routine |
| T01-09          | unit  | `schedule list` returns list of routines                         |
| T01-10          | unit  | `schedule remove --name daily` removes routine                   |
| T01-11          | unit  | `schedule due` returns routines due within 60s                   |
| T01-12          | unit  | `skills list` returns discovered skills                          |
| T01-13          | unit  | `skills match "type text"` returns matching skill                |
| T01-14          | unit  | `facts list` returns stored facts                                |
| T01-15          | unit  | `facts search "email"` returns matching facts                    |
| T01-16          | unit  | `health` calls health_check() and prints status                  |
| T01-17          | unit  | `schema` prints capability manifest table                        |
| T01-18          | unit  | `version` prints "desktop-agent X.Y.Z"                          |
| T01-19          | unit  | Unknown subcommand exits with code 2 and error message           |
| T01-20          | unit  | `--storage-dir /tmp/test` passes dir to agent factory            |
| T01-21          | unit  | Formatters: format_result_success returns string with "SUCCESS"  |
| T01-22          | unit  | Formatters: format_result_failure returns string with "FAILURE"  |
| T01-23          | unit  | Formatters: format_estimate returns cost + confidence + latency  |
| T01-24          | unit  | Formatters: format_health returns status per probe               |
| T01-25          | unit  | Formatters: format_routine returns name + cron + next_fire       |
| T01-26          | unit  | Formatters: format_skill returns name + triggers                 |
| T01-27          | unit  | Formatters: format_schema returns table with capability columns  |
| T01-28          | unit  | REPL: .help prints all dot-commands                              |
| T01-29          | unit  | REPL: .exit calls terminate_session + returns                    |
| T01-30          | unit  | REPL: normal instruction dispatches to agent.execute()           |

───────────────────────────────────────────────────────────
ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  AC-01: `desktop-agent version` prints "desktop-agent 0.17.0" without importing
         any adapter or LLM module.

  AC-02: `desktop-agent execute "Open Notepad" --dry-run --json` returns a JSON
         object with status="dry_run" without performing any real action.

  AC-03: `desktop-agent schedule add --name test --cron "0 8 * * *" --prompt "hello"`
         creates a routine and `desktop-agent schedule list` shows it.

  AC-04: `desktop-agent repl` starts interactive loop, accepts `.help`, accepts
         natural-language instruction, prints result, accepts `.exit`.

  AC-05: All 30 tests in T01-01 through T01-30 pass with zero real dependencies
         (no adapter, no LLM, no desktop).

  AC-06: pyproject.toml contains [project.scripts] desktop-agent entry point.

  AC-07: `pip install -e .` followed by `desktop-agent version` works from a
         fresh terminal.

  AC-08: No new dependencies added to pyproject.toml.

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────

Reviewer Report ID:       REVIEW-BATCH-01-2026-04-26
Review Cycle:             1
Lead Decision:            [X] ACCEPT WITH MODIFICATIONS

If ACCEPT WITH MODIFICATIONS — list each Reviewer flag acted on:
  FLAG-CHK-05 (data models precision) → Action taken: Not acted on. The CLI arg mapping
    is simple enough (instruction string → AgentGoal.params) that detailed schemas are
    unnecessary. The pre-existing plan PHASE-V017-CLI.md has the detail if needed.
  FLAG-CHK-09 (test gaps) → Action taken: Added T01-31 (REPL KeyboardInterrupt calls
    terminate_session) and T01-32 (execute --session passes ID to AgentContext) to the
    required test coverage. These will be added during execution.

Blueprint Version after response: 1.1
Lead Sign:                Lead AI Instance — 2026-04-26 20:05

═══════════════════════════════════════════════════════════
