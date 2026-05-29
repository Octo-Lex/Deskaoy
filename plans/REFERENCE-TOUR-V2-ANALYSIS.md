# Reference Tour: OSWorld, UI-TARS, Skyvern, Stagehand

> Deep-dive analysis of 4 reference repos for patterns applicable to Desktop Agent v0.15.0+

---

## 1. OSWorld — Benchmark Environment for Desktop Agents

**Repo:** `OSWorld-main` (~15k lines Python)
**What it is:** A Gymnasium-based benchmark for evaluating desktop AI agents. Runs tasks in VMs (VMware, Docker, AWS, GCP) with screenshot + accessibility tree observations.

### Key Patterns

| Pattern | Where | Our Gap | Adopt? |
|---------|-------|---------|--------|
| **Formal Action Space** | `desktop_env/actions.py` — 15 action types (MOVE_TO, CLICK, DRAG_TO, SCROLL, TYPING, PRESS, HOTKEY, WAIT, FAIL, DONE) with typed parameter ranges | Our CAPABILITIES dict is metadata-only, no validation of parameter ranges | ✅ **Action validation** |
| **Gym Env Interface** | `desktop_env/desktop_env.py` — `reset()` → observation dict, `step(action)` → (obs, reward, done, info) | We have no standard observation format or reward signal | ✅ **Observation protocol** |
| **Task Config + Evaluation** | JSON task configs with `instruction`, `config` (setup steps), `evaluator` (metric + getter + expected) | No evaluation/benchmark framework | ⚡ Future (benchmark harness) |
| **Multi-provider VMs** | VMware, Docker, AWS, GCP, Azure, VirtualBox — `create_vm_manager_and_provider()` factory | Windows-only via `pyautogui` + `win32gui` | ⚡ Future (Phase 3C) |
| **pyautogui `<` bug fix** | `_fix_pyautogui_less_than_bug()` — patches the known pyautogui `<` → `>` bug | Not yet handled | ✅ **Quick fix** |
| **Accessibility tree** | `controller.get_accessibility_tree()` via server on VM | We have UIA walker but no standard tree format | Already covered |
| **Screenshot + a11y observation** | `_get_obs()` returns `{screenshot, accessibility_tree, terminal, instruction}` | No standard observation format | ✅ **Observation protocol** |
| **Action history tracking** | `self.action_history: List[Dict]` — every step appended | Our action memory is different (target identities) | ⚡ Could layer |

### Adoptable: Action Parameter Validation

OSWorld defines strict parameter schemas per action:

```python
{
    "action_type": "CLICK",
    "parameters": {
        "button": {"type": str, "range": ["left", "right", "middle"], "optional": True},
        "x": {"type": float, "range": [0, X_MAX], "optional": True},
        "num_clicks": {"type": int, "range": [1, 2, 3], "optional": True},
    }
}
```

We should add `ActionValidator` that checks parameter ranges before dispatch. This prevents out-of-bounds clicks, invalid key names, etc.

### Adoptable: Observation Protocol

```python
@dataclass
class DesktopObservation:
    screenshot: bytes | None
    accessibility_tree: dict | None
    active_window: str
    instruction: str
    step_count: int
```

Standardizing this enables benchmark compatibility and future Gym wrapper.

---

## 2. UI-TARS Desktop — End-to-End Multimodal Agent

**Repo:** `UI-TARS-desktop-main` (~50k lines TypeScript)
**What it is:** ByteDance's multimodal desktop agent with browser, filesystem, and search. Built on Tarko framework with MCP (Model Context Protocol) integration.

### Key Patterns

