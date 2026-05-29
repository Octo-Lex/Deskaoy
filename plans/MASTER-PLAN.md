# Desktop Agent — Master Plan

> Surface-agnostic agent engine for the AI Operating System.
> Perceives any screen, acts on any element, recovers from failures autonomously.

---

## Architecture

```
AI Operating System
│
▼ Agent Protocol (AgentGoal → execute → AgentResult)
┌──────────────────────────────────────────────────────────────┐
│                       DesktopAgent                            │
│  os_types.py · desktop_agent.py                              │
│  execute() · estimate() · undo() · compensate()              │
│  Action Memory · Confidence · Mutation Tracking               │
└─────────────────────┬────────────────────────────────────────┘
                      │ SurfaceAdapter protocol (17 methods)
           ┌──────────┼──────────┬──────────────┐
           ▼          ▼          ▼              ▼
     BrowserAdapter  Windows   macOS        Linux
     (Patchright)   (UIA) ✅  (AXUIElement)  (AT-SPI)
          │
     MultimodalController
     ┌────┴────────────────────┐
     │ 3-Tier Interaction Cascade │
     │ Tier 1: Selector/AX tree  │  free, ~5ms   (85%)
     │ Tier 2: Coordinate click  │  free, ~10ms  (10%)
     │ Tier 3: Vision grounding  │  local/cloud  (5%)
     └───────────────────────────┘
                      │
              Action Memory
              ┌────┴──────────────────┐
              │ WRITE: after every    │
              │   action (AgentLoop   │
              │   + cascade + Desktop)│
              │ READ: before dispatch │
              │   inject cached sel.  │
              │ HEAL: on tier-1 fail  │
              │   replay cached path  │
              └───────────────────────┘
```

---

## Current Numbers

| Metric | Value |
|--------|-------|
| Package | `desktop-agent` **v0.12.1** |
| **Tests passing** | **1,858** |
| Tests skipped | 36 |
| Tests failing | **0** |

---

## Source Map

### agent_core — 15,958 lines (zero browser deps)

