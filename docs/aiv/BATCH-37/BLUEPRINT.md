BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-37
Blueprint Version:        1.2 (revised after review cycle 1 — reviewer FLAG-01/02/03 resolved)
Cycle Mode:               STANDARD
Lead Programmer:          Lead Programmer
Date Issued:              2026-05-11
Review SLA:               30 min
Execution SLA per Task:   90 min
Partial Sign-Off SLA:     15 min
Task Sequencing:          Mixed (TASK-01 first, then TASK-02 and TASK-03 parallel)

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Ship a persistent Desktop-Agent daemon that keeps the surface adapter
initialized and serves commands over IPC (named pipe on Windows, Unix
domain socket on Linux/macOS). First call pays initialization cost;
all subsequent calls execute in <5ms overhead vs ~2s cold start.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Spawn a background daemon process that holds a DesktopAgent instance
  - Accept commands over IPC in the same AgentGoal/AgentResult format
  - Support multiple concurrent clients (request multiplexing)
  - Auto-shutdown after configurable idle timeout
  - Provide a client library that is a drop-in replacement for DesktopAgent()
  - Expose daemon lifecycle commands: start, stop, status, ping
  - Surface adapter remains initialized between calls (no cold start)

What the code MUST NOT do:
  - Must not modify the existing DesktopAgent class constructor signature
  - Must not introduce threading inside the daemon that shares COM/UIA objects across threads
  - Must not require a running AI-OS kernel (must work standalone)
  - Must not add hard dependencies — IPC transport is optional (`pip install desktop-agent[daemon]`)
  - Must not change any existing test's behavior

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────
  Lint command:  python -m pytest tests/ -q --tb=line 2>&1 | tail -5

  Zero-failure gate: All existing tests must continue passing.
  New tests must pass. The flaky test_tracing/test_flow_logger.py::TestSpanScope::test_duration_positive
  is a known pre-existing flaky test and does not count as a regression.

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: DesktopAgent constructor signature is UNCHANGED.
         `DesktopAgent(surface=, llm=, agent_loop=, registry=, memory=,
                      policy_bridge=, trace_bridge=, recovery_bridge=)`
         No new required parameters. Existing code that creates DesktopAgent()
         directly must work identically.

  HB-02: IPC protocol uses the EXACT same AgentGoal → AgentResult types
         from os_types.py. No custom serialization. No protocol-specific types.
         A client sends AgentGoal as JSON, receives AgentResult as JSON.

  HB-03: Daemon runs SINGLE-THREADED event loop for COM/UIA operations.
         No concurrent UIA access from multiple threads. Incoming requests
         are queued and processed sequentially by the UIA thread.

  HB-04: Existing test count does not decrease. Baseline: 3,703 tests.
         All 3,703 must still pass after this Batch.

  HB-05: daemon module is importable even without optional dependencies.
         Importing agent_core.daemon must not crash if the IPC library
         is not installed. It must raise a clear ImportError only when
         actually attempting to start/connect the daemon.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

### IPC Protocol (JSON over named pipe / Unix socket)

Request envelope:
```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "method": "execute",
  "params": {
    "goal": {"capability": "click", "params": {"target": "Save"}},
    "context": {"execution_id": "xxx", "idempotency_key": "xxx", "task_id": "xxx", "user_id": "cli", "session_id": "s1"}
  }
}
```

NOTE: AgentGoal, AgentResult, AgentContext are plain @dataclass types.
They do NOT have .as_dict() methods. Protocol layer MUST use
dataclasses.asdict() or manual field extraction. Never call .as_dict().

Response envelope:
```json
{
  "jsonrpc": "2.0",
  "id": "unique-id",
  "result": {"execution_id": "xxx", "status": "success", "summary": "...", ...}
}
```

Serialization rule: use dataclasses.asdict(obj) for encoding,
construct new instance via AgentResult(**dict) for decoding.

Lifecycle methods:
```json
{"method": "ping"}    → {"result": {"status": "ok", "uptime_s": 123.4}}
{"method": "status"}  → {"result": {"healthy": true, "surface": "windows", "calls_served": 42}}
{"method": "shutdown"} → {"result": {"status": "shutting_down"}}
```

### Daemon Configuration

```python
@dataclass
class DaemonConfig:
    socket_path: str        # Named pipe path on Windows, .sock path on Unix
    idle_timeout_s: float   # Auto-shutdown after this many seconds idle (default: 300)
    max_clients: int        # Max concurrent connections (default: 10)
    log_level: str          # Logging level (default: "INFO")
```

