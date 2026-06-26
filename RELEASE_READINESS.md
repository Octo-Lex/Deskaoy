# Release Readiness — v2.0.0

Last updated: 2026-06-27

## CI Gate

The canonical release gate is the GitHub Actions matrix in
`.github/workflows/tests.yml`:

- **Unit Tests**: ubuntu-latest + windows-latest × Python 3.11 + 3.12
- **Smoke Tests**: ubuntu-latest + windows-latest
- **DCO**: all commits must be signed off
- **Integration Tests**: disabled (`if: false`) — see known debt below

All checks must be green on `main` before tagging a release.

## Known Non-Blocking Debt

These items are explicitly tracked and do not block the v2.0.0 release:

### 1. `tests/test_action_first.py` — comtypes type-library (16 tests)

Windows UIA pattern tests import `comtypes.gen.UIAutomationClient` at call
time. This type library is not pre-generated on GitHub Actions Windows
runners (no interactive desktop session). The tests skip on
`GITHUB_ACTIONS=true` but fail on a local Windows dev machine without a
pre-generated comtypes module.

**Fix path**: pre-generate the comtypes module in CI, or mock the
`comtypes.gen` import in the test fixtures. Tracked as Batch 5+ follow-up
(adapter test hermeticity).

### 2. Integration test suite disabled

The integration suite (`tests/integration/`) was built around the removed
SuperBrowser browser-automation surface (Patchright/Chromium). The suite is
gated with `if: false` in CI and will be re-enabled once rewritten for v2
desktop-only automation.

### 3. Linux input injection unsupported

`type_text`, `key_press`, `scroll`, and `fill` return
`ErrorCategory.UNSUPPORTED` on Linux because no real input-injection
backend (AT-SPI2 EditableText, xdotool) is wired. The methods fail honestly
rather than returning fake success. `dry_run=True` still works for
previewing.

**Fix path**: implement AT-SPI2 EditableText or xdotool injection.

### 4. macOS adapter experimental

The macOS adapter (`MacOSAdapter`) has real CGEvent/Quartz implementations
but is **experimental** — untested without macOS hardware. The factory
requires explicit opt-in via `DESKTOP_AGENT_MACOS=1`.

### 5. Mypy baseline (non-blocking)

Mypy reports pre-existing errors in `desktop_agent.py` (10) and
`cli/main.py` (4). These are type-annotation gaps, not runtime bugs. Mypy
is not in the CI gate for v2.0.0; it will be added once the baseline is
cleaned up.

### 6. Ruff baseline (non-blocking)

The full codebase has pre-existing ruff warnings (F401, B904, etc.) beyond
the release-critical modules. The release-critical modules
(`__init__.py`, `_version.py`, `cli/main.py`) are clean or have explicit
`__all__` re-exports. A full lint cleanup pass is deferred.

## Release Metadata Checklist

- [x] Version single-source: `pyproject.toml` → `_version.py` → runtime resolution
- [x] `__version__`, CLI `VERSION`, `DesktopAgent.version`, telemetry
      `service_version`, and manifest version all agree
- [x] `pyproject.toml` URLs point to `Octo-Lex/Deskaoy`
- [x] CLI `deskaoy version` matches package metadata
- [x] README quick start is dry-run-safe (`dry_run=True`)
- [x] `release-check` command does not crash
- [x] `pywin32` in `[windows]` extra
- [x] `[browser]` extra removed from CI
- [x] CHANGELOG updated for v2.0.0
