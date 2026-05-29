# BATCH-34 BLUEPRINT — Linux Adapter (AT-SPI2)

**Batch:** BATCH-34 | **Version:** v0.41.0 → v0.42.0 | **Cycle:** STANDARD | **AIV:** v5.3
**Lead:** Craft Agent (Lead Override per §5.3) | **Blueprint Version:** 1.0

## Strategic Bet
Linux accessibility via AT-SPI2 — completes cross-platform SurfaceAdapter trio (2/3).

## Scope
- **IN**: LinuxAdapter SurfaceAdapter subclass, AT-SPI2 tree walk, click/type/screenshot
- **OUT**: Real hardware testing, Wayland support, desktop-specific (GNOME/KDE) features

## Hard Boundaries
| ID | Constraint |
|----|-----------|
| HB-01 | All tests mocked — no Linux hardware required |
| HB-02 | python3-atspi is optional dependency only |
| HB-03 | Adapter must not import when on Windows/macOS |
| HB-04 | All baseline tests pass |

## Tasks (SEQUENTIAL)

### TASK-01: Linux Adapter Core
New module `src/agent_core/adapters/linux.py` — `LinuxAdapter(SurfaceAdapter)`.
- Uses AT-SPI2 (optional): Accessibility.Registry, Atspi
- `screenshot()` → PIL.ImageGrab or scrot (mocked)
- `snapshot()` → AT-SPI tree walk with role mapping (mocked)
- `click()`, `fill()`, `type_text()` → Atspi action interface (mocked)
- Lazy import: only imports atspi when actually used on Linux
- Tests: 18

### TASK-02: Linux Platform Detection
- Platform check in adapter factory: detect Linux → return LinuxAdapter
- Environment.is_linux property
- Graceful fallback: "Linux adapter requires python3-atspi" error
- Tests: 8

### TASK-03: Version Bump + Integration
- Version 0.41.0 → 0.42.0
- Tests: 9

**Total:** 35 new tests | **Expected suite:** 3,393