### DaemonClient — Drop-in DesktopAgent Replacement

```python
class DaemonClient:
    """Drop-in replacement for DesktopAgent that routes through the daemon."""

    def __init__(self, socket_path: str | None = None): ...

    async def execute(self, goal: AgentGoal, context: AgentContext) -> AgentResult: ...
    async def health(self) -> HealthStatus: ...
    def describe(self) -> dict: ...
    def schema(self) -> dict: ...
```

### File Layout

```
src/agent_core/daemon/
    __init__.py          # Public API: DaemonServer, DaemonClient, DaemonConfig
    server.py            # DaemonServer — binds socket, processes requests
    client.py            # DaemonClient — connects to daemon, routes calls
    protocol.py          # JSON-RPC encode/decode helpers
    transport_pipe.py    # Windows named pipe transport
    transport_socket.py  # Unix domain socket transport
```

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────

  AUTH-01: The daemon process inherits the user's OS permissions.
           No privilege escalation. If the user can't read the screen,
           the daemon can't either.

  AUTH-02: IPC socket permissions are user-only (600 on Unix,
           appropriate DACL on Windows named pipe). Other users
           on the same machine cannot connect to the daemon.

  AUTH-03: The daemon does NOT store or forward API keys.
           LLM configuration is passed at daemon start time.
           The client does not send credentials per-request.

  AUTH-04: Only one daemon instance per socket_path.
           Second startup attempt returns clear error with PID
           of existing daemon.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────

  Depends on:
    - BATCH-36 (v1.0.0 baseline — all existing code)
    - os_types.py (AgentGoal, AgentContext, AgentResult — unchanged)
    - desktop_agent.py DesktopAgent class (unchanged)
    - Python stdlib asyncio (for event loop)
    - No external IPC library — use stdlib asyncioStreamReader/Writer

  Does NOT depend on:
    - AI-OS kernel (standalone operation)
    - Any BATCH-37+ batch