```
agent_core/
├── __init__.py                 Public API exports
├── os_types.py                 280 lines — AI-OS contract types
├── desktop_agent.py            840 lines — DesktopAgent protocol impl
│
├── adapters/                   ~1,621 lines
│   ├── windows.py              807 lines — WindowsAdapter (17 methods, UIA, dry_run)
│   ├── uia_walker.py           ~690 lines — UIA tree walker (comtypes + compound fields)
│   └── electron.py             120 lines — Electron app CDP registry
│
├── agent/                      1,117 lines
│   ├── loop.py                 AgentLoop (plan→execute→verify cycle)
│   ├── registry.py             ToolRegistry + register_definition()
│   ├── delegator.py            SubagentDelegator
│   ├── loop_detector.py        3-level loop detection
│   └── types.py                LoopResult, StepResult, PlanItem
│
├── budget/                     1,326 lines
│   ├── cascade.py              5-tier model cascade (Haiku→Opus)
│   ├── cost_estimator.py       Token cost prediction
│   ├── credential_pool.py      API key rotation
│   ├── governor.py             Budget governance
│   └── types.py                CostTier, CascadeTier
│
├── cascade/                    ~1,106 lines
│   ├── protocol.py             SurfaceAdapter + CascadeProvider
│   ├── cache.py                Selector cache
│   ├── formatter.py            4-pass AX snapshot formatter (filter→dedup→prune→collapse)
│   ├── resolver.py             3-tier stale-ref resolver (exact→stable→reidentify)
│   └── types.py                ActionMethod, ClickResult, MatchLevel, ElementFingerprint
│
├── grounding/                  1,486 lines
│   ├── pipeline.py             GroundingPipeline (VisionProvider impl)
│   ├── detector.py             OmniParser v2 YOLO detector
│   ├── fusion.py               IoU dedup + structural priority
│   ├── captioner.py            Florence-2 captioning
│   ├── paddle_ocr.py           PaddleOCR text extraction
│   ├── som_renderer.py         Set-of-Mark renderer
│   ├── anchor.py               Stable element IDs
│   ├── tracker.py              Cross-frame tracking
│   ├── weight_manager.py       HuggingFace weight cache
│   └── types.py                BBox, Detection, FusedElement
│
├── input/                      422 lines
│   ├── bezier.py               Bézier mouse curves
│   ├── jitter.py               Timing + position jitter
│   └── types.py                HumanizationConfig
│
├── interaction/                68 lines
│   └── decorator.py            @agent_action decorator
│
├── hooks.py                    ~100 lines — Plugin lifecycle hooks (9 events)
│
├── utils/
│   └── shape.py                ~90 lines — JSON shape inference for LLM budgets
│
├── pipeline/                   ~260 lines — Deterministic action pipelines
│   ├── types.py                PipelineStep, PipelineDefinition
│   ├── executor.py             PipelineExecutor (zero-LLM dispatch)
│   ├── registry.py             PipelineRegistry + fuzzy matching
│   └── builtins/               Pre-built pipelines (notepad_type, etc.)
│
├── llm/                        332 lines
│   └── client.py               SimpleLLMClient (OpenAI / Anthropic)
│
├── memory/                     1,542 lines
│   ├── store.py                ActionMemory (LRU + per-domain JSON)
│   ├── types.py                ActionEvidence, Anchor, TierRecord
│   ├── fingerprint.py          Intent fingerprinting
│   ├── matching.py             Anchor matching + recall
│   └── healer.py               Self-healing selector recovery
│
├── recovery/                   1,788 lines
│   ├── coordinator.py          RecoveryCoordinator
│   ├── checkpoint.py           CheckpointManager (JSON persistence)
│   ├── session_recovery.py     Session-level recovery
│   ├── watchdogs.py            CrashWatchdog (3-tier) + StaleElementWatchdog
│   ├── event_bus.py            WatchdogEventBus
│   └── types.py                RecoveryEvent, RecoveryAction
│
├── results/                    522 lines
│   ├── types.py                ActionResult, ResultMeta
│   └── typed.py                Typed result builders
│
├── security/                   348 lines
│   └── types.py                SecurityLevel, SecurityCheckResult
│
├── skills/                     605 lines
│   ├── registry.py             SkillRegistry
│   └── types.py                SkillDefinition
│
├── tracing/                    1,008 lines
│   ├── flow_logger.py          FlowLogger + secret redaction
│   └── sinks.py                Console, File, SQLite, Prometheus sinks
│
├── verification/               817 lines
│   ├── protocol.py             VerificationLevel enum
│   ├── verifier.py             Look-act-verify (VLM_FULL wiring)
│   └── types.py                VerificationResult
│
└── vision/                     1,396 lines
    ├── factory.py              VisionProviderFactory
    ├── providers.py            Anthropic + OpenAI + Grounding providers
    ├── cache.py                VisionResult cache
    ├── ocr.py                  OCR engine
    └── types.py                VisionRequest, VisionResponse
```

### super_browser — 5,375 lines (browser adapter)

```
super_browser/
├── adapters/                   229 lines
│   └── browser.py              BrowserAdapter (wraps MultimodalController)
├── agent/                      574 lines
│   ├── facade.py               SuperBrowser facade + _NoOpLLM
│   ├── loop.py                 BrowserAgentLoop
│   ├── delegator.py            Browser delegator
│   └── registry.py             Browser tool registry
├── browser/                    693 lines
│   ├── cdp.py                  CDP bridge
│   ├── session.py              BrowserSession (Patchright)
│   ├── page.py                 Page handle
│   └── config.py               SessionConfig
├── interaction/                1,101 lines
│   ├── controller.py           MultimodalController (3-tier cascade + memory + fuzzy)
│   ├── decorator.py            @agent_action for browser
│   ├── cache.py                Selector cache
│   ├── snapshot.py             AX snapshot provider
│   ├── types.py                Action types
│   └── vision.py               Vision interaction
├── stealth/                    1,055 lines
│   ├── manager.py              StealthManager (curl_cffi Chrome 146)
│   ├── diagnostics.py          Stealth diagnostics
│   └── types.py                StealthConfig
├── security/                   684 lines
│   └── manager.py              SecurityManager
├── verification/               448 lines
│   ├── verifier.py             VLM_FULL verification
│   └── hasher.py               Perceptual hash
├── vision/                     71 lines
│   ├── factory.py              Browser vision factory
│   └── ocr.py                  Browser OCR
├── recovery/                   97 lines
│   ├── coordinator.py          Browser recovery coordinator
│   ├── checkpoint.py           Browser checkpoint
│   ├── session_recovery.py     Browser session recovery
│   └── event_bus.py            Browser event bus
├── budget/                     58 lines
│   └── cascade.py              Browser budget cascade
├── results/                    168 lines
│   ├── output.py               OutputDefender
│   └── types.py                Result types
├── skills/                     43 lines
│   └── activation.py           Skill activation
└── tracing/                    48 lines
    └── flow_logger.py          Browser flow logger
```

