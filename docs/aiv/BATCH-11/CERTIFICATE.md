# BATCH-11 Certificate — Per-App JSON Guides

## Status: ✅ PASSED

| Metric | Value |
|--------|-------|
| Version | 0.24.0 |
| New modules | `guides/__init__.py` |
| New guides | 5 (notepad, calculator, explorer, chrome, vscode) |
| New tests | 11 |
| Failures | 0 |
| Date | 2026-05-03 |

## Deliverables
- AppGuide dataclass (version, selectors, common_actions, tips, safety_notes)
- GuideRegistry: load from directory, search by name/category
- 5 sample JSON guides in `guides/guides/`

## Verification
- [x] All 11 new tests pass
- [x] No regressions
- [x] Guide loading from JSON works
- [x] Category-based search works
