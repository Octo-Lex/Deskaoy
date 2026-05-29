# BrowserAdapter → SurfaceAdapter Wiring Plan

> **COMPLETED.** BrowserAdapter implemented, 30 tests passing, 1250 total green.

## Problem

We have:
- `SurfaceAdapter` protocol (10 abstract methods in `agent_core.cascade.protocol`)
- `MultimodalController` (rich browser interaction with 3-tier cascade)
- `DesktopAgent` (AI-OS Agent Protocol, talks to `SurfaceAdapter`)
- `WindowsAdapter` (SurfaceAdapter for desktop, uses pyautogui + win32gui)

But **no `BrowserAdapter`** implementing `SurfaceAdapter` on top of
`MultimodalController`. The architecture is unvalidated — we can't prove
DesktopAgent → SurfaceAdapter → real surface works end-to-end.

## Solution

Build `BrowserAdapter` — a thin shim that maps `SurfaceAdapter` methods
to `MultimodalController` + `CDPBridge` + `PageHandle`.

## File Plan

```
NEW FILES:
  src/super_browser/adapters/browser.py       ~250 lines — BrowserAdapter
  tests/test_adapters/test_browser_adapter.py  ~350 lines — unit tests

NO MODIFIED FILES
```

## Method Mapping

| SurfaceAdapter Method | BrowserAdapter Implementation |
|---|---|
| `click(target, dry_run)` | `controller.click(target)` |
| `fill(target, value, dry_run)` | `controller.fill(target, value)` |
| `type_text(text, delay_ms, dry_run)` | `cdp.compositor_type(text, delay_ms)` |
| `key_press(key, modifiers, dry_run)` | `controller.keypress(key, modifiers=modifiers)` |
| `scroll(direction, amount, dry_run)` | `controller.scroll(direction=direction, amount=amount)` |
| `screenshot()` | `page.screenshot()` (Patchright) or `cdp.capture_screenshot()` |
| `snapshot()` | `controller.capture_ax_snapshot()` |
| `evaluate(expression)` | `cdp.evaluate(expression)` |
| `current_url()` | `page.url` |
| `current_title()` | `page.title()` |
| `select_option(target, value)` | `controller.select(target, option=value)` |
| `navigate(url)` | `page.goto(url)` |
| `hover(target)` | `controller.hover(target)` |
| `supports_navigation` | `True` |
| `supports_select` | `True` |

## Design Decisions

1. **BrowserAdapter lives in `super_browser/adapters/`** — it depends on
   `MultimodalController`, `CDPBridge`, and `PageHandle`, which are all
   browser-specific. It cannot go in `agent_core`.

2. **BrowserAdapter wraps MultimodalController, not the raw CDP directly**
   — the controller already has the 3-tier cascade (selector → coordinate
   → vision). Reusing it means BrowserAdapter gets cascade for free.

3. **For `type_text()`**, we go directly to `cdp.compositor_type()` —
   the controller doesn't have a standalone `type_text` method, but
   CDPBridge does. This is the raw compositor path.

4. **dry_run**: When `dry_run=True`, return a predicted ActionResult
   without calling the controller. We predict success with the target
   info as data.

5. **AXSnapshot compatibility**: `snapshot()` returns the same `AXSnapshot`
   from `cascade.types` (re-exported via `super_browser/interaction/types`).
   No conversion needed.

6. **Constructor takes `MultimodalController`** (not page+cdp separately)
   — the controller already holds references to both. This avoids
   parameter explosion.

## Test Plan

### Unit Tests (mocked — no browser needed)

| Test | What |
|---|---|
| `test_click_delegates` | click() calls controller.click, returns ActionResult |
| `test_fill_delegates` | fill() calls controller.fill |
| `test_type_text_delegates` | type_text() calls cdp.compositor_type |
| `test_key_press_delegates` | key_press() calls controller.keypress |
| `test_scroll_delegates` | scroll() calls controller.scroll |
| `test_screenshot_returns_bytes` | screenshot() returns PNG bytes from page |
| `test_snapshot_returns_ax` | snapshot() returns AXSnapshot |
| `test_evaluate_delegates` | evaluate() calls cdp.evaluate |
| `test_current_url` | current_url() returns page.url |
| `test_current_title` | current_title() calls page.title() |
| `test_navigate` | navigate() calls page.goto() |
| `test_select_option` | select_option() calls controller.select() |
| `test_hover` | hover() calls controller.hover() |
| `test_supports_flags` | supports_navigation=True, supports_select=True |
| `test_dry_run_click` | dry_run=True → no controller call, ok=True |
| `test_dry_run_fill` | dry_run=True → no controller call, ok=True |
| `test_dry_run_type_text` | dry_run=True → no CDP call, ok=True |

### Integration Test (gated behind --run-integration)

| Test | What |
|---|---|
| `test_end_to_end_click` | DesktopAgent → BrowserAdapter → real headless Chromium → click button |
| `test_end_to_end_fill` | DesktopAgent → BrowserAdapter → fill input |
| `test_end_to_end_snapshot` | DesktopAgent → BrowserAdapter → capture AX snapshot |

## Effort

~3 hours total:
- BrowserAdapter implementation: ~1 hr
- Unit tests: ~1 hr
- Integration tests: ~1 hr