| Pattern | Where | Our Gap | Adopt? |
|---------|-------|---------|--------|
| **Environment abstraction** | `AgentTARSBaseEnvironment` → Local vs AIO sandbox | No env abstraction (hardcoded Windows) | ✅ **Environment interface** |
| **Hook lifecycle** | `onBeforeToolCall`, `onAfterToolCall`, `onEachAgentLoopStart`, `onBeforeLoopTermination`, `onDispose` | We have `global_hooks` but no per-tool hooks | ⚡ Enhancement |
| **Multi-agent orchestration** | GUI Agent + Code Agent + MCP Agent + Omni Agent (all under `omni-tars/`) | Our `HostAgent` is simpler | ⚡ Future |
| **Operator pattern** | `operator-nutjs` (desktop), `operator-browser` (web), `operator-adb` (mobile), `operator-aio` (sandbox) | Single Windows adapter | ✅ **Operator interface** |
| **Resource cleanup** | `resource-cleaner.ts` — tracks and cleans browser contexts, temp files | No resource cleanup lifecycle | ✅ **Resource tracker** |
| **Tool registration** | `environment.initialize((tool) => this.registerTool(tool))` — environment provides tools | Tools come from `ToolRegistry` | Different approach, no change needed |
| **Config validation** | `validateBrowserControlMode()` — checks model compatibility with control modes | No config validation | ✅ Minor |

### Adoptable: Environment Interface

UI-TARS separates the agent logic from the execution environment:

```typescript
abstract class AgentTARSBaseEnvironment {
    abstract initialize(toolRegistrar, eventStream): Promise<void>;
    abstract onBeforeToolCall(id, toolCall, args): Promise<any>;
    abstract onAfterToolCall(id, toolCall, result): Promise<any>;
    abstract onEachAgentLoopStart(sessionId): Promise<void>;
    abstract onDispose(): Promise<void>;
    abstract getMCPServerRegistry(): MCPServerConfig[];
}
```

We should add `Environment` protocol to `agent_core/adapters/` so Windows, macOS, Linux, Browser, and Docker environments can be swapped. Our existing `SurfaceAdapter` protocol is close but doesn't cover the full lifecycle.

### Adoptable: Resource Tracker

```python
@dataclass
class TrackedResource:
    resource_type: str  # "browser_context", "temp_file", "screenshot"
    resource_id: str
    created_at: float
    cleanup_fn: Callable

class ResourceTracker:
    def track(self, resource: TrackedResource) -> None: ...
    def cleanup_all(self) -> None: ...
    def cleanup_older_than(self, seconds: float) -> int: ...
```

This prevents resource leaks in long-running sessions.

---

## 3. Skyvern — Browser Workflow Automation

**Repo:** `skyvern-main` (~80k lines Python)
**What it is:** Production browser automation platform with workflow blocks, scheduling, credential management, and failure classification.

### Key Patterns

| Pattern | Where | Our Gap | Adopt? |
|---------|-------|---------|--------|
| **Workflow Blocks** | `workflow/models/block.py` — 20+ block types (TaskBlock, ForLoopBlock, CodeBlock, SendEmailBlock, DownloadFileBlock, ValidationBlock, etc.) | Our `DAGExecutor` is generic; no typed block library | ✅ **Typed blocks** |
| **Failure Classifier** | `forge/failure_classifier.py` — 16 categories (ANTI_BOT, PROXY_ERROR, BROWSER_ERROR, NAVIGATION_FAILURE, AUTH_FAILURE, etc.) | No structured failure classification | ✅ **Failure taxonomy** |
| **Scheduled Workflows** | `workflow/schedules.py` — croniter-based, timezone-aware, minimum interval validation | Our `RoutineScheduler` is simpler (no timezone, no min interval) | ✅ **Enhance routines** |
| **Speculative Planning** | `agent.py` `SpeculativePlan` — pre-compute actions from cached scrape before LLM call | No speculative execution | ⚡ Future |
| **Prompt Ceiling** | `PROMPT_HARD_CEILING_TOKENS` — enforced via `enforce_prompt_ceiling_tracked()` | No token budget on prompts | ✅ **Token budget** |
| **Action Confidence** | DB column `actions.confidence_float` — per-action confidence tracking | We track `ActionResult.data["confidence"]` informally | Already covered |
| **Validation Blocks** | `ValidationBlock` — post-task verification (check download exists, verify text, confirm URL) | No post-action validation hooks | ✅ **Validation layer** |
| **Self-heal with retry** | Max retries per step, max steps per task — configurable per org | We have retry but no per-step budget | ✅ **Step budget** |

