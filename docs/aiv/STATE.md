# CODEBASE STATE

Last Updated:       2026-05-11
Updated By:         Lead Programmer — via BATCH-37 Close
Framework Version:  5.3

───────────────────────────────────────────────────────────
VERIFIED MODULE MAP
───────────────────────────────────────────────────────────

  Module:              agent_core.daemon
  Actual exports:      DaemonServer, DaemonClient, DaemonConfig
  Verified in:         BATCH-37
  Notes:               Stdlib-only — no external IPC deps. Uses asyncio for named pipes/Unix sockets.

  Module:              agent_core.daemon.protocol
  Actual exports:      encode_request, decode_result_from_response, parse_request, goal_to_params, build_execute_request, build_ping_request, build_status_request, build_shutdown_request
  Verified in:         BATCH-37
  Notes:               JSON-RPC 2.0. AgentGoal/AgentResult use dataclasses.asdict() — no .as_dict() method exists on these types.

  Module:              agent_core.daemon.transport_pipe
  Actual exports:      PipeTransport, pipe_path
  Verified in:         BATCH-37
  Notes:               pipe_path() returns '\\.\pipe\desktop-agent' on Windows. Path uses chr(92) for backslashes in assertions to avoid raw-string escaping issues.

  Module:              agent_core.daemon.transport_socket
  Actual exports:      SocketTransport, socket_path
  Verified in:         BATCH-37
  Notes:               socket_path() returns '/tmp/desktop-agent.sock' on Unix.

───────────────────────────────────────────────────────────
ARCHITECTURAL DECISIONS
───────────────────────────────────────────────────────────

  DEC-001:  Daemon runs single-threaded event loop for COM/UIA safety.
            Windows COM objects cannot be accessed from multiple threads.
            All requests processed sequentially via asyncio.Lock.
            Future: if parallelism needed, use multiple daemon instances.
  Source:    BATCH-37
  Active:    YES
  Overridden: NO

  DEC-002:  IPC protocol is JSON-RPC 2.0 over named pipes (Windows) or Unix sockets (Linux/macOS).
            No external IPC library — pure stdlib asyncio.
            Serialization uses dataclasses.asdict() for AgentGoal/AgentResult.
  Source:    BATCH-37
  Active:    YES
  Overridden: NO

  DEC-003:  DaemonClient is a partial drop-in — implements execute(), health(), describe(), schema().
            Not all ~15 public methods of DesktopAgent are proxied (e.g., read_clipboard, set_value, perform_action are not).
            Future batches may add more method proxies.
  Source:    BATCH-37 (Reviewer FLAG-03)
  Active:    YES
  Overridden: NO

───────────────────────────────────────────────────────────
KNOWN GOTCHAS
───────────────────────────────────────────────────────────

  GOTCHA-001: Windows named pipe paths contain backslashes that break raw strings in assertions.
              Use chr(92) approach or double-escaped strings. Never use r"\\.\pipe\" — the trailing \"
              escapes the closing quote.
  Discovered:  BATCH-37
  Status:      MITIGATED — use chr(92) concatenation in test assertions

  GOTCHA-002: test_adapters/test_action_first.py shows 9 mock-state-leakage failures when run in full
              suite. Tests pass individually. Caused by global mock patches not being properly scoped.
              Not a BATCH-37 regression — existed before.
  Discovered:  BATCH-37 (observed during full suite run)
  Status:      OPEN — needs mock scoping fix in a future batch

  GOTCHA-003: test_tracing/test_flow_logger.py::TestSpanScope::test_duration_positive is a
              timing-sensitive flaky test. Pre-existing, not caused by any BATCH-37+ work.
  Discovered:  Pre-BATCH-37
  Status:      OPEN — would need time-mocking to fix

───────────────────────────────────────────────────────────
ADAPTATION LOG (ROLLING — LAST 10 BATCHES)
───────────────────────────────────────────────────────────

  BATCH-37/TASK-01: Blueprint stated .as_dict() for serialization. Actual: dataclasses have no .as_dict() method. Resolution: use dataclasses.asdict(). (Reviewer FLAG-01)
  BATCH-37/TASK-01: Test baseline stated 3,703. Actual: 3,766. Resolution: updated baseline to 3,766. (Reviewer FLAG-01)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────

  Last verified count: 3,831 (3,766 pre-existing + 65 new daemon tests)
  Verified in:         BATCH-37 (2026-05-11)
  Breakdown:           3,766 pre-existing + 29 server + 14 client + 22 CLI

───────────────────────────────────────────────────────────
CARRY-FORWARD OBLIGATIONS
───────────────────────────────────────────────────────────

  GAP-BATCH-37-01: DaemonClient only proxies 4 of ~15 public DesktopAgent methods.
    Status:   OPEN
    Source:    Reviewer FLAG-03
    Promised:  Future batch (post BATCH-39)

  GAP-BATCH-37-02: test_action_first.py mock-state-leakage (9 tests fail in full suite).
    Status:   OPEN
    Source:    Observed during BATCH-37 verification
    Promised:  Future batch

═══════════════════════════════════════════════════════════
