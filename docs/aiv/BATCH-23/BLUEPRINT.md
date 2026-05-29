# BATCH-23: Codebase Polish & Health Fix

**Version:** 0.31.1  
**Date:** 2026-05-04  
**Status:** IN PROGRESS

## Scope

1. **Health check 3-state** — Optional subsystems (surface, LLM, policy, storage) report NA instead of FAIL when not configured
2. **Ruff + mypy config** — Add linting and type-checking configuration to pyproject.toml
3. **README polish** — Add badges, installation table, quick-start examples
4. **CLI status command** — Show which subsystems are configured and available
5. **Pillow deprecation fix** — `getdata()` → `get_flattened_data()` in vision/cache.py

## Files Modified

- `src/agent_core/safety/health.py` — 3-state health (pass/na/fail)
- `src/agent_core/cli/main.py` — Add `status` command
- `src/agent_core/cli/formatters.py` — format_status()
- `src/agent_core/vision/cache.py` — Pillow deprecation fix
- `pyproject.toml` — ruff + mypy config
- `README.md` — Badges, installation, examples

## Tests Added

- `tests/test_safety/test_health_three_state.py` — Tests for 3-state health
- `tests/test_cli/test_status.py` — Tests for status command

## Verification

- All 2,921+ tests still pass
- `desktop-agent health` reports HEALTHY when only built-in subsystems available
- `desktop-agent status` shows configured vs available
- No DeprecationWarnings from Pillow
