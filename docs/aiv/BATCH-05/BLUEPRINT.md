BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-05
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
Fix the critical CLI storage_dir crash, resolve version drift,
add key blocklist, add sensitive app detection, expand SurfaceAdapter
with clipboard/open_app/invoke_element/window_state, add MCP transport,
and add REST transport — closing the 22 pattern gaps identified in the
PATTERN_TEST_REPORT.md.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - CLI commands execute without crashing (storage_dir fix)
  - Single source of truth for version (pyproject.toml only)
  - Key blocklist prevents dangerous key combos (Alt+F4, Ctrl+Alt+Del)
  - Sensitive app detection auto-elevates policy tier
  - SurfaceAdapter gains clipboard, open_app, invoke_element, set_window_state
  - MCP stdio transport allows Claude Code / Cursor integration
  - REST HTTP transport allows bring-your-own-agent integration
  - All existing 2,613 tests continue to pass
  - Doctor command checks new subsystems

What the code MUST NOT do:
  - Must NOT break any existing test
  - Must NOT add hard dependencies (MCP SDK, aiohttp are optional)
  - Must NOT change the SurfaceAdapter abstract method signatures for existing methods
  - Must NOT remove any existing public API
  - Must NOT touch super_browser code

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────
  Lint command:  python -m pytest --tb=line -q 2>&1 | tail -3

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────
  HB-01: No existing abstract method signatures on SurfaceAdapter may be changed.
         New methods MUST be added as non-abstract with default implementations.
  HB-02: All new transport dependencies (mcp, aiohttp) MUST be optional extras
         in pyproject.toml, not core dependencies.
  HB-03: Every new safety feature (key blocklist, sensitive apps) MUST have
         at least 2 unit tests confirming correct behavior.
  HB-04: The existing test count of 2,613 MUST NOT decrease.
  HB-05: No file outside src/agent_core/ may be modified except pyproject.toml,
         CHANGELOG.md, and test files.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────
SurfaceAdapter (cascade/protocol.py):
  - Existing 10 abstract methods unchanged
  - New non-abstract methods with default implementations:
    read_clipboard() -> str (raises NotImplementedError)
    write_clipboard(text: str) -> None (raises NotImplementedError)
    open_app(name: str) -> dict (raises NotImplementedError)
    invoke_element(target: str, action: str, value: str = "") -> ActionResult
    set_window_state(state: str, target: str = "") -> ActionResult
    get_focused_element() -> Optional[dict]
    get_element_state(target: str) -> dict

PolicyBridge additions (policy.py):
  - SENSITIVE_APPS: dict mapping app name patterns to tier elevation rules
  - BLOCKED_KEYS: frozenset of blocked key combinations

CLI (cli/main.py):
  - _get_agent() must not pass storage_dir to DesktopAgent()
  - Version sourced from importlib.metadata with fallback

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────
  - Key blocklist is enforced BEFORE dispatch, not after
  - Sensitive app elevation applies even in dev mode
  - MCP transport requires no auth (localhost only)
  - REST transport requires bearer token auth

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────
  BATCH-01 (CLI): DONE
  BATCH-03 (Runtime hardening): DONE
  BATCH-04 (PyPI prep): DONE (not formally closed)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────
  Baseline at Blueprint issuance:  2,613 existing tests
  Expected delta (all Tasks):      +85 new tests
  Expected total at Batch close:   ~2,698

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-05/TASK-01 — Critical CLI Fix + Version Drift
  Description:      Fix the storage_dir crash in CLI, unify version to single source
  Files in scope:   src/agent_core/cli/main.py, src/agent_core/desktop_agent.py,
                    src/agent_core/cli/version.py (new), src/agent_core/safety/health.py
  Depends on:       None
  Required Tests:
    | Test ID          | Type       | Pass Criteria                                    |
    |:-----------------|:-----------|:-------------------------------------------------|
    | TEST-05-01-01    | unit       | CLI execute command returns exit code 0 or 1, not crash |
    | TEST-05-01-02    | unit       | CLI health command returns output, not crash     |
    | TEST-05-01-03    | unit       | CLI schema command returns output, not crash     |
    | TEST-05-01-04    | unit       | CLI version returns consistent version string    |
    | TEST-05-01-05    | unit       | DesktopAgent.version matches pyproject.toml      |
    | TEST-05-01-06    | unit       | CLI estimate command returns output, not crash   |
    | TEST-05-01-07    | integration| Full CLI smoke: all 15 commands run without exception |
  Acceptance Criteria:
    AC-01-01: `desktop-agent execute "test"` does not raise TypeError
    AC-01-02: `desktop-agent version` shows version from pyproject.toml metadata
    AC-01-03: DesktopAgent.version class attribute matches package version
    AC-01-04: `desktop-agent health` returns structured health status