---

## Completed Work

### Phase 0 — Critical Bug Fixes ✅

5 critical + 8 high + 10 medium issues fixed.

| Fix | Area | What Changed |
|-----|------|-------------|
| C1 | Agent loop | Nudge parameter for loop detection warning injection |
| C2 | Agent loop | Removed broken recovery coordinator guard |
| C3 | Results | Preview-length tracking for budget (spill-to-disk) |
| C4 | Security | `@agent_action` accepts `security_level` param |
| C5 | Delegation | Subsystem passthrough in SubagentDelegator |
| H1 | Stealth | `Fetch.requestPaused` over detectable CDP injection |
| H2 | Recovery | Fail-fast without LLM in `act()` |
| H3 | Vision | Page fingerprint for cache invalidation |
| H4 | Budget | Budget cascade across tiers |
| H5 | Budget | Context compressor with importance scoring |
| H6 | Recovery | Checkpoint persistence (JSON over git) |
| H7 | Interaction | JS safety via `json.dumps()` |
| H8 | Vision | Vectorized 2D DCT (numpy matrix multiply) |

### Phase 1 — Agent-Core Extraction ✅

Separated the surface-agnostic engine from browser-specific code into `agent_core/`. 54 new implementation files. Zero `super_browser` imports in agent_core. Re-export shims in super_browser for backward compatibility.

**Input layer built:** Bézier mouse curves + timing jitter + win32gui window isolation + DPI awareness + randomized offsets.

### Phase 1.5 — AI-OS Contract Implementation ✅

DesktopAgent implements the Agent Protocol v2.2 from `PLATFORM_CONTRACT.md`:
- `execute(goal, context) → AgentResult` — routes to single action or multi-step automate
- `estimate(goal, context) → AgentEstimate` — cost/latency/confidence prediction
- `undo(execution_id, snapshot) → UndoResult` — best-effort inverse action replay
- `compensate(execution_id, snapshot) → UndoResult` — manual instructions for external actions
- `dry_run` support on all mutating actions
- `action_class` hierarchy: read_only → recoverable → draftable → sensitive → external → irreversible
- `MutationRecord` with before/after state on every mutating action
- Evidence-based confidence from grounding pipeline

### Phase 2 — Visual Grounding + Stealth + Wiring ✅

**Visual grounding pipeline:**
```
Screenshot → YOLO (OmniParser v2) + PaddleOCR + AX Tree
                ↓
         Fusion Engine (structural > visual > text)
                ↓
         Florence-2 Captions
                ↓
         FusedElement[] → Set-of-Mark screenshot
```
- Fusion priority: Structural (AX, conf≥0.95) > Visual (YOLO) > Text (OCR)
- ~100ms GPU, ~300ms CPU, $0 per call
- Graceful degradation without ML deps

**curl_cffi stealth:** Chrome 146 TLS fingerprint, HTTP/2, 53 browser targets.

**BrowserAdapter wiring:** Wraps MultimodalController → gets 3-tier cascade for free.

### Phase 3 — Platform Adapters (Windows Complete) ✅

