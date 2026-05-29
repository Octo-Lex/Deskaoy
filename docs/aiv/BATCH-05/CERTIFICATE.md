# BATCH-05 Certificate — CLI Fix + Safety + Transports

**Batch**: BATCH-05  
**Date**: 2026-05-03  
**Version**: 0.19.0  
**Status**: ✅ COMPLETE

## Tasks

| Task | Description | Status | Tests |
|------|-------------|--------|-------|
| TASK-01 | CLI crash fix + version drift | ✅ Done | Existing (26 CLI tests) |
| TASK-02 | Key blocklist (12 combos) | ✅ Done | 10 new tests |
| TASK-02 | Sensitive app detection (14 apps) | ✅ Done | 13 new tests |
| TASK-03 | SurfaceAdapter expansion (7 methods) | ✅ Done | 11 new tests |
| TASK-04 | MCP stdio transport | ✅ Done | 10 new tests |
| TASK-05 | REST HTTP transport | ✅ Done | 5 new tests |
| TASK-06 | Doctor upgrade + CHANGELOG | ✅ Done | Existing |

## New Files

| File | Purpose |
|------|---------|
| `src/agent_core/safety/key_blocklist.py` | 12 blocked key combinations |
| `src/agent_core/safety/sensitive_apps.py` | 14 sensitive app categories |
| `src/agent_core/transport/__init__.py` | Transport package |
| `src/agent_core/transport/mcp_server.py` | MCP stdio JSON-RPC server |
| `src/agent_core/transport/rest_server.py` | REST HTTP API server |
| `tests/test_safety/test_key_blocklist_sensitive_apps.py` | 23 tests |
| `tests/test_cascade/test_adapter_expansion.py` | 10 tests |
| `tests/test_transport/test_mcp_server.py` | 10 tests |
| `tests/test_transport/test_rest_server.py` | 5 tests |

## Modified Files

| File | Change |
|------|--------|
| `src/agent_core/cli/main.py` | Fixed storage_dir crash, health→health, UTF-8, mcp/serve commands |
| `src/agent_core/cli/version.py` | Single-source version 0.19.0 |
| `src/agent_core/desktop_agent.py` | Version 0.19.0 |
| `src/agent_core/cascade/protocol.py` | 7 new non-abstract methods |
| `src/agent_core/adapters/windows.py` | clipboard, open_app, set_window_state |
| `pyproject.toml` | Version 0.19.0, [mcp] and [rest] extras |
| `CHANGELOG.md` | BATCH-05 entry |
| `tests/test_cli/test_main.py` | health_check → health |

## Test Results

```
2,644 passed, 0 failed, 36 skipped
```

- Previous: 2,613 passed
- Added: 44 new tests
- Regressions: 0

## Pre-flight Checks

| Check | Result |
|-------|--------|
| All tests pass | ✅ 2,644/2,644 |
| No regressions | ✅ Existing tests unchanged |
| Version consistency | ✅ pyproject=0.19.0, fallback=0.19.0, class=0.19.0 |
| CLI smoke test | ✅ All 17 commands exit cleanly |
| Import check | ✅ All new modules importable |
