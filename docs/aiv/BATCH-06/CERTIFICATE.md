# BATCH-06 Certificate — Two-Step Actions + Snapshot Diffing

**Batch**: BATCH-06
**Date**: 2026-05-03
**Version**: 0.20.0
**Status**: ✅ COMPLETE

## Tasks

| Task | Description | Status | Tests |
|------|-------------|--------|-------|
| TASK-01 | SnapshotDiffer — structural diff between AX snapshots | ✅ Done | 15 new tests |
| TASK-02 | TwoStepVerifier — action outcome classification | ✅ Done | 11 new tests |
| TASK-03 | AgentLoop two_step integration | ✅ Done | 8 new tests |
| TASK-04 | CHANGELOG + Certificate | ✅ Done | — |

## New Files

| File | Purpose |
|------|---------|
| `src/agent_core/cascade/differ.py` | SnapshotDiffer, SnapshotDiff, NodeDiff |
| `src/agent_core/agent/two_step.py` | TwoStepVerifier with action-specific classifiers |
| `tests/test_cascade/test_differ.py` | 15 tests |
| `tests/test_agent/test_two_step.py` | 11 tests |
| `tests/test_agent/test_loop_two_step.py` | 8 tests |
| `docs/aiv/BATCH-06/BLUEPRINT.md` | Batch blueprint |

## Modified Files

| File | Change |
|------|--------|
| `src/agent_core/agent/loop.py` | Added `two_step` param, `_verify_step`, `_capture_snapshot`, diff context in prompt |
| `src/agent_core/agent/types.py` | Added `verification`, `diff_summary` fields to StepResult |
| `pyproject.toml` | Version 0.20.0 |
| `src/agent_core/cli/version.py` | Version 0.20.0 |
| `src/agent_core/desktop_agent.py` | Version 0.20.0 |
| `CHANGELOG.md` | BATCH-06 entry |

## Test Results

```
2,691 passed, 0 failed, 36 skipped
```

- Previous: 2,657 passed (BATCH-05)
- Added: 34 new tests
- Regressions: 0

## Pre-flight Checks

| Check | Result |
|-------|--------|
| All tests pass | ✅ 2,691/2,691 |
| No regressions | ✅ Existing tests unchanged |
| Version consistency | ✅ pyproject=0.20.0, fallback=0.20.0, class=0.20.0 |
| HB-01: two_step defaults False | ✅ Verified |
| HB-02: No new dependencies | ✅ Pure Python |
| HB-03: All new modules have tests | ✅ 15 + 11 + 8 |
| HB-04: Test count not decreased | ✅ 2,691 > 2,657 |
| HB-05: Diff output is plain string | ✅ diff_to_text returns str |