### Adoptable: Failure Classifier

Skyvern classifies every failure into 16 categories with confidence scores:

```python
class FailureCategory(Enum):
    ANTI_BOT_DETECTION = "anti_bot"
    PROXY_ERROR = "proxy_error"
    BROWSER_ERROR = "browser_error"
    NAVIGATION_FAILURE = "nav_failure"
    PAGE_LOAD_TIMEOUT = "page_timeout"
    AUTH_FAILURE = "auth_failure"
    LLM_ERROR = "llm_error"
    CREDENTIAL_ERROR = "credential_error"
    DATA_EXTRACTION_FAILURE = "extraction_failure"
    ELEMENT_NOT_FOUND = "element_not_found"
    WRONG_PAGE_STATE = "wrong_state"
    MAX_STEPS_EXCEEDED = "max_steps"
    LLM_REASONING_ERROR = "llm_reasoning"
    INFRASTRUCTURE_ERROR = "infra_error"
    PARAMETER_BINDING_ERROR = "param_error"
    UNKNOWN = "unknown"

def classify_failure(reason: str, exception: Exception | None = None) -> list[FailureClassification]:
    """Returns sorted list of (category, confidence, reasoning)."""
```

This plugs into our `RecoveryBridge` for structured error handling and retry decisions.

### Adoptable: Typed Workflow Blocks

Skyvern's block types are way more granular than our DAG nodes:

| Block Type | What | Our Equivalent |
|-----------|------|---------------|
| TaskBlock | Run a browser task | `_execute_single_action` |
| ForLoopBlock | Loop over list | Not implemented |
| CodeBlock | Run Python/JS | Not implemented |
| DownloadFileBlock | Download + verify | Not implemented |
| SendEmailBlock | Email via SMTP | Not implemented |
| ValidationBlock | Post-task check | Not implemented |
| FileParseBlock | Parse PDF/CSV/etc | Not implemented |
| ExeBlock | Run shell command | Not implemented |
| FileTypeBlock | Classify file type | Not implemented |
| WaitBlock | Sleep | Not implemented |

Our `DAGNode` is generic (just `callable`). We should add typed block definitions that provide parameter validation, error classification, and retry semantics per type.

### Adoptable: Schedule Enhancements

Our `RoutineScheduler` should adopt Skyvern's patterns:
- **Timezone-aware cron** — use `zoneinfo` instead of naive `time.time()`
- **Minimum interval validation** — prevent `* * * * *` (every minute) abuse
- **`compute_previous_fire_time()`** — useful for catch-up logic
- **`calculate_next_runs(cron, tz, count)`** — batch preview of upcoming runs

---

## 4. Stagehand — Browser AI with Self-Healing Actions

**Repo:** `stagehand-main` (~30k lines TypeScript)
**What it is:** Browser automation SDK with three core operations: `act()`, `extract()`, `observe()`. Self-healing DOM selectors. Multi-model support.

### Key Patterns

| Pattern | Where | Our Gap | Adopt? |
|---------|-------|---------|--------|
| **Two-step action** | `actHandler.ts` — LLM proposes action, executes, takes new snapshot, LLM proposes follow-up (if `twoStep === true`) | Single-step dispatch only | ✅ **Two-step actions** |
| **Self-healing selectors** | `actHandler.ts` `takeDeterministicAction()` — on error, re-snapshots page, re-queries LLM for new selector, retries | Our `SelfHealer` works on target IDs, not selectors | ✅ **Selector healing** |
| **Timeout guard** | `createTimeoutGuard()` — wraps every step with remaining-time check | We have `asyncio.wait_for` but no guard pattern | ✅ **Timeout guard** |
| **DOM diff** | `diffCombinedTrees()` — captures tree before/after, sends only diff to LLM | No DOM diffing | ✅ **Snapshot diff** |
| **Hybrid snapshot** | `captureHybridSnapshot()` — combines accessibility tree + DOM | Our cascade already does multi-tier | Already covered |
| **Agent tools** | `createAgentTools()` — wraps act/extract/observe as AI SDK tools | We have `ToolRegistry` | Different approach |
| **CUA integration** | Multiple CUA clients (OpenAI, Anthropic, Google, Microsoft) | No CUA (Computer Use Agent) support | ⚡ Future |
| **Metrics callback** | `onMetrics(functionName, promptTokens, completionTokens, reasoningTokens, cachedInputTokens, inferenceTimeMs)` | Our `CostTracker` tracks cost only, not per-call metrics | ✅ **Per-call metrics** |
| **Variable substitution** | `resolveVariableValue()` — `{{variable}}` substitution in actions | No variable templating | ✅ **Variable templates** |