**WindowsAdapter — 807 lines, 17 SurfaceAdapter methods, 36 tests:**

| Method | Type | Notes |
|--------|------|-------|
| `screenshot()` | read | pyautogui screenshot, window-rect cropped |
| `snapshot()` | read | UIA tree walker → AXSnapshot |
| `current_url()` | read | `win32://<title>` pseudo-URL |
| `current_title()` | read | win32gui.GetWindowText |
| `evaluate()` | read | Not supported on desktop |
| `abort()` | control | Sets abort flag |
| `click(target)` | mutate | pyautogui + Bezier move, dry_run |
| `fill(target, value)` | mutate | Select all + type, dry_run |
| `type_text(text)` | mutate | Char-by-char with jitter, dry_run |
| `key_press(key)` | mutate | Combo parsing (ctrl+a), dry_run |
| `scroll(direction, amount)` | mutate | pyautogui vscroll/hscroll, dry_run |
| `hover(target)` | mutate | Bezier move without click |
| `wait_for_selector(target)` | read | Exponential backoff UIA polling |
| `select_option()` | stub | Returns "not supported" |
| `navigate()` | stub | Returns "not supported" |
| `supports_navigation` | prop | False |
| `supports_select` | prop | False |

**UIA Tree Walker — 640 lines, 40 tests:**
- comtypes direct (no pywinauto dependency)
- ControlViewWalker by default (skips decorative elements)
- Hard caps: max 500 elements, max depth 8
- Lazy COM initialization, zero overhead until first `walk()`
- Per-element threading timeout (0.3s) prevents hangs on dead windows

### Action Memory + Self-Healing ✅

**1,542 lines source + 1,546 lines tests = 119 new tests.**

Three feedback paths fully wired:

| Path | Location | What It Does |
|------|----------|-------------|
| **WRITE** | AgentLoop `_record_step_evidence()` + cascade `_record_cascade_evidence()` + DesktopAgent `_record_to_memory()` | Records evidence after every action |
| **READ** | AgentLoop `_try_memory_recall()` | Injects cached selector before dispatch |
| **HEAL** | Cascade `_try_memory_heal()` | Replays cached path on tier-1 failure |

Keyed by intent hash `hash(intent, surface, domain)` — finds elements by *what you're trying to do*, not *how you found them*.

### Medium Issues Cleanup ✅

9 issues closed, 31 new tests, zero regressions:

| ID | Issue | Fix |
|----|-------|-----|
| M22 | Recovery `_page` private attr | Public `page` property |
| M17 | FileSink sync flush | `asyncio.to_thread()` |
| M18 | SQLiteSink sync flush | `asyncio.to_thread()` + sync fallback |
| M20 | Header redaction URL-only | Regex Bearer/API key/token patterns |
| M13 | CircuitBreaker not in cascade | Skip open tiers, record success/fail |
| M10 | No fuzzy selector matching | `difflib.get_close_matches()` on AX names |
| M9 | StaleElementWatchdog coarse | Interactive element fingerprints |
| M5 | VLM_FULL is stub | Wire `vlm_compare_fn` into verifier |
| M8 | CrashWatchdog 1-tier | 3-tier: process → CDP → target check |

### Integration Proof ✅

**SimpleLLMClient** — thin wrapper around OpenAI / Anthropic that implements `propose_action()`, `create_plan()`, `replan()`. AgentLoop can drive real LLMs.

**`scripts/demo_desktop_agent.py`** — launches Notepad → LLM plans → agent types → UIA tree verifies.

**4 integration tests** (gated behind `--run-integration`):
- `test_type_in_notepad` — real LLM + real desktop, verifies "Hello World" appears
- `test_single_action_click` — single-action dispatch without AgentLoop
- `test_dry_run_does_not_mutate` — dry run safety proof
- `test_memory_records_execution` — action memory populates after real run

**`register_definition()`** on ToolRegistry — registers pre-built ToolDefinitions for adapter methods.

---

## Dependency Map

