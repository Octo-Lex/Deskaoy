# BATCH-33 BLUEPRINT — macOS Adapter (AXorcist-Pattern)

**Batch:** BATCH-33 | **Version:** v0.40.0 → v0.41.0 | **Cycle:** STANDARD | **AIV:** v5.3
**Lead:** Craft Agent (Lead Override per §5.3) | **Blueprint Version:** 1.0

## Strategic Bet
First non-Windows platform adapter — macOS accessibility via ApplicationServices/AXUIElement. Completes cross-platform SurfaceAdapter trio (1/3).

## Scope
- **IN**: MacOSAdapter SurfaceAdapter subclass, AX tree walk, click/type/screenshot, snapshot
- **OUT**: Real hardware testing (all mocked), Menu/Dock/Dialog macOS equivalents

## Hard Boundaries
| ID | Constraint |
|----|-----------|
| HB-01 | All tests mocked — no macOS hardware required |
| HB-02 | pyobjc is optional dependency only |
| HB-03 | Adapter must not import when on Windows/Linux |
| HB-04 | All baseline tests pass |

## Tasks (SEQUENTIAL)

### TASK-01: macOS Adapter Core
New module `src/agent_core/adapters/macos.py` — `MacOSAdapter(SurfaceAdapter)`.
- Uses pyobjc ApplicationServices (optional): AXUIElement, kAXError, CoreGraphics
- `screenshot()` → CGWindowListCreateImage (mocked)
- `snapshot()` → AXUIElementCopyAttributeValue tree walk (mocked)
- `click()`, `fill()`, `type_text()` → AXUIElement actions + CGEvent (mocked)
- Lazy import: only imports pyobjc when actually used on macOS
- Tests: 20

### TASK-02: macOS Platform Detection
- Platform check in adapter factory: detect macOS → return MacOSAdapter
- Environment.is_macos property
- Graceful fallback: "macOS adapter requires pyobjc" error when missing dep
- Tests: 10

### TASK-03: macOS Health Check
- Health check: surface returns True when adapter available, N/A when not macOS
- Optional subsystem check for pyobjc availability
- Tests: 5

### TASK-04: Version Bump + Integration
- Version 0.40.0 → 0.41.0
- Tests: 5

**Total:** 40 new tests | **Expected suite:** 3,358
