# Gap Analysis — Desktop Agent Current State

> Comprehensive assessment of what's built, what's missing, and what's next.

## Scorecard

| Area | Built? | Tests? | Notes |
|------|--------|--------|-------|
| AI-OS Contract (Agent Protocol) | ✅ | ✅ 36 tests | execute, estimate, undo, compensate |
| SurfaceAdapter protocol | ✅ | ✅ | 10 abstract methods, 2 implementations |
| BrowserAdapter | ✅ | ✅ 30 tests | Wraps MultimodalController |
| WindowsAdapter | ✅ scaffold | ⚠️ no tests | 515 lines, snapshot() is placeholder |
| macOSAdapter | ❌ | ❌ | Not started |
| LinuxAdapter | ❌ | ❌ | Not started |
| Visual Grounding Pipeline | ✅ types + pipeline | ✅ 115 tests | Types/fusion/anchor/tracker/render/weights work. ML deps optional |
| YOLO Detection (OmniParser v2) | ✅ code | ⚠️ mocked only | Works if ultralytics installed; no real-weight tests |
| Florence-2 Captioning | ✅ code | ⚠️ mocked only | Works if transformers installed |
| PaddleOCR | ✅ code | ⚠️ mocked only | Works if paddleocr installed |
| Grounding → VisionProvider wiring | ❌ | ❌ | Pipeline exists but not registered in VisionProviderFactory |
| curl_cffi stealth | ❌ | ❌ | Decided but never implemented |
| Agent Loop (plan→execute→verify) | ✅ | ✅ | Single flat loop |
| Multi-app orchestration | ❌ | ❌ | No HostAgent/AppAgent/DAG/Blackboard |
| Recovery (checkpoint, watchdog) | ✅ | ✅ | |
| Budget governance | ✅ | ✅ | |
| Loop detection | ✅ | ✅ | |
| Security (action approval) | ✅ | ✅ | |
| Stealth (anti-detection) | ✅ | ✅ | Fetch.requestPaused, proxy, CAPTCHA |
| Tracing | ✅ | ✅ | |
| Skills system | ✅ | ✅ | |
| Bezier mouse movement | ✅ | ✅ | |
| Input jitter/randomization | ✅ | ✅ | |
| CI pipeline | ✅ | ✅ | GitHub Actions |
| README | ✅ | — | Accurate but test count outdated |
| **1367 tests passing** | | | **0 regressions** |

---

## Gaps by Severity

### 🔴 Critical (broken or blocking real use)

1. **GroundingPipeline not wired into VisionProviderFactory**
   - `GroundingPipeline` implements `VisionProvider.locate()` but is never instantiated
     or registered in `VisionProviderFactory.from_env()`
   - `SB_VISION_DEFAULT_PROVIDER=grounding` does nothing because the factory doesn't
     know about it
   - **Impact**: The entire Phase 2 pipeline exists but can't be used
   - **Fix**: ~30 lines in `vision/factory.py` + env var check

2. **WindowsAdapter.snapshot() returns empty AXSnapshot**
   - Line 465: `# UI Automation integration is complex — placeholder for now`
   - Without real UIA tree data, the Windows adapter can only click by coordinates
   - **Impact**: Desktop automation on Windows is coordinate-only (Tier 2), no Tier 1
   - **Fix**: Integrate `comtypes` + `uiautomation` for real UIA tree walking