```
agent_core (zero browser deps):
  stdlib + Pillow + numpy

agent_core [llm] (optional):
  openai >= 1.0
  anthropic >= 0.30

super_browser [browser]:
  agent_core + Patchright + psutil + Pillow + curl_cffi

grounding (optional ML):
  ultralytics + transformers + paddleocr + torch + accelerate
```

---

## Test Map

```
tests/                              1,661 passed + 36 skipped
├── test_agent_core/                37 tests — contract + core
├── test_llm/                       24 tests — JSON extraction, LLM init, register
├── test_adapters/
│   ├── test_browser_adapter.py     30 tests — BrowserAdapter
│   ├── test_windows_adapter.py     36 tests — WindowsAdapter protocol
│   └── test_uia_walker.py          40 tests — UIA tree walking
├── test_agent/                     ~30 tests — loop, delegation, registry
├── test_memory/                    119 tests — store, fingerprint, heal, feedback loop
├── test_grounding/                 129 tests — detection, fusion, pipeline, anchors
├── test_input/                     45 tests — Bézier, jitter, safety
├── test_stealth/                   34 tests — stealth + curl_cffi
├── test_vision/                    10 tests — grounding wiring
├── test_tracing/                   ~25 tests — flow logger, sinks
├── test_cascade/                   ~35 tests — formatter, resolver, cache
├── test_pipeline/                  ~15 tests — executor, registry, builtins
├── test_utils/                      ~10 tests — shape inference
├── test_hooks.py                     ~8 tests — plugin lifecycle
├── test_recovery/                  ~35 tests — checkpoint, coordinator, watchdogs
├── test_budget/                    ~20 tests — cascade, compressor
├── test_verification/              ~20 tests — verifier, hasher
├── test_interaction/               ~25 tests — controller, decorator
├── test_results/                   ~15 tests — output defender
├── test_skills/                    ~10 tests — registry
├── test_browser/                   ~15 tests — CDP, session
├── integration/                    30 browser + 4 desktop-agent live tests
│   ├── test_browser_basic.py
│   ├── test_controller_cascade.py
│   ├── test_verification.py
│   ├── test_vision_pipeline.py
│   ├── test_output.py
│   ├── test_recovery_io.py
│   └── test_desktop_agent_live.py  4 live tests (gated)
```

---

## Remaining Work

### Phase 3B — OpenCLI Gems Integration ✅

8 high-value patterns extracted from OpenCLI (v1.7.8, 30K lines TS + 85K lines adapters), adapted for our Python desktop agent. Full analysis in `plans/OPENCLI-GEMS.md`, implementation plan in session plan.

| Gem | What | Batch | Effort | Tests | Status |
|-----|------|-------|--------|-------|--------|
| **G11** Error Envelopes | `ActionError` + `code`/`hint`/`candidates` — LLM self-corrects | 1 | 2h | 14 | ✅ |
| **G8** Hook System | 9 lifecycle hooks (`on_step_start`, `on_memory_record`, etc.) | 1 | 2h | 8 | ✅ |
| **G7** Shape Inference | `infer_shape(data)` → flat type map, cuts LLM tokens | 1 | 2h | 14 | ✅ |
| **G9** Snapshot Formatter | 4-pass AX tree cleanup (filter→dedup→prune→collapse) | 2 | 4h | 16 | ✅ |
| **G1** Stale-Ref Resolver | 3-tier fingerprint recovery (exact→stable→reidentify) | 2 | 6h | 20 | ✅ |
| **G5** Compound Fields | Rich UIA metadata (combobox options, date formats, file filters) | 2 | 2h | 0* | ✅ |
| **G4** Deterministic Pipelines | Zero-LLM action sequences for known workflows | 3 | 5h | 14 | ✅ |
| **G10** Electron Registry | CDP control of Cursor/Notion/VS Code (bypasses UIA) | 3 | 2h | 11 | ✅ |

*G5 tests integrated into resolver + formatter tests (CompoundInfo type in types.py)*