───────────────────────────────────────────────────────────
STATE.md STATUS
───────────────────────────────────────────────────────────

  State file exists:       [ ] NO — first Batch under this program
  Last Updated:            N/A — will create at Batch Close
  Batches since update:    N/A
  Reconciliation audit:    [ ] N/A — first Batch

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────

  Baseline at Blueprint issuance:  3,766 existing tests
  Expected delta (all Tasks):      +81 new tests
  Expected total at Batch close:   3,847

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: [BATCH-37/TASK-01]
  Priority:          Critical
  Description:       Daemon core — DaemonServer process that holds a DesktopAgent
                     instance, binds to a named pipe (Windows) or Unix socket (Linux/macOS),
                     and processes execute/ping/status/shutdown requests via JSON-RPC.
                     Single-threaded event loop for COM/UIA safety. Idle timeout auto-shutdown.
  Files in scope:
    - src/agent_core/daemon/__init__.py (new)
    - src/agent_core/daemon/server.py (new)
    - src/agent_core/daemon/protocol.py (new)
    - src/agent_core/daemon/transport_pipe.py (new)
    - src/agent_core/daemon/transport_socket.py (new)
    - src/agent_core/daemon/config.py (new)
    - pyproject.toml (add `[daemon]` optional dependency group)
    - tests/test_daemon/test_server.py (new)
    - tests/test_daemon/test_protocol.py (new)
    - tests/test_daemon/test_transport.py (new)
  Depends on:        None — foundational task
  Required Tests:
    | Test ID          | Type       | Behavior Verified                                          | Failure Mode                                    | Falsified By                                         | Pass Criteria                                                |
    |:-----------------|:-----------|:-----------------------------------------------------------|:------------------------------------------------|:-----------------------------------------------------|:-------------------------------------------------------------|
    | TEST-37-01-01    | unit       | DaemonConfig has correct defaults                          | Config defaults change silently                 | Change idle_timeout_s default to 0 in config.py    | assert config.idle_timeout_s == 300.0                        |
    | TEST-37-01-02    | unit       | Protocol encodes AgentGoal to JSON-RPC request             | Serialization drops fields                      | Remove "capability" from serialization in protocol | assert request["params"]["goal"]["capability"] == "click"    |
    | TEST-37-01-03    | unit       | Protocol decodes JSON-RPC response to AgentResult          | Deserialization returns wrong status type       | Return string "ok" instead of ResultStatus enum    | assert isinstance(result, AgentResult)                        |
    | TEST-37-01-04    | unit       | Protocol rejects malformed JSON-RPC (missing method)       | Malformed request crashes daemon                | Remove method validation check in protocol         | assert response["error"]["code"] == -32600                    |
    | TEST-37-01-05    | unit       | Protocol rejects unknown method                            | Unknown method gets silently ignored            | Remove method whitelist in server                  | assert response["error"]["code"] == -32601                    |
    | TEST-37-01-06    | integration| DaemonServer starts, binds socket, responds to ping        | Daemon fails to bind or respond                 | Return early from start() before binding           | assert ping_result["status"] == "ok"                          |
    | TEST-37-01-07    | integration| DaemonServer routes execute to DesktopAgent.execute()       | Execute method doesn't reach DesktopAgent       | Mock DesktopAgent.execute to raise, verify caught  | assert result.status in ("success", "failure") — no crash    |
    | TEST-37-01-08    | integration| DaemonServer queues concurrent requests (no parallel UIA)  | Two requests processed simultaneously            | Remove asyncio.Lock from request processing        | assert second_request_starts_after_first_completes            |
    | TEST-37-01-09    | unit       | DaemonServer auto-shuts down after idle timeout            | Daemon runs forever consuming resources         | Set idle_timeout to 0.1s, wait, verify shutdown    | assert daemon.is_running is False after timeout               |
    | TEST-37-01-10    | unit       | Transport: named pipe path resolves correctly on Windows   | Wrong pipe name format                          | Hardcode wrong prefix in transport_pipe            | assert path starts with r"\\.\pipe\" on Windows               |
    | TEST-37-01-11    | unit       | Transport: Unix socket path resolves correctly on non-Win  | Wrong socket path                               | Skip platform check, always use pipe path          | assert path.endswith(".sock") on non-Windows                   |
    | TEST-37-01-12    | unit       | Second daemon startup on same socket fails with clear error| Two daemons corrupt shared state                | Remove PID-file check from server                  | assert raises with "already running" message                   |
    | TEST-37-01-13    | unit       | daemon module imports without error even without [daemon]  | Import crashes on missing optional deps         | Add hard import of asyncio in __init__             | assert import agent_core.daemon succeeds                       |
    | TEST-37-01-14    | integration| Daemon status endpoint returns uptime and call count        | Status returns stale data                       | Remove call_counter increment from server          | assert status["calls_served"] == 1 after one execute          |
    | TEST-37-01-15    | unit       | shutdown method sets is_running=False                      | Daemon ignores shutdown command                 | Remove shutdown handler from dispatch              | assert daemon.is_running is False after shutdown              |

  Acceptance Criteria:
    AC-01-01: DaemonServer can start, bind to OS-appropriate socket, and accept connections
    AC-01-02: Protocol layer correctly serializes/deserializes AgentGoal and AgentResult as JSON-RPC
    AC-01-03: Single-threaded request processing — concurrent requests are queued, not parallelized
    AC-01-04: Auto-shutdown after configurable idle timeout
    AC-01-05: Duplicate daemon detection — second startup on same socket fails with PID of existing
    AC-01-06: Graceful import — `import agent_core.daemon` does not crash without optional deps
    AC-01-07: pyproject.toml has `[daemon]` optional dependency group
  Traceability:
    AC-01-01 → TEST-37-01-06, TEST-37-01-10, TEST-37-01-11
    AC-01-02 → TEST-37-01-02, TEST-37-01-03, TEST-37-01-04, TEST-37-01-05
    AC-01-03 → TEST-37-01-08
    AC-01-04 → TEST-37-01-09
    AC-01-05 → TEST-37-01-12
    AC-01-06 → TEST-37-01-13
    AC-01-07 → TEST-37-01-07 (verified by pyproject.toml change)


