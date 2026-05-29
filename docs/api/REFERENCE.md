# API Reference — desktop-agent v1.0.0

Complete public API for the desktop-agent framework.

---

## Core

### `DesktopAgent`

The main entry point for the desktop-agent framework.

```python
from agent_core import DesktopAgent

agent = DesktopAgent(surface=windows_adapter)
```

#### Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `surface` | `SurfaceAdapter` | `None` | Platform adapter (Windows, macOS, Linux) |
| `llm` | `LLMClient` | `None` | Language model client |
| `policy_bridge` | `PolicyBridge` | `None` | AI-OS policy connector |
| `storage_resolver` | `StorageResolver` | `None` | File system resolver |
| `recovery_bridge` | `RecoveryBridge` | `None` | Circuit breaker + retry engine |
| `version` | `str` | `"1.0.0"` | Agent version |

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `execute(goal, context)` | `RuntimeExecutionReceipt` | Execute a goal with full safety pipeline |
| `estimate(goal)` | `Estimate` | Estimate cost and risk before execution |
| `undo(goal)` | `ActionResult` | Attempt to undo a previous action |
| `compensate(goal)` | `ActionResult` | Run compensating action for failed undo |
| `health()` | `HealthStatus` | Run all subsystem health checks |
| `shutdown()` | `None` | Graceful shutdown with receipt |

---

## Adapters

### `SurfaceAdapter` (Abstract)

Base class for all platform adapters.

```python
from agent_core.cascade.protocol import SurfaceAdapter
```

#### Abstract Methods (must implement)

| Method | Returns | Description |
|--------|---------|-------------|
| `click(target)` | `ActionResult` | Click on an element |
| `fill(target, value)` | `ActionResult` | Fill a text field |
| `type_text(text)` | `ActionResult` | Type text with humanized timing |
| `key_press(key, modifiers)` | `ActionResult` | Press key with modifiers |
| `scroll(direction, amount)` | `ActionResult` | Scroll in a direction |
| `screenshot()` | `bytes` | Capture screenshot |
| `snapshot()` | `AXSnapshot` | Capture accessibility tree |
| `hover(target)` | `ActionResult` | Hover over an element |
| `wait_for_selector(sel, timeout)` | `ActionResult` | Wait for element to appear |
| `evaluate(expression)` | `Any` | Evaluate expression (optional) |

#### Non-Abstract Methods (inherited)

| Method | Returns | Description |
|--------|---------|-------------|
| `read_clipboard()` | `str` | Read system clipboard |
| `write_clipboard(text)` | `None` | Write to clipboard |
| `open_app(name)` | `dict` | Open or focus an application |
| `invoke_element(ref)` | `ActionResult` | Invoke element by reference |
| `set_window_state(state)` | `ActionResult` | Maximize/minimize/restore/close |
| `get_focused_element()` | `str` | Get currently focused element ref |
| `get_element_state(ref)` | `dict` | Get element properties |
| `current_url()` | `str` | Get current URL/window identifier |
| `current_title()` | `str` | Get current window title |

### `WindowsAdapter`

Windows desktop adapter using win32gui + pyautogui + UI Automation.

```python
from agent_core.adapters.windows import WindowsAdapter

adapter = WindowsAdapter(hwnd=win32gui.FindWindow(None, "Calculator"))
```

#### Windows-specific

| Parameter | Type | Description |
|-----------|------|-------------|
| `hwnd` | `int` | Window handle |
| `window_title` | `str` | Find window by title |
| `humanization` | `HumanizationConfig` | Input humanization settings |

---

## Safety

### Key Blocklist

```python
from agent_core.safety.key_blocklist import is_blocked_key, block_reason

is_blocked_key("Alt+F4")     # True
block_reason("Alt+F4")       # "Closing windows — may lose unsaved work"
```

Order-independent: `is_blocked_key("F4+Alt")` also returns `True`.

Key aliases: `del`↔`delete`, `esc`↔`escape`, `cmd`/`win`↔`meta`, `return`↔`enter`.

### Sensitive App Detection

```python
from agent_core.safety.sensitive_apps import is_sensitive_app, sensitive_app_tier

is_sensitive_app("Outlook")       # True
sensitive_app_tier("Outlook")     # "confirm"
```

14 sensitive categories: email, banking, password managers, messaging, terminal.

### Health Check

```python
from agent_core.safety.health import HealthCheck

checker = HealthCheck(agent)
status = await checker.check()
# status.checks = {"surface": True, "llm": False, ..., "key_blocklist": True}
```