TASK-02: BATCH-05/TASK-02 — Key Blocklist + Sensitive App Detection
  Description:      Add blocked key combinations and sensitive app pattern detection
  Files in scope:   src/agent_core/safety/key_blocklist.py (new),
                    src/agent_core/safety/sensitive_apps.py (new),
                    src/agent_core/safety/__init__.py or safety health
  Depends on:       None
  Required Tests:
    | Test ID          | Type       | Pass Criteria                                    |
    |:-----------------|:-----------|:-------------------------------------------------|
    | TEST-05-02-01    | unit       | is_blocked_key("Alt+F4") returns True            |
    | TEST-05-02-02    | unit       | is_blocked_key("Ctrl+Alt+Del") returns True      |
    | TEST-05-02-03    | unit       | is_blocked_key("a") returns False                |
    | TEST-05-02-04    | unit       | block_reason("Alt+F4") contains explanation      |
    | TEST-05-02-05    | unit       | is_sensitive_app("outlook") returns True          |
    | TEST-05-02-06    | unit       | is_sensitive_app("notepad") returns False         |
    | TEST-05-02-07    | unit       | sensitive_app_tier("gmail") returns "confirm"    |
  Acceptance Criteria:
    AC-02-01: Blocked keys list includes Alt+F4, Cmd+Q, Ctrl+Alt+Del, Shift+Delete
    AC-02-02: Sensitive apps list includes outlook, gmail, banking, 1password
    AC-02-03: Non-blocked keys pass through unchanged

TASK-03: BATCH-05/TASK-03 — SurfaceAdapter Expansion
  Description:      Add clipboard, open_app, invoke_element, set_window_state,
                    get_focused_element, get_element_state to SurfaceAdapter
  Files in scope:   src/agent_core/cascade/protocol.py,
                    src/agent_core/adapters/windows.py
  Depends on:       TASK-01 (CLI must work for testing)
  Required Tests:
    | Test ID          | Type       | Pass Criteria                                    |
    |:-----------------|:-----------|:-------------------------------------------------|
    | TEST-05-03-01    | unit       | SurfaceAdapter has read_clipboard method         |
    | TEST-05-03-02    | unit       | SurfaceAdapter has write_clipboard method        |
    | TEST-05-03-03    | unit       | SurfaceAdapter has open_app method               |
    | TEST-05-03-04    | unit       | SurfaceAdapter has invoke_element method         |
    | TEST-05-03-05    | unit       | SurfaceAdapter has set_window_state method       |
    | TEST-05-03-06    | unit       | Default implementations raise NotImplementedError|
    | TEST-05-03-07    | unit       | WindowsAdapter.read_clipboard returns string     |
    | TEST-05-03-08    | unit       | WindowsAdapter.open_app returns dict with pid    |
    | TEST-05-03-09    | unit       | invoke_element supports click/focus/set_value    |
    | TEST-05-03-10    | unit       | set_window_state supports maximize/minimize      |
  Acceptance Criteria:
    AC-03-01: All new methods are non-abstract (backward compatible)
    AC-03-02: WindowsAdapter implements at least clipboard and open_app
    AC-03-03: Existing tests continue to pass (no regressions)