TASK-02: [BATCH-37/TASK-02]
  Priority:          High
  Description:       DaemonClient — drop-in replacement for DesktopAgent that connects
                     to a running daemon over IPC. Implements the same execute(), health(),
                     describe(), and schema() methods. Auto-starts daemon if not running.
                     Transparent fallback to direct DesktopAgent if daemon unavailable.
  Files in scope:
    - src/agent_core/daemon/client.py (new)
    - src/agent_core/daemon/__init__.py (update exports)
    - tests/test_daemon/test_client.py (new)
  Depends on:        TASK-01 (server must exist for client to connect)
  Required Tests:
    | Test ID          | Type       | Behavior Verified                                          | Failure Mode                                    | Falsified By                                         | Pass Criteria                                                |
    |:-----------------|:-----------|:-----------------------------------------------------------|:------------------------------------------------|:-----------------------------------------------------|:-------------------------------------------------------------|
    | TEST-37-02-01    | unit       | DaemonClient.connect() reaches daemon via IPC              | Client cannot establish connection               | Return None from transport connect                  | assert client.is_connected is True                            |
    | TEST-37-02-02    | unit       | DaemonClient.execute() sends AgentGoal, returns AgentResult| Client doesn't send goal or misreads result      | Mock transport to return empty dict                | assert isinstance(result, AgentResult)                        |
    | TEST-37-02-03    | unit       | DaemonClient.describe() returns discovery document         | Client doesn't proxy describe call               | Remove describe from client method dispatch         | assert desc["name"] == "desktop_agent"                        |
    | TEST-37-02-04    | unit       | DaemonClient.health() proxies to daemon health             | Health call not forwarded                        | Return hardcoded health from client instead of daemon | assert health result matches daemon response                |
    | TEST-37-02-05    | integration| DaemonClient auto-starts daemon if not running             | Client crashes when daemon absent                | Remove auto-start logic from client                | assert daemon process running after client init               |
    | TEST-37-02-06    | unit       | DaemonClient falls back to direct DesktopAgent if daemon unavailable | Client hangs waiting for daemon       | Remove fallback path from client                    | assert result comes from direct DesktopAgent                  |
    | TEST-37-02-07    | unit       | DaemonClient handles daemon crash mid-session              | Client crashes when daemon dies                  | Raise ConnectionError in execute, no catch          | assert client falls back gracefully OR raises DaemonUnavailable |
    | TEST-37-02-08    | integration| Multiple DaemonClient instances share one daemon           | Each client starts its own daemon                | Remove PID-file sharing from auto-start             | assert only one daemon process running                         |
    | TEST-37-02-09    | unit       | DaemonClient disconnect cleans up socket                   | Socket leaked after client close                 | Remove cleanup from __del__                         | assert no stale socket after client.close()                   |
    | TEST-37-02-10    | unit       | DaemonClient implements same method signatures as DesktopAgent | Interface mismatch breaks drop-in replacement | Change execute() signature in client               | assert callable signatures match DesktopAgent                  |

  Acceptance Criteria:
    AC-02-01: DaemonClient implements execute(), health(), describe(), schema() — same signatures as DesktopAgent
    AC-02-02: Auto-start: DaemonClient starts daemon process if not already running
    AC-02-03: Transparent fallback: if daemon is unavailable, falls back to direct DesktopAgent
    AC-02-04: Connection cleanup: closing client releases socket resources
    AC-02-05: Multiple clients can share a single daemon instance
  Traceability:
    AC-02-01 → TEST-37-02-10, TEST-37-02-02, TEST-37-02-03, TEST-37-02-04
    AC-02-02 → TEST-37-02-05
    AC-02-03 → TEST-37-02-06, TEST-37-02-07
    AC-02-04 → TEST-37-02-09
    AC-02-05 → TEST-37-02-08


