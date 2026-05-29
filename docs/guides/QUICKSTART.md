# Quick-Start Guide — desktop-agent

Get started with desktop-agent in 5 minutes.

---

## 1. Install

```bash
pip install desktop-agent
```

For specific features:

```bash
pip install desktop-agent[mcp]     # MCP transport
pip install desktop-agent[rest]    # REST HTTP transport
pip install desktop-agent[browser] # Browser automation
pip install desktop-agent[llm]     # LLM integration
pip install desktop-agent[dev]     # Development tools
```

## 2. Verify Installation

```bash
desktop-agent doctor
```

This checks all 8 subsystems:
- Surface adapter availability
- LLM client configuration
- Policy bridge status
- Storage resolver
- Circuit breaker
- Cost budget
- Key blocklist (14 dangerous combos blocked)
- Sensitive apps (14 categories monitored)

## 3. First Action (Python API)

```python
import asyncio
from agent_core import DesktopAgent
from agent_core.adapters.windows import WindowsAdapter

async def main():
    # Create adapter for a specific window
    adapter = WindowsAdapter(window_title="Notepad")
    agent = DesktopAgent(surface=adapter)

    # Check health
    health = await agent.health()
    print(f"Healthy: {health.healthy}")

    # Execute a goal
    receipt = await agent.execute("Type Hello World in Notepad")
    print(f"Status: {receipt.status}")
    print(f"Duration: {receipt.duration_ms:.0f}ms")

asyncio.run(main())
```

## 4. Agent Loop (LLM-Powered)

```python
from agent_core.agent.loop import AgentLoop

# Requires LLM client configured
loop = AgentLoop(agent, max_iterations=10)
receipt = await loop.run("Open Calculator and compute 2+2")
```

With two-step verification:

```python
loop = AgentLoop(agent, two_step=True)
# Captures before/after snapshots, verifies changes
```

## 5. CLI Usage

```bash
# Show version
desktop-agent --version

# Execute a goal
desktop-agent execute "Open Notepad"

# Interactive REPL
desktop-agent repl

# List tools
desktop-agent tools list

# Run benchmarks
desktop-agent benchmark

# Show per-app guide
desktop-agent guides show notepad
```

## 6. MCP Transport (for AI tools)

```bash
desktop-agent mcp
```

Outputs JSON-RPC over stdio, compatible with Model Context Protocol clients.

## 7. REST API

```bash
desktop-agent serve --port 3847
```

Then:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:3847/health
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
     -d '{"goal": "Open Notepad"}' \
     http://localhost:3847/execute
```

## 8. Evaluation Framework

```python
from agent_core.evaluation import BenchmarkRunner

runner = BenchmarkRunner(tasks_dir="tasks/")
results = await runner.run_all()
print(runner.format_results(results))
```

## 9. Performance Monitoring

```python
from agent_core.performance import LatencyProfiler

profiler = LatencyProfiler()
with profiler.measure("click_dispatch"):
    await adapter.click("button")
print(profiler.summary())
```

## Next Steps

- [API Reference](api/REFERENCE.md) — Complete API docs
- [Architecture Guide](guides/ARCHITECTURE.md) — How it works
- [Adapter Development](guides/ADAPTER_DEV.md) — Build your own adapter
- [CONTRIBUTING.md](../CONTRIBUTING.md) — How to contribute

---

*Quick-Start Guide v0.24.0 — Generated 2026-05-03*