8 subsystem checks: surface, llm, policy, storage, circuit_breaker, cost_budget, key_blocklist, sensitive_apps.

---

## Agent Loop

### `AgentLoop`

Orchestrates LLM-based action planning with tool calling.

```python
from agent_core.agent.loop import AgentLoop

loop = AgentLoop(agent, max_iterations=10, two_step=True)
receipt = await loop.run("Open Notepad and type Hello World")
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent` | `DesktopAgent` | required | The agent instance |
| `max_iterations` | `int` | `10` | Max LLM rounds |
| `two_step` | `bool` | `False` | Enable pre/post snapshot verification |

### `TwoStepVerifier`

Action-specific verification with confidence scores.

```python
from agent_core.agent.two_step import TwoStepVerifier

verifier = TwoStepVerifier()
result = verifier.verify("click", pre_snapshot, post_snapshot, target="btn")
# result.confidence = 0.85
```

### `CUALoop`

Computer Use Agent loop — screenshot-based action cycle.

```python
from agent_core.agent.cua_loop import CUALoop

loop = CUALoop(agent, provider="openai")
receipt = await loop.run("Click the Start button")
```

---

## Cascade Engine

### `SnapshotDiffer`

Deterministic diff between two AX snapshots.

```python
from agent_core.cascade.differ import SnapshotDiffer

diff = SnapshotDiffer.diff(before, after)
# diff.added = [...], diff.removed = [...], diff.changed = [...]
```

### Formatter

4-pass AX snapshot formatter for token-efficient LLM context.

```python
from agent_core.cascade.formatter import format_snapshot

text = format_snapshot(snapshot)
```

---

## Orchestration

### Workflow Blocks

```python
from agent_core.orchestration.blocks import ForLoop, Wait, Download, Validation, FormFill, CodeBlock
from agent_core.orchestration.workflow import WorkflowBuilder

workflow = (
    WorkflowBuilder("My Workflow")
    .add(Validation(check=lambda ctx: True))
    .add(Wait(seconds=2.0))
    .build()
)
```

---

## Transport

### MCP Server

JSON-RPC over stdio, compatible with Model Context Protocol.

```bash
desktop-agent mcp          # Full output
desktop-agent mcp --compact  # Compact output
```

### REST Server

HTTP API with bearer token authentication.

```bash
desktop-agent serve --port 3847
```

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/execute` | POST | Execute a goal |
| `/estimate` | POST | Estimate cost/risk |

---

## Evaluation

### Benchmark Runner

```python
from agent_core.evaluation import BenchmarkRunner, TaskDefinition

runner = BenchmarkRunner(tasks_dir="tasks/")
results = await runner.run_all()
print(runner.format_results(results))
```

### Evaluator Types

| Type | Description |
|------|-------------|
| `exact_match` | Output matches expected exactly |
| `contains` | Output contains expected substring |
| `file_exists` | File at path exists |
| `file_contains` | File at path contains text |
| `process_running` | Process name is running |
| `window_title` | Window title contains text |
| `always_pass` / `always_fail` | Stub evaluators |

---

## Guides

### Per-App Guides

```python
from agent_core.guides import GuideRegistry

registry = GuideRegistry()
guide = registry.find("notepad")
# guide.common_actions = {"type_text": {...}}
```

---

## Performance

### Latency Profiler

```python
from agent_core.performance import LatencyProfiler

profiler = LatencyProfiler()
with profiler.measure("click_dispatch"):
    await adapter.click("btn")
print(profiler.summary())
```

### Benchmark Suite

```python
from agent_core.performance import BenchmarkSuite

suite = BenchmarkSuite()
suite.add("lookup", lambda: cache.get("key"), target_ms=1.0)
results = suite.run()
```

---

## CLI

```bash
desktop-agent --version
desktop-agent --help
desktop-agent status           # Show agent status
desktop-agent doctor           # Run health checks
desktop-agent execute "goal"   # Execute a goal
desktop-agent repl             # Interactive REPL
desktop-agent mcp              # MCP stdio transport
desktop-agent serve            # REST HTTP transport
desktop-agent tools list       # List available tools
desktop-agent tasks list       # List evaluation tasks
desktop-agent benchmark        # Run benchmarks
desktop-agent guides list      # List per-app guides
desktop-agent guides show ID   # Show guide details
```

---

*API Reference v1.0.0 — Generated 2026-05-10*