**New files:** `hooks.py`, `utils/shape.py`, `cascade/formatter.py`, `cascade/resolver.py`, `pipeline/` package, `adapters/electron.py`
**Result:** 97 new tests, ~1,800 new source lines, version **v0.4.0**
**Key outcomes:** Token-efficient page state (formatter), 3-tier stale element recovery (resolver), $0.00 for known workflows (pipelines), LLM self-correction (error hints), plugin extensibility (hooks)

### Phase 3C — macOS + Linux Adapters 🔲

| Adapter | OS | API | Status | Effort |
|---------|-----|-----|--------|--------|
| Windows | Win10/11 | UI Automation (comtypes) | **✅ Complete** | Done |
| macOS | 12+ | AXUIElement (pyobjc) | Not started | 12h |
| Linux | X11/Wayland | AT-SPI (pyatspi) | Not started | 12h |

Both follow the same pattern proven by WindowsAdapter: 17 methods, SurfaceAdapter protocol, dry_run, UIA/AX/AT-SPI tree walking.

### Phase 4 — Multi-App Orchestration ✅

| Feature | Description | Status |
|---------|-------------|--------|
| Blackboard | Shared key-value store with async wait | ✅ `orchestration/blackboard.py` |
| DAG Executor | Topological sort + parallel execution | ✅ `orchestration/dag.py` |
| AppAgent | Per-app scoped agent with blackboard I/O | ✅ `orchestration/app_agent.py` |
| HostAgent | LLM decomposition + template matching + DAG orchestration | ✅ `orchestration/host_agent.py` |
| Templates | 3 built-in patterns (email→task, screenshot→note, copy→paste) | ✅ `orchestration/templates.py` |
| DesktopAgent wiring | `orchestrate` capability + routing | ✅ `desktop_agent.py` |

**Enables:** "Read email → create task in Notion → send Slack notification"

### Phase 5 — Production Hardening ✅

| Feature | Description | Status |
|---------|-------------|--------|
| Action Rate Governor | Token-bucket rate limiter per action type | ✅ `safety/rate_governor.py` |
| Crash Recovery Persistence | Agent state save/resume across process kills | ✅ `recovery/crash_recovery.py` |
| Latency Budgets | Per-action p50/p95/p99 with violation tracking | ✅ `safety/latency_budget.py` |
| LLM Cost Tracker | Token usage + cost estimation + budget enforcement | ✅ `safety/cost_tracker.py` |
| Health Check | 6-probe readiness/liveness check | ✅ `safety/health.py` |
| CI Smoke + Benchmarks | Pipeline lifecycle smoke + latency benchmarks | ✅ `smoke/`, `benchmarks/`, CI workflow |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent core separation | `agent_core` package, zero browser deps | Surface-agnostic engine |
| Contract-first | AI-OS types before features | Every feature feeds contract shape |
| Browser adapter | Wraps MultimodalController, not raw CDP | Gets 3-tier cascade for free |
| Grounding as VisionProvider | Drop-in `locate()` protocol | Zero changes to cascade engine |
| curl_cffi over httpmorph | More mature, Chrome 99–146, HTTP/3 | Regular fingerprint updates |
| OmniParser v2 | Microsoft Research, 39.5% ScreenSpot Pro | Proven on OSWorld |
| Lazy ML model loading | Load on first use, not import | <100ms import without torch |
| Bezier mouse + win32gui | pyautogui + Bézier + window isolation | Anti-detection for timing analysis |
| Confidence from evidence | Grounding → ActionResult.data.visual_confidence | Not heuristic |
| Graceful degradation | Works without ML/curl_cffi | Zero-cost import, optional power |
| comtypes direct (no pywinauto) | ~30 lines for IUIA singleton | pywinauto adds ~200K unneeded lines |
| Memory keyed by intent | `hash(intent, surface, domain)` | Finds by *what*, not *how* |
| SimpleLLMClient dual-provider | OpenAI + Anthropic, auto-detect | Most users have at least one key |
| register_definition() | Direct ToolDefinition registration | Adapters need custom names/params |
| gpt-4o-mini default | Cheapest model that follows instructions | ~$0.001 per demo run |

---

