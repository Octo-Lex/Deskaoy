# Deskaoy

> **Deskaoy** — the one from the desk. An AI desktop agent that perceives any screen, acts on any element, and recovers from failures autonomously.

*The name blends English "Desk" with the Arabic demonym suffix "-awi" (ـاوِي) — the one native to, the one belonging to the desk.*

## Quick Start

```bash
pip install deskaoy
```

The fastest way to try it is the CLI:

```bash
deskaoy execute --dry-run "Open Notepad and type Hello World"
```

Or programmatically — `execute()` takes an `AgentGoal` and an `AgentContext`. This snippet runs as a **dry-run smoke test** (no real desktop action) so it works without an LLM or surface configured:

```python
import asyncio
from uuid import uuid4

from deskaoy import DesktopAgent
from deskaoy.os_types import AgentGoal, AgentContext

async def main():
    agent = DesktopAgent()
    goal = AgentGoal(
        capability="automate",
        params={"instruction": "Open Notepad and type Hello World"},
    )
    ctx = AgentContext(
        execution_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        task_id=str(uuid4()),
        user_id="demo-user",
        session_id=str(uuid4()),
        dry_run=True,  # smoke test — no real desktop action
        timeout_seconds=60,
    )
    result = await agent.execute(goal, ctx)
    print(result.status, result.summary)

asyncio.run(main())
```

## Features

| Capability | Status |
|:-----------|:-------|
| Windows UI Automation | ✅ UIA + comtypes + pyautogui |
| Linux AT-SPI2 | ✅ Ubuntu 24.04+ via pyatspi |
| macOS Accessibility | 🔲 Planned (needs hardware) |
| CLI | ✅ 15 subcommands + REPL |
| CUA Loop | ✅ OpenAI + Anthropic |
| OpenTelemetry | ✅ Tracing + Metrics via OTLP |
| Health & Diagnostics | ✅ 8-point subsystem health |
| Routine Scheduling | ✅ Cron-based automation |
| Crash Recovery | ✅ Checkpoints + retry |
| Script Runner | ✅ `.deskaoy.json` declarative scripts |

## Installation

```bash
# Core (desktop automation)
pip install deskaoy

# With LLM support
pip install deskaoy[llm]

# With OpenTelemetry tracing
pip install deskaoy[tracing]

# With OTLP exporter
pip install deskaoy[tracing-otlp]

# Everything
pip install deskaoy[all]
```

## CLI

```bash
deskaoy execute "Open Notepad and type Hello"
deskaoy execute --dry-run --json "Open Calculator"
deskaoy estimate "Send an email"
deskaoy schedule add --name morning --cron "0 8 * * *" --prompt "Check calendar"
deskaoy health
deskaoy doctor
deskaoy completions bash
```

## Architecture

```
deskaoy/
├── adapters/          # Platform adapters (Windows, Linux)
├── agent/             # Agent loop, config, script runner
├── budget/            # Token budgets and cost tracking
├── cascade/           # UI element resolution and snapshots
├── cli/               # Command-line interface
├── daemon/            # Background daemon mode
├── grounding/         # Object detection and OCR
├── interaction/       # Action execution and decorators
├── memory/            # Action memory and fingerprints
├── recovery/          # Crash recovery and checkpoints
├── results/           # Result types and output formatting
├── security/          # Approval gates and redaction
├── skills/            # Plugin system
├── tracing/           # OpenTelemetry-native observability
├── verification/      # Screenshot diff verification
└── vision/            # Screen capture and OCR
```

## Observability

Deskaoy uses OpenTelemetry for tracing and metrics:

```python
from deskaoy.tracing.runtime import configure_telemetry, TelemetryConfig

# Enable with OTLP export
configure_telemetry(TelemetryConfig(otlp_endpoint="http://localhost:4317"))

# Or in-process only
configure_telemetry(TelemetryConfig())
```

LLM calls are automatically instrumented with `gen_ai.*` and `deskaoy.*` attributes.

## Development

```bash
git clone <repo-url>
cd deskaoy

pip install -e ".[dev]"

# Run tests
pytest

# With coverage
pytest --cov=deskaoy

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## Per-App Guides

Built-in guides for common applications:

| App | Launch | Selectors | Actions |
|:----|:-------|:----------|:--------|
| Notepad | ✓ | ✓ | ✓ |
| Calculator | ✓ | ✓ | ✓ |
| File Explorer | ✓ | ✓ | ✓ |
| Chrome | ✓ | ✓ | ✓ |
| VS Code | ✓ | ✓ | ✓ |

## License

[MIT](LICENSE) © 2025-2026 Deskaoy Contributors
