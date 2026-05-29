# Phase 1: Extract agent-core — COMPLETED ✅

> Separate the surface-agnostic 80% from the browser-specific 20%.
> The AI OS will consume `agent_core` as a package. Super Browser becomes
> a thin browser adapter consuming the shared engine.
>
> **Status**: COMPLETE — 65 files extracted, 24 tests, zero browser deps.
> 1141 total tests passing (1117 super_browser + 24 agent_core).

## Target Architecture

```
agent_core/                          (new package — surface-agnostic)
├── cascade/                         interaction cascade engine
│   ├── types.py                     Tier, TierAttempt, CascadeResult, AXNode, AXSnapshot
│   ├── cache.py                     TierPreferenceCache
│   └── protocol.py                  SurfaceAdapter ABC (click, type, snapshot, screenshot)
├── agent/                           agent loop and orchestration
│   ├── loop.py                      AgentLoop (takes SurfaceAdapter, not PageHandle)
│   ├── loop_detector.py             ActionLoopDetector
│   ├── registry.py                  ToolRegistry, @agent_action
│   ├── types.py                     StepResult, LoopNudge, PlanItem, etc.
│   ├── decorator.py                 @agent_action
│   ├── config.py                    AgentConfig
│   └── delegator.py                 SubagentDelegator
├── results/                         action result envelope
│   ├── types.py                     ActionResult, ActionError, ResultMeta, action_result()
│   └── output.py                    OutputDefender (3-level defense)
├── recovery/                        self-healing pipeline
│   ├── types.py                     ErrorType, RecoveryHint, WatchdogEvent, etc.
│   ├── coordinator.py               RecoveryCoordinator
│   ├── event_bus.py                 WatchdogEventBus
│   ├── classifier.py                ErrorClassifier
│   ├── checkpoint.py                CheckpointManager
│   ├── reflection.py                ReflectionEngine
│   ├── retry_tracker.py             RetryTracker
│   ├── format_validator.py          FormatValidator
│   └── watchdogs.py                 Watchdog implementations
├── verification/                    visual verification
│   ├── types.py                     VerificationLevel, PerceptualHash, etc.
│   ├── hasher.py                    dHash, pHash (no browser deps)
│   └── protocol.py                  VerifierAdapter ABC (snapshot, verify)
├── vision/                          VLM providers and grounding
│   ├── types.py                     CascadeConfig, VisionTaskComplexity, etc.
│   ├── controller.py                VisionController
│   ├── cache.py                     VisionCache
│   ├── providers.py                 AnthropicCUA, OpenAI, UITARS
│   ├── factory.py                   VisionProviderFactory
│   ├── ocr.py                       OCRGrounding
│   └── coords.py                    resize_coordinates, normalize_coordinates
├── skills/                          domain skill registry
│   ├── types.py                     DomainSkill, SkillProvenance, etc.
│   ├── registry.py                  SkillRegistry
│   └── markdown.py                  parse_markdown_skills
├── tracing/                         observability
│   ├── types.py                     SpanKind, TraceEvent, etc.
│   ├── flow_logger.py               FlowLogger
│   ├── sinks.py                     ConsoleSink, FileSink
│   ├── cost_analytics.py            CostAnalytics
│   ├── session_db.py                SessionDB
│   └── middleware.py                tracing middleware
├── budget/                          token cost governance
│   ├── types.py                     BudgetScope, BudgetConfig, TokenUsageRecord, etc.
│   ├── governor.py                  TokenBudgetGovernor
│   ├── cascade.py                   ModelCascade
│   ├── client.py                    BudgetAwareLLMClient
│   ├── compressor.py                ContextCompressor
│   ├── cost_estimator.py            CostEstimator
│   └── credential_pool.py           CredentialPool
├── security/                        action approval
│   └── approval.py                  ActionApproval
└── __init__.py

super_browser/                       (existing package — browser adapter)
├── browser/                         (unchanged) CDPBridge, BrowserSession, PageHandle
├── interaction/
│   ├── controller.py                MultimodalController (imports agent_core.cascade)
│   ├── snapshot.py                  SnapshotProvider (implements agent_core protocol)
│   └── vision.py                    VisionProviderFactory (browser-specific)
├── stealth/                         (unchanged) StealthManager, proxy, CAPTCHA
├── agent/
│   └── facade.py                    SuperBrowser facade (thin wiring layer)
├── results/
│   └── validation.py                PreExecutionValidator (DOM-specific)
└── __init__.py
```

## Key Abstractions (New Protocol Classes)

### 1. SurfaceAdapter — the platform contract