## File Map

```
desktop-agent/
├── src/
│   ├── agent_core/                    ~17,600 lines
│   │   ├── __init__.py
│   │   ├── os_types.py                AI-OS contract types
│   │   ├── desktop_agent.py           DesktopAgent protocol impl
│   │   ├── hooks.py                   Plugin lifecycle hooks (9 events)
│   │   ├── adapters/
│   │   │   ├── windows.py             WindowsAdapter (UIA + pyautogui + Bézier)
│   │   │   ├── uia_walker.py          UIA tree walker + compound fields (comtypes)
│   │   │   └── electron.py            Electron app CDP registry
│   │   ├── agent/                     loop, registry, delegation, loop detection
│   │   ├── budget/                    token governance, model cascade
│   │   ├── cascade/                   SurfaceAdapter protocol, cache, formatter, resolver
│   │   ├── grounding/                 YOLO + OCR + fusion + caption pipeline
│   │   ├── input/                     Bézier curves, jitter, humanization
│   │   ├── interaction/               @agent_action decorator
│   │   ├── llm/                       SimpleLLMClient (OpenAI / Anthropic)
│   │   ├── memory/                    action memory + self-healing grounding
│   │   ├── pipeline/                  deterministic action pipelines (zero-LLM)
│   │   ├── recovery/                  checkpoint, watchdog bus, error classification
│   │   ├── results/                   ActionResult envelope + rich error codes
│   │   ├── security/                  action approval, injection detection
│   │   ├── skills/                    domain automation
│   │   ├── tracing/                   event logging, sinks, secret redaction
│   │   ├── utils/                     shape inference, helpers
│   │   ├── verification/              look-act-verify, VLM_FULL wiring
│   │   └── vision/                    VLM providers, OCR, grounding factory
│   │
│   └── super_browser/                 5,375 lines
│       ├── adapters/browser.py        BrowserAdapter (SurfaceAdapter impl)
│       ├── agent/                     facade, loop, delegation
│       ├── browser/                   CDP bridge, Patchright session, page handle
│       ├── interaction/               MultimodalController (3-tier cascade + memory)
│       ├── stealth/                   Anti-detection (curl_cffi Chrome 146)
│       ├── security/                  DOM injection/redaction
│       ├── verification/              perceptual hash, VLM verify
│       └── ...                        budget, recovery, results, skills, tracing, vision
│
├── tests/                             20,382 lines (1,661 passing)
│   ├── test_agent_core/              contract + core tests
│   ├── test_llm/                     SimpleLLMClient + JSON extraction
│   ├── test_adapters/                browser + windows + UIA walker
│   ├── test_memory/                  store, fingerprint, heal, feedback loop
│   ├── test_grounding/               detection, fusion, pipeline, anchors
│   ├── test_input/                   Bézier, jitter, safety
│   ├── test_agent/                   loop, delegation, registry
│   ├── test_stealth/                 stealth + curl_cffi
│   ├── test_vision/                  grounding wiring
│   ├── integration/                  30 browser + 4 live desktop tests
│   └── ...                           recovery, budget, tracing, verification, etc.
│
├── scripts/
│   ├── demo_e2e.py                   Browser demo (example.com)
│   ├── demo_complex_site.py          Browser demo (Wikipedia + HN + httpbin)
│   └── demo_desktop_agent.py         Desktop demo (Notepad + LLM → type text)
│
├── plans/
│   ├── MASTER-PLAN.md                This file
│   ├── REASSESSMENT.md               Gap analysis
│   ├── AI-OS-CONTRACT-GAP.md         Contract compliance gaps
│   ├── AI-OS-CONTRACT-IMPLEMENTATION.md
│   ├── BROWSER-ADAPTER-WIRING.md
│   ├── CURL-CFFI-ANALYSIS.md
│   ├── GAP-ANALYSIS.md
│   ├── INPUT-FEEDBACK-ANALYSIS.md
│   ├── PHASE-1-AGENT-CORE-EXTRACTION.md
│   ├── PHASE-2-VISUAL-GROUNDING-V2.md
│   ├── PHASE-3-INTEGRATION-TESTS.md
│   └── OPENCLI-GEMS.md         OpenCLI pattern extraction (12 gems)
│
├── sessions/260426-nimble-wave/plans/
│   ├── ACTION-MEMORY-DESIGN.md
│   ├── CLOSE-FEEDBACK-LOOP.md
│   ├── INTEGRATION-PROOF.md
│   ├── MEDIUM-ISSUES-CLEANUP.md
│   ├── UIA-TREE-WALKER-IMPLEMENTATION.md
│   └── WINDOWS-ADAPTER-COMPLETION.md
│
└── .github/workflows/tests.yml       CI pipeline
```

