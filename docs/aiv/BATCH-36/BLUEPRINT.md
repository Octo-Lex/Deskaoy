# BATCH-36 BLUEPRINT — PyPI Release & Documentation

**Batch:** BATCH-36 | **Version:** v0.49.0 → v1.0.0 | **Cycle:** SIMPLIFIED | **AIV:** v5.3
**Lead:** Craft Agent (Lead Override per §5.3) | **Blueprint Version:** 1.0

## Strategic Bet
Public PyPI upload readiness, final docs pass, v1.0.0 tag — the release batch.

## Scope
- **IN**: PyPI metadata finalization, docs audit, CHANGELOG final, README badges, v1.0.0 tag
- **OUT**: Actual PyPI upload (manual action by user), marketing, announcement

## Hard Boundaries
| ID | Constraint |
|----|-----------|
| HB-01 | `twine check dist/*` must pass with zero warnings |
| HB-02 | All 3,418+ tests pass |
| HB-03 | Version v1.0.0 in all 3 single-source files |

## Tasks (SEQUENTIAL)

### TASK-01: PyPI Metadata Finalization
- pyproject.toml: classifiers, urls, optional deps groups finalized
- `desktop-agent-0.49.0-py3-none-any.whl` + `.tar.gz` rebuilt
- `twine check` passes
- Tests: 5

### TASK-02: Documentation Final Pass
- README.md: badges, quickstart, install, usage, architecture diagram
- CHANGELOG.md: complete history from v0.1.0 → v1.0.0
- CONTRIBUTING.md: updated for v1.0.0
- docs/api/REFERENCE.md: complete API reference
- Tests: 5

### TASK-03: v1.0.0 Tag
- Version bump to v1.0.0 in all 3 files
- pyproject.toml: `development_status = "5 - Production/Stable"`
- Git tag `v1.0.0` (if git repo)
- Tests: 5

**Total:** 15 new tests | **Expected suite:** 3,433
**Cycle:** SIMPLIFIED (3 tasks, single review)
