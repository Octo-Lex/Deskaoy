# Architecture Guide — desktop-agent

## Overview

desktop-agent is a **surface-agnostic desktop automation framework** with safety-first design. It provides a unified API for automating desktop applications across operating systems, with built-in LLM integration, self-healing selectors, and multi-layer safety.

```
┌─────────────────────────────────────────────────────┐
│                    CLI / MCP / REST                   │
│                   (Transport Layer)                   │
├─────────────────────────────────────────────────────┤
│                   DesktopAgent                        │
│                (Orchestration Facade)                 │
├──────────┬──────────┬───────────┬────────────────────┤
│ AgentLoop│ CUALoop  │ Workflow  │  Evaluation        │
│ (LLM)    │ (Vision) │ (Blocks)  │  (Benchmarks)      │
├──────────┴──────────┴───────────┴────────────────────┤
│                   Cascade Engine                      │
│          (Tiered Element Resolution)                  │
│   Tier 1: Selector  →  Tier 2: Visual  →  Tier 3    │
├─────────────────────────────────────────────────────┤
│              SurfaceAdapter (Abstract)                │
│         Windows │ macOS (future) │ Linux (future)    │
├─────────────────────────────────────────────────────┤
│                     Safety Layer                      │
│   Key Blocklist │ Sensitive Apps │ Rate Governor     │
│   Cost Tracker  │ Latency Budget │ Session Budget    │
│   Policy Bridge │ Circuit Breaker│ Evidence Ledger   │
└─────────────────────────────────────────────────────┘
```

## Subsystems

### 1. Surface Adapters (`adapters/`)

Platform-specific adapters that implement the `SurfaceAdapter` protocol. Each adapter provides:

- **Element resolution**: Find UI elements by name, automation ID, or coordinates
- **Input injection**: Mouse (click, hover, scroll) and keyboard (type, key press)
- **Window management**: Focus, minimize, maximize, close
- **Accessibility tree**: Snapshot the UI tree for analysis
- **Screenshots**: Visual capture of the target window

Current implementations:
- **WindowsAdapter**: win32gui + pyautogui + UI Automation
- **LocalDesktop / DockerDesktop / RemoteVM**: Environment abstractions (lifecycle hooks)

### 2. Cascade Engine (`cascade/`)

Tiered element resolution with automatic fallback:

1. **Tier 1 — Selector**: Match by CSS-like selector or UIA identifier
2. **Tier 2 — Visual**: YOLO detection + OCR text matching
3. **Tier 3 — LLM Grounding**: Language model identifies the element

Each tier is progressively slower but more flexible. The cascade automatically falls back when lower tiers fail.

### 3. Safety Layer (`safety/`)

Multi-layer safety system:

| Module | Purpose |
|--------|---------|
| `key_blocklist` | Blocks 14 dangerous key combos (Alt+F4, Ctrl+Alt+Del, etc.) |
| `sensitive_apps` | Detects 14 sensitive app categories (email, banking, etc.) |
| `rate_governor` | Prevents action flooding |
| `cost_tracker` | Tracks LLM API costs |
| `latency_budget` | Prevents runaway operations |
| `session_budget` | Limits actions per session |
| `timeout_guard` | Hierarchical deadline enforcement |
| `health` | 8-subsystem health check |

### 4. Agent Loop (`agent/`)

LLM-powered action planning:

- **AgentLoop**: Standard tool-calling loop with LLM
- **CUALoop**: Computer Use Agent — screenshot-based action cycle
- **TwoStepVerifier**: Pre/post action verification with confidence scoring

### 5. Memory (`memory/`)

Persistent action memory with self-healing:

- **Hot cache**: In-memory LRU for fast lookup
- **Warm storage**: Per-domain JSON files
- **Self-healing**: When selectors break, automatically finds alternative anchors
- **Learning evidence**: Tracks which healing strategies work

### 6. Input (`input/`)

Humanized input injection:

- **Bézier curves**: Mouse movements follow curved paths
- **Jitter**: Click positions are randomized
- **Timing**: Inter-key delays vary naturally
- **Burst typing**: Occasionally types fast bursts (like humans)

### 7. Orchestration (`orchestration/`)

Workflow building blocks:

| Block | Purpose |
|-------|---------|
| `ForLoop` | Repeat action N times |
| `Wait` | Wait for N seconds |
| `Download` | Download a file |
| `Validation` | Assert a condition |
| `FormFill` | Fill multiple fields |
| `CodeBlock` | Run sandboxed Python |

### 8. Transport (`transport/`)

Two transport modes for external integration:

- **MCP**: JSON-RPC over stdio (for AI tools like Claude Desktop)
- **REST**: HTTP API with bearer token auth (port 3847)

### 9. Performance (`performance/`)

Profiling and caching infrastructure:

- **LatencyProfiler**: Measure and report hot-path timings
- **LRUCache**: Generic LRU cache for expensive lookups
- **BenchmarkSuite**: Latency regression testing
- **PerformanceMonitor**: Real-time operation tracking

### 10. Evaluation (`evaluation/`)

OSWorld-compatible task framework:

- JSON task definitions with evaluator specs
- 7 built-in evaluator types
- BenchmarkRunner for batch evaluation
- 10 sample Windows desktop tasks

## Data Flow

```
User Goal → AgentLoop → LLM → Tool Call → Safety Gate → Cascade → Adapter → Desktop
                ↑                                              ↓
                └───── Observation ← Snapshot ← Screenshot ───┘
```

1. User provides a goal (text string)
2. AgentLoop sends to LLM with context
3. LLM returns tool calls (click, type, etc.)
4. Safety gate validates the action
5. Cascade resolves the target element
6. Adapter executes on the desktop
7. Observation captures the result
8. Loop continues until goal achieved or limit reached

## Receipt System

Every execution produces an immutable `RuntimeExecutionReceipt`:

```python
receipt = await agent.execute("Open Notepad")
# receipt.status: SUCCESS / FAILURE / PARTIAL / RATE_LIMITED / TIMED_OUT
# receipt.duration_ms: 342.5
# receipt.actions_count: 3
# receipt.error: None
# receipt.frozen: False
receipt.freeze()  # Make immutable
```

---

*Architecture Guide v0.24.0 — Generated 2026-05-03*
