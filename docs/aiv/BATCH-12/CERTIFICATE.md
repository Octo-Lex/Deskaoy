# BATCH-12 Certificate — Security Audit + Hardening

## Status: ✅ PASSED

| Metric | Value |
|--------|-------|
| Version | 0.24.0 |
| Modified modules | `key_blocklist.py`, `windows.py`, `health.py` |
| New tests | 6 |
| Total tests | 2,790 |
| Failures | 0 |
| Date | 2026-05-03 |

## Deliverables
- Key blocklist rewritten with sorted-key normalization
- Key aliases: del↔delete, esc↔escape, cmd/win/super↔meta, return↔enter
- WindowsAdapter.key_press() checks blocklist → SECURITY error
- HealthCheck includes key_blocklist + sensitive_apps checks
- Order-independent combo matching

## Verification
- [x] All 6 security hardening tests pass
- [x] All 22 original blocklist+app tests pass
- [x] All 8 health checks verified
- [x] `ctrl+alt+del` matches `ctrl+alt+delete` via alias normalization
- [x] Health test counts updated (6 → 8)
- [x] Smoke test updated
- [x] No regressions: 2,790 passed, 0 failed
