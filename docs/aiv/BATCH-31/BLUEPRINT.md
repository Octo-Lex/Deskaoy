# BATCH-31 BLUEPRINT — Concurrent Capture Gate & Performance

**Batch:** BATCH-31 | **Version:** v0.38.0 → v0.39.0 | **Cycle:** STANDARD | **AIV:** v5.3
**Lead:** Craft Agent (Lead Override per §5.3) | **Blueprint Version:** 1.0

## Strategic Bet
ScreenCaptureKit-style concurrency protection + performance regression tests.

## Scope
- **IN**: Capture mutex/lock, snapshot LRU metrics, perf regression tests, latency budgets
- **OUT**: GPU acceleration, multiprocessing capture

## Hard Boundaries
| ID | Constraint |
|----|-----------|
| HB-01 | Capture gate must not deadlock — timeout after 10s |
| HB-02 | All baseline tests pass |

## Tasks (SEQUENTIAL)

### TASK-01: Concurrent Capture Gate
New module `src/agent_core/safety/capture_gate.py` — `CaptureGate` class.
- asyncio.Lock-based mutex ensuring only one screenshot/observation at a time
- Queue depth limit (max 5 pending captures)
- Timeout: 10s wait for lock acquisition
- Metrics: capture_count, wait_time_ms, timeout_count
- Tests: 10

### TASK-02: Snapshot LRU Metrics
Enhance `SnapshotStore` with metrics.
- `get_metrics()` → hits, misses, evictions, total_size_bytes, count
- `reset_metrics()` for testing
- Expose via CLI: `desktop-agent snapshots stats`
- Tests: 8

### TASK-03: Performance Regression Tests
New file `tests/test_performance/test_regression.py`.
- Screenshot latency <500ms (mocked adapter)
- Observation pipeline quick preset <1s
- Snapshot create+read <100ms
- Health check <200ms
- Tests: 8

### TASK-04: Version Bump + Integration
- Version 0.38.0 → 0.39.0
- Tests: 4

**Total:** 30 new tests | **Expected suite:** 3,298