TASK-03: [BATCH-37/TASK-03]
  Priority:          High
  Description:       CLI integration — `desktop-agent daemon start`, `desktop-agent daemon stop`,
                     `desktop-agent daemon status`. CLI execute command uses DaemonClient
                     when daemon is running (opt-in via --daemon flag). No change to
                     default behavior (CLI still creates DesktopAgent directly by default).
  Files in scope:
    - src/agent_core/cli/main.py (add daemon subcommands)
    - tests/test_cli/test_daemon_cli.py (new)
  Depends on:        TASK-01 (server) and TASK-02 (client)
  Required Tests:
    | Test ID          | Type       | Behavior Verified                                          | Failure Mode                                    | Falsified By                                         | Pass Criteria                                                |
    |:-----------------|:-----------|:-----------------------------------------------------------|:------------------------------------------------|:-----------------------------------------------------|:-------------------------------------------------------------|
    | TEST-37-03-01    | integration| `desktop-agent daemon start` starts daemon process         | CLI command doesn't start daemon                | Return early from _cmd_daemon_start                 | assert daemon subprocess is running                           |
    | TEST-37-03-02    | integration| `desktop-agent daemon stop` shuts down daemon              | Stop command doesn't reach daemon               | Remove shutdown method from CLI handler             | assert daemon subprocess is not running after stop            |
    | TEST-37-03-03    | integration| `desktop-agent daemon status` reports running state        | Status reports stale data                       | Remove status poll from CLI handler                 | assert "running" in status output                             |
    | TEST-37-03-04    | unit       | `desktop-agent execute --daemon` routes through DaemonClient| --daemon flag ignored, direct DesktopAgent used | Remove --daemon arg parsing from CLI               | assert DaemonClient.execute called when --daemon flag present |
    | TEST-37-03-05    | unit       | `desktop-agent execute` (no --daemon) uses direct DesktopAgent | Default behavior changed to use daemon   | Remove DesktopAgent direct path from CLI            | assert DesktopAgent() created directly, not DaemonClient      |
    | TEST-37-03-06    | unit       | daemon subcommand parser registered with correct sub-subcommands| Parser missing subcommands                 | Remove subparsers from daemon arg setup             | assert "start", "stop", "status" in available subcommands     |
    | TEST-37-03-07    | integration| `desktop-agent daemon start` prints socket path on startup | User doesn't know where daemon is listening     | Remove print statement from start handler           | assert socket_path in captured stdout                         |
    | TEST-37-03-08    | unit       | `desktop-agent daemon start` fails with clear error if already running| Silent overwrite of running daemon    | Remove PID-file check from start handler            | assert "already running" in error output                      |
    | TEST-37-03-09    | unit       | daemon CLI commands accessible from help text               | Users can't discover daemon feature             | Remove daemon from subparser list                   | assert "daemon" in help output                                |
    | TEST-37-03-10    | integration| `desktop-agent daemon status` shows uptime and calls served | Status output missing key fields                | Remove uptime field from status response            | assert "uptime" in status output                              |

  Acceptance Criteria:
    AC-03-01: `desktop-agent daemon start` starts daemon, prints socket path
    AC-03-02: `desktop-agent daemon stop` cleanly shuts down daemon
    AC-03-03: `desktop-agent daemon status` shows health, uptime, calls served
    AC-03-04: `desktop-agent execute --daemon` routes through DaemonClient
    AC-03-05: Default `desktop-agent execute` behavior unchanged (direct DesktopAgent)
    AC-03-06: Existing CLI tests continue passing (no regression)
  Traceability:
    AC-03-01 → TEST-37-03-01, TEST-37-03-07
    AC-03-02 → TEST-37-03-02
    AC-03-03 → TEST-37-03-03, TEST-37-03-10
    AC-03-04 → TEST-37-03-04
    AC-03-05 → TEST-37-03-05
    AC-03-06 → TEST-37-03-09 (verified by existing test suite passing)

TASK-03 Additional Test (from review FLAG-03):
    | TEST-37-03-11    | integration| Existing CLI commands (execute, health, version) still work after daemon subcommands added | Daemon code breaks existing CLI dispatch | Add import that breaks CMD_MAP lookup | assert "execute", "health", "version" still in CMD_MAP keys |

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  BAC-01: Daemon can be started, receive execute calls, and be stopped cleanly.
          Verified by integration test in TASK-01 and TASK-03.
  BAC-02: DaemonClient is a drop-in replacement for DesktopAgent — same method
          signatures, same return types. Verified by TEST-37-02-10.
  BAC-03: CHANGELOG.md updated with BATCH-37 entry.
  BAC-04: All documents archived under /docs/aiv/BATCH-37/.
  BAC-05: All 3,703 pre-existing tests still pass (zero regressions).
  BAC-06: pyproject.toml has `[daemon]` optional dependency group.
  BAC-07: `import agent_core.daemon` does not crash without optional deps.

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────
[Completed by Lead after Phase I-B. Leave blank until Review Report is received.]

Reviewer Report ID:       REVIEW-BATCH-37-2026-05-11
Review Cycle:             1
Lead Decision:            [x] ACCEPT WITH MODIFICATIONS

If ACCEPT WITH MODIFICATIONS — list each Reviewer flag acted on:
  FLAG-01 → Action taken: Updated test baseline from 3,703 to 3,766 in Blueprint.
  FLAG-02 → Action taken: [daemon] group will be stdlib-only. No external IPC deps needed. Noted in Data Models.
  FLAG-03 → Action taken: Added TEST-37-03-11 (CLI regression test) to TASK-03.

Blueprint Version after response: 1.1
Lead Sign:                Lead Programmer — 2026-05-11 06:48 GMT+3

═══════════════════════════════════════════════════════════