```python
# agent_core/cascade/protocol.py

from abc import ABC, abstractmethod
from typing import Any, Optional
from agent_core.results.types import ActionResult

class SurfaceAdapter(ABC):
    """Platform contract for the cascade engine.

    Implementations: BrowserAdapter (CDP), MacOSAdapter (AXUIElement),
    WindowsAdapter (UIA), LinuxAdapter (AT-SPI).
    """

    @abstractmethod
    async def click(self, target: str, **kwargs) -> ActionResult: ...

    @abstractmethod
    async def fill(self, target: str, value: str, **kwargs) -> ActionResult: ...

    @abstractmethod
    async def screenshot(self) -> bytes: ...

    @abstractmethod
    async def snapshot(self) -> Any: ...  # structural tree

    @abstractmethod
    async def evaluate(self, expression: str) -> Any: ...

    @abstractmethod
    async def key_press(self, key: str, modifiers: int = 0) -> ActionResult: ...

    @abstractmethod
    async def scroll(self, direction: str, amount: int) -> ActionResult: ...

    @abstractmethod
    async def type_text(self, text: str, delay_ms: float = 0) -> ActionResult: ...

    @abstractmethod
    def current_url(self) -> str: ...

    @abstractmethod
    async def current_title(self) -> str: ...
```

### 2. VerifierAdapter — verification without browser deps

```python
# agent_core/verification/protocol.py

from abc import ABC, abstractmethod

class VerifierAdapter(ABC):
    """Decouples VisualVerifier from CDPBridge/PageHandle."""

    @abstractmethod
    async def capture_screenshot(self) -> tuple[bytes, str]: ...  # (image_bytes, sha256)

    @abstractmethod
    async def capture_structural(self, url: str, title: str) -> Any: ...  # AX tree
```

## Files That Need Changes

### Extract (copy to agent_core, update imports)
48 source files + their 97 test files.

### Decouple (break browser dependencies)
| File | Change |
|------|--------|
| `agent/loop.py` | Takes `SurfaceAdapter` instead of accessing `_controller._page` directly |
| `agent/delegator.py` | Imports `SurfaceAdapter` protocol instead of `MultimodalController` |
| `verification/verifier.py` | Takes `VerifierAdapter` instead of `CDPBridge`/`PageHandle` |
| `recovery/coordinator.py` | Takes `SurfaceAdapter` protocol instead of `MultimodalController` |
| `recovery/checkpoint.py` | No changes (already uses strings, not browser objects) |

### Browser adapter (implements protocols)
| File | Change |
|------|--------|
| `interaction/controller.py` | Implements `SurfaceAdapter` protocol |
| `interaction/snapshot.py` | Implements `VerifierAdapter.capture_structural()` |
| `agent/facade.py` | Wires browser adapter → agent_core |

## Execution Order

### Batch 1: Foundation types (zero dependencies)
- `agent_core/results/types.py` — ActionResult, ActionError, ResultMeta
- `agent_core/results/typed.py` — ClickResult, FillResult, etc.
- `agent_core/cascade/types.py` — Tier, TierAttempt, AXNode, AXSnapshot
- `agent_core/budget/types.py` — BudgetScope, BudgetConfig, etc.
- `agent_core/recovery/types.py` — ErrorType, RecoveryHint, WatchdogEvent
- `agent_core/verification/types.py` — VerificationLevel, PerceptualHash
- `agent_core/vision/types.py` — VisionTaskComplexity, CascadeConfig
- `agent_core/tracing/types.py` — SpanKind, TraceEvent
- `agent_core/skills/types.py` — DomainSkill, SkillProvenance
- `agent_core/agent/types.py` — StepResult, LoopNudge, PlanItem

### Batch 2: Protocols (depend on Batch 1)
- `agent_core/cascade/protocol.py` — SurfaceAdapter ABC
- `agent_core/verification/protocol.py` — VerifierAdapter ABC

### Batch 3: Implementations (depend on Batch 1+2)
- All remaining modules — agent, recovery, vision, budget, tracing, skills, security
- Cascade cache, governor, event bus, hasher, providers, etc.

### Batch 4: Browser adapter (depends on Batch 3)
- `super_browser/interaction/controller.py` — implements SurfaceAdapter
- `super_browser/agent/facade.py` — thin wiring

### Batch 5: Test migration
- Update all 1147 test imports from `super_browser.X` to `agent_core.X`
- Browser-specific tests stay in `super_browser`

## Gate Criteria

1. `agent_core` has **zero imports** from `super_browser`
2. `super_browser` imports from `agent_core` (not the reverse)
3. All 1147 tests pass with new import paths
4. Demo scripts work identically
5. `pip install agent-core` works without Patchright/Pillow

## Effort Estimate

| Batch | Time | Risk |
|-------|------|------|
| Batch 1: Types | 4 hrs | Low (copy + rename imports) |
| Batch 2: Protocols | 2 hrs | Low (new ABC files) |
| Batch 3: Implementations | 8 hrs | Medium (decouple 3 browser deps) |
| Batch 4: Browser adapter | 4 hrs | Medium (implement protocols) |
| Batch 5: Test migration | 6 hrs | Low (find-replace imports) |
| **Total** | **~24 hrs** | |

## What This Unlocks

After Phase 1:
- **Phase 2** (Visual Grounding): `agent_core/detection/` adds YOLO, Florence-2, OCR
- **Phase 3** (Platform Adapters): `agent_core/adapters/macos.py` implements SurfaceAdapter
- **Phase 4** (Multi-App): `agent_core/orchestration/` coordinates multiple SurfaceAdapters
- **AI OS integration**: OS provides BudgetService, ModelRouter, SecurityService as implementations of agent_core protocols
