# Input Module — Feedback Analysis

> Systematic review of each feedback point vs. what's built.
> ✅ = Already handled  ⚠️ = Needs fix  ❌ = Missing, needs build

---

## 1. Multi-Monitor & DPI Scaling
**Status**: ⚠️ Needs fix

`GetWindowRect()` returns physical pixels on DPI-unaware processes but virtual
coordinates on DPI-aware ones. Currently no DPI handling at all.

**Fix**: Add `_get_dpi_scale()` and `_to_virtual_coords()` to windows.py.
Scale jitter by DPI. Document the requirement.

## 2. Window Overlap / Occlusion
**Status**: ⚠️ Needs fix (partial)

`_validate_point_in_window()` checks coordinates are within window bounds but
doesn't verify the point is actually visible (not covered by another window).

**Fix**: Add `_is_window_at_point()` using `WindowFromPoint()` win32 API.
If another window is on top, call `_bring_to_front()` before clicking.

## 3. Dead Zones in Bezier Curves
**Status**: ⚠️ Needs fix

Unconstrained random control points can create S-curves or backtracking.
No minimum displacement per segment. No max deviation angle.

**Fix**: Clamp perpendicular offset to `distance * 0.25` max. Add minimum
displacement check per segment. Reject curves that deviate >120° from target.

## 4. DPI-Aware Jitter Scaling
**Status**: ⚠️ Needs fix

±1.5px jitter and ±4px click offset are absolute. At 4K / 200% DPI these
are proportionally invisible. At 100% 1080p they're fine.

**Fix**: Scale jitter by DPI factor in HumanizationConfig at runtime.

## 5. SetForegroundWindow() Failure Handling
**Status**: ⚠️ Needs fix

`SetForegroundWindow()` fails silently when:
- Process lacks foreground rights
- UAC prompt is active
- Another fullscreen app has focus
Currently catches the exception but only logs a warning. Clicks proceed to
wrong window.

**Fix**: Check `IsWindowVisible()` and `IsIconic()` before calling.
Catch access denied. Return error instead of proceeding.

## 6. Focus Wait Delay
**Status**: ⚠️ Needs fix

After `SetForegroundWindow()`, code waits 100ms. But the Bezier move starts
immediately after. An app that detects focus timing sees: focus → 100ms → click.

**Fix**: Add configurable focus settle delay (200-500ms) after
`_bring_to_front()`. Randomize it.

## 7. LLMHF_INJECTED Flag
**Status**: ❌ Known limitation, documented

`SendInput()` (pyautogui's backend) sets the `LLMHF_INJECTED` flag. Apps can
detect software-generated input. No fix now — this requires kernel-level driver
or hardware HID (Raspberry Pi Pico). Document as known limitation.

## 8. Saccade Movement
**Status**: ❌ Not implemented

Pre-click micro-jump. Good idea. Add later if telemetry detection becomes
an issue. Low priority.

## 9. Verification Step (Florence-2 closed loop)
**Status**: ❌ Not implemented

Click → wait 300ms → crop → Florence-2 "did state change?" — this is the
right architecture but needs Phase 2 visual grounding. The pipeline is designed
for this but not wired.

## 10. Bezier Velocity Reset Between Segments
**Status**: ⚠️ Needs fix (design)

Chained moves reset velocity to zero. Real humans have continuous velocity
through waypoints. Catmull-Rom splines or C1-stitched Bezier would fix this.

**Fix**: Not critical for single-click flows. Document as future improvement.

## 11. Typing Burst n-gram Weighting
**Status**: ❌ Over-engineering for threat model

Current 10% burst / 3 chars is sufficient. n-gram weighting ("ing", "tion")
is clever but unnecessary until detection proves otherwise.

## 12. Typing IME / Modifier Key Edge Cases
**Status**: ⚠️ Needs fix

`pyautogui.write()` breaks on non-ASCII characters and IME input. Shift for
uppercase is handled by pyautogui but Ctrl/Alt combos may not work for
international keyboards.

**Fix**: Add Unicode fallback using `pyautogui.typewrite()` with individual
characters or `pyautogui.press()` for special chars.

## 13. Failsafe Redundancy
**Status**: ⚠️ Needs fix

pyautogui's corner-mouse failsafe doesn't work in:
- VMs without mouse integration
- RDP sessions
- Headless CI

**Fix**: Add secondary abort: SIGINT handler + explicit `abort()` method
on adapter. Check abort flag before every action.

## 14. Window State Validation (IsWindowVisible / IsIconic)
**Status**: ⚠️ Needs fix

No check before `SetForegroundWindow()`. Minimized windows throw errors or
unpredictably steal focus.

**Fix**: Add `_ensure_window_ready()` that checks visibility, restores from
minimized, validates hwnd is still valid.

## 15. macOS AXUIElement Stale Coordinates
**Status**: ❌ Documented for future

AXUIElement can return stale coords during window animations. Not blocking
for Windows adapter. Document for macOS adapter.

## 16. AT-SPI Bus Availability
**Status**: ❌ Documented for future

AT-SPI requires `at-spi-bus-launcher` which may not run in minimal Linux.
Capability probe at init needed. Document for Linux adapter.

## 17. Property-Based Testing (Hypothesis)
**Status**: ⚠️ Worth adding

Current tests use fixed seeds and examples. Hypothesis would validate bounds
across thousands of random seeds automatically.

**Fix**: Add hypothesis strategies for Bezier paths and jitter bounds.

## 18. Typing Burst Logic Correlation
**Status**: ✅ Already handled

10% burst / 3 chars is the right baseline. The feedback's n-gram suggestion
is noted but not needed now.

## 19. HumanizationConfig DPI-Aware Jitter
**Status**: ⚠️ Needs fix

Jitter values are absolute pixels. Need DPI scaling.