---

## How to Use

```bash
# Install core + dev tools
pip install -e ".[dev]"

# With browser support (Patchright + curl_cffi)
pip install -e ".[browser,dev]"

# With LLM support (OpenAI / Anthropic)
pip install -e ".[llm]"

# With ML grounding (optional, ~2GB)
pip install -e ".[grounding]"

# Run tests
pytest tests/ -q                              # 1,661 tests, ~12s
pytest tests/ -m grounding -v                 # Weight-gated grounding tests
pytest tests/ --run-integration -q            # Real Chromium + real desktop tests

# Browser demo
python scripts/demo_e2e.py                    # Browses example.com

# Desktop agent demo (Windows + LLM)
set OPENAI_API_KEY=sk-...
python scripts/demo_desktop_agent.py --task "Type Hello World"

# Configure grounding
export SB_VISION_DEFAULT_PROVIDER=grounding
export SB_GROUNDING_ENABLED=true

# Configure stealth
# curl_cffi auto-used when installed
```

---

## Version History

| Version | Date | Tests | What Changed |
|---------|------|-------|-------------|
| v0.1.0 | 2025-04 | 1,086 | Phase 0: critical + high bug fixes |
| v0.1.5 | 2025-04 | 1,221 | Phase 1: agent-core extraction + input layer |
| v0.2.0 | 2025-04 | 1,388 | Phase 2: grounding + stealth + BrowserAdapter wiring |
| v0.3.0 | 2025-04 | 1,661 | Phase 3A: Windows adapter + memory + feedback loop + medium issues + LLM client |
| v0.4.0 | 2025-04 | 1,758 | Phase 3B: OpenCLI gems — error envelopes, hooks, shape inference, formatter, stale-ref resolver, pipelines, electron registry |
| v0.5.0 | 2025-04 | 1,766 | Phase 3B wiring: pipeline fast-path, formatter default, resolver in cascade, hooks on execute, 8 wiring tests |
| v0.6.0 | 2025-04 | 1,817 | AI-OS realignment: capability manifest, storage resolver, policy bridge, trace bridge, result mapper, recovery bridge, 51 alignment tests |
| v0.7.0 | 2025-04 | 1,842 | Realignment complete: learning evidence, stealth gate, model artifacts, AIOS_HOME memory storage, 25 phase 8-9 tests |
| v0.8.0 | 2025-04 | 1,858 | Bridge wiring: policy preflight, trace spans, result mapper, recovery bounds, storage resolver — all functional in execution paths, 16 wiring tests |
| v0.9.0 | 2025-04 | 1,903 | gogcli patterns: expanded status codes, circuit breaker, action guard filtering, machine-readable schema, retry with backoff + jitter — 45 tests |
| v0.10.0 | 2025-04 | 1,961 | LangExtract patterns: post-action grounding verification (4-tier), pre-flight instruction validation, step context window — 58 tests |
| v0.11.0 | 2025-04 | 2,036 | Phase 5 hardening: rate governor, crash recovery, latency budgets, cost tracker, health check — 75 new tests |
| v0.12.0 | 2025-04 | 2,107 | Phase 4 orchestration: blackboard, DAG executor, AppAgent, HostAgent, templates — 71 new tests |
| v0.12.1 | 2025-04 | 2,139 | Phase 5F: CI smoke tests (25) + benchmark harness (7) + updated CI workflow |