TASK-04: BATCH-05/TASK-04 — MCP Transport
  Description:      Add MCP stdio transport for Claude Code / Cursor integration
  Files in scope:   src/agent_core/transport/__init__.py (new),
                    src/agent_core/transport/mcp_server.py (new),
                    pyproject.toml (optional dep)
  Depends on:       TASK-01
  Required Tests:
    | Test ID          | Type       | Pass Criteria                                    |
    |:-----------------|:-----------|:-------------------------------------------------|
    | TEST-05-04-01    | unit       | MCPServerTool wraps DesktopAgent capability      |
    | TEST-05-04-02    | unit       | MCP tool listing returns 10 tools                |
    | TEST-05-04-03    | unit       | MCP tool call routes to execute()                |
    | TEST-05-04-04    | unit       | Graceful fallback when mcp SDK not installed     |
    | TEST-05-04-05    | unit       | Bearer token auth not required for stdio MCP     |
  Acceptance Criteria:
    AC-04-01: `desktop-agent mcp` starts stdio JSON-RPC server
    AC-04-02: MCP dependency is optional extra: `pip install desktop-agent[mcp]`
    AC-04-03: Tool list maps to 10 DesktopAgent capabilities

TASK-05: BATCH-05/TASK-05 — REST Transport
  Description:      Add REST HTTP transport with bearer token auth
  Files in scope:   src/agent_core/transport/rest_server.py (new),
                    src/agent_core/transport/auth.py (new),
                    pyproject.toml (optional dep)
  Depends on:       TASK-04 (transport package structure)
  Required Tests:
    | Test ID          | Type       | Pass Criteria                                    |
    |:-----------------|:-----------|:-------------------------------------------------|
    | TEST-05-05-01    | unit       | REST server binds to 127.0.0.1 only             |
    | TEST-05-05-02    | unit       | GET /tools returns tool catalog                  |
    | TEST-05-05-03    | unit       | POST /execute requires bearer token              |
    | TEST-05-05-04    | unit       | GET /health returns version and status           |
    | TEST-05-05-05    | unit       | Graceful fallback when aiohttp not installed     |
    | TEST-05-05-06    | integration| Full round-trip: token → execute → result        |
  Acceptance Criteria:
    AC-05-01: `desktop-agent serve` starts HTTP server on 127.0.0.1:3847
    AC-05-02: Unauthenticated requests return 401
    AC-05-03: aiohttp dependency is optional extra: `pip install desktop-agent[rest]`

TASK-06: BATCH-05/TASK-06 — Doctor Upgrade + CHANGELOG + Certificate
  Description:      Upgrade doctor to check new subsystems, update CHANGELOG,
                    write batch certificate
  Files in scope:   src/agent_core/cli/main.py, CHANGELOG.md,
                    docs/aiv/BATCH-05/ (all AIV docs)
  Depends on:       TASK-01 through TASK-05
  Required Tests:
    | Test ID          | Type       | Pass Criteria                                    |
    |:-----------------|:-----------|:-------------------------------------------------|
    | TEST-05-06-01    | unit       | Doctor checks MCP transport availability          |
    | TEST-05-06-02    | unit       | Doctor checks REST transport availability         |
    | TEST-05-06-03    | unit       | Doctor checks key blocklist is loaded             |
    | TEST-05-06-04    | unit       | Doctor checks sensitive apps registry              |
  Acceptance Criteria:
    AC-06-01: CHANGELOG.md updated with BATCH-05 entry
    AC-06-02: Doctor reports new subsystems status
    AC-06-03: All AIV documents archived under docs/aiv/BATCH-05/

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────
  BAC-01: All 2,613+ tests pass with 0 failures
  BAC-02: CLI fully functional (no storage_dir crash)
  BAC-03: CHANGELOG.md updated with BATCH-05 entry
  BAC-04: All documents archived under /docs/aiv/BATCH-05/

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────
[To be completed after Phase I-B review]

═══════════════════════════════════════════════════════════