### Adoptable: Two-Step Action Pattern

Stagehand's most interesting pattern: the LLM can request a two-step action:

1. **Step 1:** LLM proposes primary action (e.g., "click dropdown")
2. **Execute** the primary action
3. **Step 2:** Take new snapshot, send diff to LLM, LLM proposes follow-up (e.g., "select option")
4. **Execute** the follow-up
5. Return combined result

This is useful for multi-step UI interactions (dropdown → select, hover → click submenu). We should add this to our agent loop as an option.

### Adoptable: Self-Healing Selector Pattern

```typescript
// On action error:
if (this.selfHeal) {
    // 1. Re-snapshot the page
    const { combinedTree, combinedXpathMap } = await captureHybridSnapshot(page);
    // 2. Ask LLM for a new selector
    const { action: fallbackAction } = await this.getActionFromLLM({
        instruction: actCommand,
        domElements: combinedTree,
        xpathMap: combinedXpathMap,
    });
    // 3. Retry with new selector
    await performUnderstudyMethod(page, method, fallbackAction.selector, args);
}
```

Our `SelfHealer` already does anchor recovery but doesn't re-query the LLM. Adding LLM-in-the-loop healing would improve recovery rates for complex UI changes.

### Adoptable: Timeout Guard Pattern

```python
class TimeoutGuard:
    """Creates checkpointed timeout guards that track remaining time."""
    def __init__(self, total_timeout_ms: float): ...
    def check(self) -> None:
        """Raise TimeoutError if time exceeded."""
    @property
    def remaining_ms(self) -> float: ...
```

Better than raw `asyncio.wait_for` because it:
- Shares a single deadline across multiple steps
- Reports remaining time for adaptive behavior
- Can be passed to sub-operations

---

## Summary: Patterns to Adopt (Priority Order)

| # | Pattern | Source | Effort | Impact |
|---|---------|--------|--------|--------|
| **1** | **Failure Classifier** | Skyvern | ~2h | Structured error handling → better retry/recovery decisions |
| **2** | **Schedule Enhancements** | Skyvern | ~1h | Timezone-aware cron, min interval, previous fire time |
| **3** | **Action Parameter Validation** | OSWorld | ~1.5h | Prevent out-of-bounds clicks, invalid keys, bad params |
| **4** | **Timeout Guard** | Stagehand | ~1h | Shared deadline across steps, remaining-time reporting |
| **5** | **Self-Healing Selectors** | Stagehand | ~2h | LLM-in-the-loop selector recovery on action failure |
| **6** | **Resource Tracker** | UI-TARS | ~1h | Prevent resource leaks in long-running sessions |
| **7** | **Observation Protocol** | OSWorld | ~1h | Standardized observation format for benchmark compat |
| **8** | **Two-Step Actions** | Stagehand | ~3h | Multi-step UI interactions (dropdown → select) |
| **9** | **Environment Interface** | UI-TARS | ~2h | Swap between Windows/macOS/Linux/Browser environments |
| **10** | **Typed Workflow Blocks** | Skyvern | ~4h | ForLoop, Code, Download, Validation blocks |
| **11** | **Snapshot Diffing** | Stagehand | ~1.5h | Send only DOM changes to LLM (token savings) |
| **12** | **pyautogui `<` Bug Fix** | OSWorld | ~15m | Known pyautogui bug workaround |

### Total: ~20h of adoptable patterns
### Quick wins (#1–4 + #6 + #12): ~7h for highest ROI
