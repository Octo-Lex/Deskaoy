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

### 2. Integration test suite — partially resolved

Browser-era integration modules (`test_browser_basic.py`,
`test_verification.py`, `test_recovery_io.py`) have been deleted — they
were dead code depending on a non-existent conftest and removed CDP APIs.

Hermetic desktop integration tests (`test_desktop_integration.py`) are now
re-enabled in CI, covering dry-run execution, policy-deny, receipts, and
CLI goal-capture through the real `DesktopAgent.execute()` stack.

Real-hardware integration tests (`test_real_*.py`,
`test_desktop_agent_live.py`) remain gated behind `--run-integration` and
are not run in CI.

### 3. Linux input injection — X11 supported, Wayland unsupported

Real input injection is supported on **X11 sessions with xdotool** installed.
The adapter detects `XDG_SESSION_TYPE`, `DISPLAY`, and `shutil.which("xdotool")`
at call time. When available, `click`, `type_text`, `key_press`, `scroll`, and
`fill` execute real xdotool commands. When unavailable (Wayland, no DISPLAY,
no xdotool), they return `ErrorCategory.UNSUPPORTED`.

**Exception:** `click()` has a two-tier contract:
- **AT-SPI2 action click** succeeds without xdotool when an accessible element
  exposes an invoke/click action. This is a real accessibility action, not fake
  success.
- **Coordinate-based click** requires X11 + xdotool. Falls back to `UNSUPPORTED`
  when xdotool is unavailable.

`type_text`, `key_press`, `scroll`, and `fill` all require X11 + xdotool.

Wayland remains **unsupported** — global input injection on Wayland is
compositor/portal-dependent and cannot be done generically. All input methods
return `ErrorCategory.UNSUPPORTED` on Wayland sessions.

The future implementation path is the **XDG RemoteDesktop portal + libei/EIS**,
which provides consent-aware, session-based input injection. See
`docs/wayland-input-strategy.md` for the full strategy and backend decision
record. `deskaoy doctor` now reports portal and libei availability on Wayland
sessions (informational WARN, not FAIL).

`dry_run=True` always works for previewing without subprocess invocation.

### 4. macOS adapter — experimental with permission probes (pending hardware validation)

The macOS adapter (`MacOSAdapter`) has real CGEvent/Quartz implementations
but is **experimental** — untested on real macOS hardware. The factory
requires explicit opt-in via `DESKTOP_AGENT_MACOS=1`.

**Batch 11 improvements:**
- Added explicit permission probes: `_check_accessibility_permission()`
  (required for CGEvent injection) and `_check_screen_recording_permission()`
  (required for screenshots). All input methods now fail honestly with
  `ErrorCategory.SECURITY` when permissions are missing, rather than silently
  dropping events.
- Added key blocklist enforcement to `key_press` (was missing).
- Added `fill()` permission check before click (no partial side effects).
- Created `scripts/validate_macos_adapter.py` — a hardware validation script
  that tests construction, permissions, screenshots, input injection, key
  blocklist, and dry-run paths on a real macOS machine.

**Gate removal criteria** (not yet met):
- Hardware validation script must pass on at least one macOS version
- All input methods must produce observable desktop actions
- Permission failure paths must be verified
- `_char_to_keycode` needs a real character-to-keycode mapping (currently
  returns 0 for all characters — a known limitation)
- Named target resolution needs implementation (currently falls back to
  window center without returning None for unresolved targets)

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
