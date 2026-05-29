# BATCH-35 BLUEPRINT — Internal Alpha & Hardening

**Batch:** BATCH-35 | **Version:** v0.42.0 → v0.49.0 | **Cycle:** STANDARD | **AIV:** v5.3
**Lead:** Craft Agent (Lead Override per §5.3) | **Blueprint Version:** 1.0

## Strategic Bet
Zero P0 bugs, full E2E validation across all adapters, performance benchmarks, security audit — release readiness gate.

## Scope
- **IN**: E2E tests for all adapters (mocked), security audit fixes, doctor command validation, version bump to pre-release
- **OUT**: Public release (BATCH-36), real hardware CI

## Hard Boundaries
| ID | Constraint |
|----|-----------|
| HB-01 | Zero test failures in full suite |
| HB-02 | Doctor command must pass on clean Windows install |
| HB-03 | All baseline tests pass |

## Tasks (SEQUENTIAL)

### TASK-01: E2E Adapter Tests
New file `tests/test_e2e/test_adapter_e2e.py`.
- Full lifecycle test for each adapter (Windows, macOS, Linux)
- Create adapter → observe → click → type → snapshot → verify
- All mocked but exercises real code paths
- Tests: 10

### TASK-02: Security Audit
- Credential leak scan: grep all source for api_key/secret/password patterns
- Input validation: all CLI inputs sanitized
- File path traversal: snapshot paths validated
- Rate limiter: ensure all transport endpoints rate-limited
- Tests: 8

### TASK-03: Doctor Command Full Validation
- Doctor checks all 13+ subsystems
- Each check has clear pass/fail/N/A message
- Exit code: 0 if all pass/N/A, 1 if any fail
- Tests: 5

### TASK-04: Version Bump + Pre-Release Tag
- Version 0.42.0 → 0.49.0 (pre-release numbering)
- pyproject.toml: `development_status = "4 - Beta"`
- Tests: 2

**Total:** 25 new tests | **Expected suite:** 3,418