3. **No macOS / Linux adapters**
   - README advertises `macos/`, `windows/`, `linux/` adapters
   - Only Windows has a scaffold (and it's incomplete)
   - **Impact**: Can only automate browsers, not native desktop apps
   - **Fix**: Phase 3 work — macOS via ApplicationServices/AXUIElement, Linux via AT-SPI

### 🟡 Significant (limits capability, not broken)

4. **curl_cffi not wired into stealth stack**
   - Decision was made (curl_cffi over httpmorph) but never implemented
   - `StealthManager` uses CDP `Fetch.requestPaused` instead
   - **Impact**: Network-layer fingerprint (TLS, HTTP/2) not spoofed
   - **Fix**: Add `curl_cffi` session to `StealthManager`, route requests through it

5. **No real-weight integration tests for grounding**
   - All grounding ML tests use mocks
   - No test that actually loads YOLO weights and runs detection on a screenshot
   - **Impact**: We don't know if the pipeline actually works end-to-end
   - **Fix**: Add `--run-grounding` integration tests (gated, like `--run-integration`)

6. **DesktopAgent doesn't pass grounding confidence to actions**
   - `_confidence_from_action()` reads `visual_confidence` from `ActionResult.data`
   - But `BrowserAdapter` / `WindowsAdapter` never SET `visual_confidence` in data
   - The plumbing exists at both ends but nothing connects them
   - **Impact**: Confidence is always heuristic (0.9), never evidence-based
   - **Fix**: After grounding is wired into VisionProviderFactory, the cascade
     should propagate detection confidence through to ActionResult

7. **Single flat AgentLoop — no multi-app orchestration**
   - Can only automate one app at a time
   - No HostAgent coordinating multiple AppAgents
   - No DAG execution, no Blackboard pattern
   - **Impact**: Cannot automate workflows across apps (e.g., "read email → create task in Notion")
   - **Fix**: Future phase — significant architectural addition

8. **12 skipped MEDIUM issues from cross-layer report**
   - M3: Vision providers not wired (related to gap #1)
   - M5: VLM_FULL tier is stub
   - M8: No 3-tier CrashWatchdog
   - M9: StaleElementWatchdog is coarse
   - M10: No text similarity scoring for selectors
   - M13: No circuit breaker
   - M14: No Chrome header morphing
   - M17: No async I/O batching
   - M18: SQLiteSink not async
   - M20: Header redaction partial
   - M22: Recovery private attr access

### 🟢 Minor (polish, not blocking)

9. **README test count outdated** — Says "1141 tests", actually 1367

10. **`test_zero_distance` pre-existing failure** — Bezier duration for 0-distance
    exceeds config minimum. One-line fix in `input/bezier.py`.

11. **No `.editorconfig` / code style enforcement** — Inconsistent formatting

12. **No `scripts/download_weights.py`** — Users need manual weight download

13. **pyproject.toml name is still "super-browser"** — Should be "desktop-agent" or "agent-core"

---

## What's Actually Proven (End-to-End Paths)

These paths work from top to bottom with real tests:

1. **AI-OS → DesktopAgent → BrowserAdapter → MultimodalController → Mock** ✅
   - 36 contract tests + 30 adapter tests

2. **AI-OS → DesktopAgent → WindowsAdapter → Mock** ✅ (partially)
   - Windows adapter exists but no dedicated tests

3. **Browser end-to-end** ✅
   - 30 integration tests with real headless Chromium
   - Demo scripts browsing example.com, Wikipedia, HN

4. **Visual grounding types + fusion + anchors** ✅
   - 115 unit tests, zero ML deps needed

## What's NOT Proven

1. ❌ GroundingPipeline → real YOLO detection → real screenshot
2. ❌ DesktopAgent → WindowsAdapter → real desktop app
3. ❌ DesktopAgent → BrowserAdapter → grounding pipeline → real VLM-free click
4. ❌ curl_cffi stealth against real anti-bot system
5. ❌ Multi-app workflow (e.g., browser + desktop app coordinated)

---

## Recommended Next Steps (Priority Order)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 1 | **Wire GroundingPipeline into VisionProviderFactory** | 1h | Unblocks the entire grounding pipeline |
| 2 | **Add `--run-grounding` integration test with real weights** | 3h | Proves Phase 2 actually works |
| 3 | **Fix `test_zero_distance`** | 15m | Clean test suite |
| 4 | **Update README + pyproject name** | 30m | Honest marketing |
| 5 | **Windows UIA tree walking (real snapshot)** | 8h | Enables Tier 1 on Windows desktop |
| 6 | **Wire curl_cffi into StealthManager** | 6h | Network-layer stealth |
| 7 | **Connect grounding confidence through BrowserAdapter** | 2h | Evidence-based confidence |
| 8 | **macOS adapter (AXUIElement)** | 12h | Cross-platform desktop |
| 9 | **Multi-app orchestration (HostAgent)** | 20h | Cross-app workflows |
| 10 | **Linux adapter (AT-SPI)** | 12h | Full platform coverage |

Items 1-4 can be done right now, in this session.
