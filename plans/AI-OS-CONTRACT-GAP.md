# Gap Analysis: agent_core vs. AI-OS Platform Contract

> What we must change to make the desktop agent a proper AI-OS citizen.

## The Contract

```
AI-OS gives:  INTENT + CONTEXT + PARAMETERS
We give back: RESULT + UNDO_DATA + CONFIDENCE
```

Our desktop agent is an **Agent** citizen (owns the "desktop_automation" domain).

---

## What Matches (keep)

| What We Have | AI-OS Equivalent | Status |
|-------------|-----------------|--------|
| `ActionResult.ok` | `ToolResult.success` | ✅ Same concept |
| `ActionResult.data` | `ToolResult.data` | ✅ Same |
| `ActionResult.error` | `ToolResult.errors` | ✅ Close |
| `ToolRegistry` | Tool discovery | ✅ Maps to capabilities |
| `@agent_action` | Capability declaration | ✅ Same pattern |
| `RecoveryCoordinator` | Undo/recovery | ✅ Maps to before_state/after_state |
| `CheckpointManager` | Snapshots for undo | ✅ Maps to Snapshot |
| `BudgetGovernor` | Cost tracking | ✅ Maps to cost_estimate |
| `FlowLogger` | Structured logging | ✅ Maps to metadata |
| `SurfaceAdapter` | Platform abstraction | ✅ Keep — internal detail |

## What Doesn't Match (must change)

| What AI-OS Requires | What We Have | Gap |
|---------------------|-------------|-----|
| `Agent.execute(goal, context) → AgentResult` | `AgentLoop.run(instruction) → LoopResult` | **Must wrap** |
| `AgentGoal` with capability + params | Plain string instruction | **Must parse** |
| `AgentContext` with user_memory, autonomy_mode, max_cost | Nothing | **Must add** |
| `AgentResult` with summary, confidence, needs_review, learnings, suggested_followups | `LoopResult` with steps, plan, completion_reason | **Must enrich** |
| `Agent.estimate(goal, context) → AgentEstimate` | Nothing | **Must build** |
| `dry_run` support on every action | Nothing | **Must add** |
| `before_state` / `after_state` on mutations | Nothing | **Must capture** |
| `action_class` classification per capability | Nothing | **Must declare** |
| `impact_level` per capability | Nothing | **Must declare** |
| `cost_estimate` per capability | Budget governor (internal) | **Must expose** |
| `Agent.domains` | Nothing | **Must declare** |
| `Agent.capabilities` + descriptions | ToolRegistry tools | **Must map** |
| `Agent.required_tools` / `required_integrations` | Nothing | **Must declare** |
| `Snapshot` for undo | CheckpointManager | **Must bridge** |

## What's New (must build)

1. **AI-OS types** — `AgentGoal`, `AgentContext`, `AgentResult`, `AgentEstimate`, `ToolContext`, `ToolResult`, `Snapshot`
2. **DesktopAgent class** — implements the Agent protocol, wraps AgentLoop
3. **Capability map** — each `@agent_action` gets `action_class`, `impact_level`, `cost_estimate`
4. **Dry-run mode** — every SurfaceAdapter method supports simulation
5. **State capture** — before/after snapshots for undo on mutations
6. **Confidence scoring** — verification pipeline feeds confidence into results

## Architecture After

```
AI-OS Orchestrator
    │
    │  AgentGoal + AgentContext
    ▼
DesktopAgent (Agent Protocol)
    │
    ├── estimate() → cost, latency, confidence
    │
    ├── execute(goal, context) → AgentResult
    │     │
    │     ├── Parse goal.capability → action name
    │     ├── Parse goal.params → action parameters
    │     ├── Check context.autonomy_mode → copilot/autopilot/executive
    │     ├── Check context.max_cost → budget gate
    │     ├── If dry_run → simulate, return preview
    │     │
    │     └── AgentLoop.run()
    │           ├── SurfaceAdapter (browser/desktop)
    │           ├── Cascade engine
    │           ├── Recovery pipeline
    │           └── Verification → confidence score
    │
    └── execute_streaming() → AsyncIterator[AgentProgress]
```

## File Changes Required

```
NEW FILES:
  src/agent_core/os_types.py          — AgentGoal, AgentContext, AgentResult, etc.
  src/agent_core/desktop_agent.py     — DesktopAgent (Agent Protocol implementation)
  tests/test_agent_core/test_os_contract.py — Contract test suite from §7

MODIFIED FILES:
  src/agent_core/cascade/protocol.py  — Add dry_run support to SurfaceAdapter
  src/agent_core/results/types.py     — Add before_state/after_state to ActionResult
  src/agent_core/agent/registry.py    — Add action_class, impact_level, cost_estimate
  src/agent_core/agent/loop.py        — Accept AgentGoal instead of raw string
```
