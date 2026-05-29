# BATCH-32 BLUEPRINT — Visual Feedback System

**Batch:** BATCH-32 | **Version:** v0.39.0 → v0.40.0 | **Cycle:** STANDARD | **AIV:** v5.3
**Lead:** Craft Agent (Lead Override per §5.3) | **Blueprint Version:** 1.0

## Strategic Bet
Optional visual feedback overlay — click animations, cursor trails — for user confidence during automation.

## Scope
- **IN**: Click ripple, cursor trail, scroll indicator, highlight element — all opt-in via `--visual-feedback`
- **OUT**: Sound feedback, haptic feedback, always-on mode

## Hard Boundaries
| ID | Constraint |
|----|-----------|
| HB-01 | Visual feedback is opt-in only — never enabled by default |
| HB-02 | Must not interfere with automation coordinates |
| HB-03 | All baseline tests pass |
| HB-04 | No new required dependencies (use tkinter or console overlay) |

## Tasks (SEQUENTIAL)

### TASK-01: Visual Feedback Engine
New module `src/agent_core/feedback/engine.py` — `FeedbackEngine` class.
- `show_click_ripple(x, y)` — brief circle animation at click point
- `show_highlight(bounds)` — highlight rectangle around element
- `show_scroll_indicator(direction)` — brief arrow indicator
- `show_cursor_trail(points)` — fading trail between mouse positions
- Implementation: tkinter transparent overlay window (always on top, no focus steal)
- Tests: 10 (mocked tkinter)

### TASK-02: CLI & Adapter Integration
- `--visual-feedback` flag on CLI: execute, observe, chat commands
- SurfaceAdapter feedback hooks: `on_before_click()`, `on_after_click()`
- WindowsAdapter calls feedback engine when enabled
- Tests: 5

### TASK-03: Version Bump + Integration
- Version 0.39.0 → 0.40.0
- Tests: 5

**Total:** 20 new tests | **Expected suite:** 3,318
