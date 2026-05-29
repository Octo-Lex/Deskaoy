# TASK-04 Implementation Report — Metrics Wiring and Dependency Declaration

**Task ID:**       BATCH-43/TASK-04
**Priority:**      Medium
**Status:**        ✅ APPROVED
**Implemented by:** Assistant (session 260528-fresh-thistle)
**Approved by:**   Lead (260520-apt-topaz)
**Date:**          2026-05-28

## Objective

Wire `DesktopAgentMetrics` into `TelemetryRuntime` and declare `[tracing]`, `[tracing-otlp]`, `[tracing-prometheus]` extras in `pyproject.toml`.

## Files Changed

| File | Action | Detail |
|:-----|:-------|:-------|
| `src/agent_core/tracing/runtime.py` | NO CHANGE | `self._metrics` and `@property metrics` already present from TASK-01 |
| `pyproject.toml` | MODIFIED | Added `[tracing]`, `[tracing-otlp]`, `[tracing-prometheus]` extras under `[project.optional-dependencies]` |
| `tests/test_tracing/test_runtime.py` | MODIFIED | 5 new tests across 3 test classes |

## Extras Declared

```toml
tracing = ["opentelemetry-api>=1.40", "opentelemetry-sdk>=1.40"]
tracing-otlp = ["desktop-agent[tracing]", "opentelemetry-exporter-otlp-proto-grpc>=1.40"]
tracing-prometheus = ["desktop-agent[tracing]", "opentelemetry-exporter-prometheus>=0.45b0"]
```

## Tests Added: +5

| Test ID | Method | Pass Criteria |
|:--------|:-------|:--------------|
| TEST-43-04-01 | `test_metrics_returns_desktop_agent_metrics` | runtime.metrics returns DesktopAgentMetrics |
| TEST-43-04-01b | `test_metrics_identity_stable` | Same instance returned on repeated access |
| TEST-43-04-02 | `test_cdp_call_records_values` | MeterReader has recorded values after record_cdp_call |
| TEST-43-04-03 | `test_tracing_extras_exist` | `[tracing]`, `[tracing-otlp]`, `[tracing-prometheus]` parseable |
| AC-04-04 | `test_prometheus_not_core_dependency` | `opentelemetry-exporter-prometheus` not in core deps |

## Test Results

- **153 passed, 0 failed** (148 TASK-03 baseline + 5 new)

## Acceptance Criteria

| AC | Status |
|:---|:-------|
| AC-04-01: DesktopAgentMetrics accessible via TelemetryRuntime.metrics | ✅ MET |
| AC-04-02: desktop_agent.* namespace used for all instruments | ✅ MET |
| AC-04-03: [tracing], [tracing-otlp], [tracing-prometheus] declared | ✅ MET |
| AC-04-04: opentelemetry-exporter-prometheus NOT core dependency | ✅ MET |

## Partial Sign-Off

`docs/aiv/BATCH-43/PARTIAL-TASK-04-2026-05-28.md`
