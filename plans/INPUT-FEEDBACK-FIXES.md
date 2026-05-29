# Input Feedback — Fix Summary

> 1186 tests passing, 0 failures, 30 skipped

## What Was Fixed (this round)

| # | Feedback Point | Fix | Files |
|---|---------------|-----|-------|
| 1 | **Bezier dead zones** | Control point offset clamped to `distance * 0.25`. Points deviating >120° from target direction are rejected. | `bezier.py` |
| 2 | **DPI-aware jitter** | `HumanizationConfig.dpi_scale` scales click offset and micro-jitter. `effective_click_offset_max` and `effective_micro_jitter` properties. | `types.py`, `jitter.py`, `bezier.py` |
| 3 | **DPI from window** | `_get_window_rect()` calls `GetDpiForWindow()` and updates `dpi_scale` on every call. | `windows.py` |
| 4 | **Window state validation** | New `_ensure_window_ready()` checks: `IsWindow()`, `IsIconic()` (restores if minimized), `IsWindowVisible()`. Called before every click. | `windows.py` |
| 5 | **Occlusion detection** | New `_is_window_at_point()` using `WindowFromPoint()`. If occluded, brings to front and re-checks. Blocks click if still covered. | `windows.py` |
| 6 | **SetForegroundWindow failure** | Falls back to `BringWindowToTop()`. Raises `RuntimeError` if both fail. Restores from minimized first. | `windows.py` |
| 7 | **Focus settle delay** | After `_bring_to_front()`, waits `focus_settle_ms` (300ms default ± 100ms random) before starting Bezier move. Anti-detection for timing analysis. | `windows.py` |
| 8 | **Failsafe redundancy** | New `abort()` method + `_check_abort()` called before and after settle delay. Works in VMs/RDP/headless where corner-mouse failsafe doesn't. | `windows.py` |
| 9 | **Abort before click** | `_check_abort()` called twice per click: once at start, once after focus settle. | `windows.py` |
| 10 | **16 new tests** | Control point constraints, DPI scaling, abort mechanism, humanization defaults. | `test_safety.py` |

## What Was Documented (not coded — requires different layers)

| # | Feedback Point | Status | Why |
|---|---------------|--------|-----|
| 1 | **LLMHF_INJECTED flag** | ❌ Documented limitation | Requires kernel driver or hardware HID. Out of scope. |
| 2 | **Saccade movement** | ❌ Future | Good idea, low priority until telemetry proves necessary. |
| 3 | **Florence-2 verification step** | ❌ Phase 2 | Needs visual grounding pipeline. Architecture supports it. |
| 4 | **Catmull-Rom splines** | ❌ Future | Current Bezier is fine for single-click. Chained moves need this. |
| 5 | **n-gram burst weighting** | ❌ Over-engineering | 10% burst / 3 chars sufficient for current threat model. |
| 6 | **macOS AXUIElement stale coords** | ❌ Documented | Noted for macOS adapter. Window animations can return stale data. |
| 7 | **AT-SPI bus availability** | ❌ Documented | Noted for Linux adapter. Need capability probe at init. |
| 8 | **IME / Unicode fallback** | ⚠️ Partial | `pyautogui.write()` handles ASCII. Unicode needs `press()` fallback. Documented as known gap. |
| 9 | **Hypothesis property testing** | ⚠️ Worth adding | 50-seed loop tests are decent. Hypothesis would be better. Not blocking. |

## Test Count

```
Before feedback:  1170 tests
After feedback:   1186 tests (+16 safety + constraint tests)
Total:            1186 passed, 0 failed, 30 skipped
```
