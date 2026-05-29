# TASK-01 Implementation Report — TelemetryRuntime and DesktopAgentMetrics

**Task ID:**       BATCH-43/TASK-01
**Priority:**      High
**Status:**        ✅ APPROVED
**Implemented by:** Assistant (session 260528-long-storm)
**Approved by:**   Lead (260520-apt-topaz)
**Date:**          2026-05-28

## Objective

Create `TelemetryRuntime` as the sole owner of OTel providers/exporters and `DesktopAgentMetrics` with 6 cached instruments.

## Files Created

| File | Lines | Detail |
|:-----|:------|:-------|
| `src/agent_core/tracing/runtime.py` | 194 | `TelemetryConfig` dataclass, `TelemetryRuntime` class, `configure_telemetry()`, `get_telemetry()`, `reset_telemetry()` |
| `src/agent_core/tracing/instruments.py` | 81 | `DesktopAgentMetrics` with 6 instruments under `desktop_agent.*` namespace |
| `tests/test_tracing/test_runtime.py` | 198 | Runtime lifecycle, config, provider tests |
| `tests/test_tracing/test_instruments.py` | 124 | Metrics creation and recording tests |
| `tests/test_tracing/test_no_otel_at_import.py` | 23 | HB-03 enforcement: no OTel SDK import at `agent_core` module level |

## Tests Added: +19

- `test_runtime.py`: 12 tests (lifecycle, config defaults, provider creation, lazy import)
- `test_instruments.py`: 6 tests (counter/histogram/recording)
- `test_no_otel_at_import.py`: 1 test (module-level import check)

## Test Results

- **117 passed, 0 failed** (98 TASK-00 baseline + 19 new)
- Zero modifications to existing source files

## Acceptance Criteria

| AC | Status |
|:---|:-------|
| AC-01-01: TelemetryRuntime owns TracerProvider + MeterProvider | ✅ MET |
| AC-01-02: DesktopAgentMetrics uses `desktop_agent.*` namespace | ✅ MET |
| AC-01-03: OTel SDK imported lazily (not at module level) | ✅ MET (HB-03 test) |
| AC-01-04: `otlp_endpoint` defaults to None | ✅ MET (COR-43-02) |

## Key Design Decisions

- DEC-43-01: TelemetryRuntime owns all providers; FlowLogger only emits
- DEC-43-05: OTel SDK as optional `[tracing]` dependency
- DEC-43-06: Instance-based internally + `configure_telemetry()` convenience

## Partial Sign-Off

`docs/aiv/BATCH-43/PARTIAL-TASK-01-2026-05-28.md`
