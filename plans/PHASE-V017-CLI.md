# v0.17: CLI Entry Point + REPL

> **v0.16.0 → v0.17.0** | ~3h | 3 workstreams
> Makes the agent a **runnable tool**, not just a library.

---

## Problem

Right now `desktop-agent` is a library. There's no `desktop-agent` command.
The only way to use it is via `scripts/demo_desktop_agent.py` or by importing
Python modules directly. A CLI gives it a front door.

---

## Design Principles

1. **argparse only** — zero new dependencies (no click/typer)
2. **Async-safe** — all execution is async; CLI wraps with `asyncio.run()`
3. **Structured output** — JSON for scripts, pretty-printed for humans
4. **Session lifecycle** — `configure_session` / `terminate_session` per invocation

---

## Workstream A: Core CLI + Entry Point (~1.5h)

### New file: `src/agent_core/cli/__init__.py`

Empty package init.

### New file: `src/agent_core/cli/main.py`

```python
"""desktop-agent CLI — command-line interface for the Desktop Agent."""

Usage:
    desktop-agent execute "Open Notepad and type Hello"
    desktop-agent execute --capability click --params '{"target": "OK button"}'
    desktop-agent estimate "Open Notepad and type Hello"
    desktop-agent schedule add --name "morning" --cron "0 8 * * *" --prompt "Check calendar"
    desktop-agent schedule list
    desktop-agent schedule remove --name "morning"
    desktop-agent schedule due
    desktop-agent skills list
    desktop-agent skills match "type text in notepad"
    desktop-agent facts list
    desktop-agent facts search "email"
    desktop-agent health
    desktop-agent schema
    desktop-agent version
    desktop-agent repl
```

### Subcommands

| Subcommand | What | Maps to |
|-----------|------|---------|
| `execute` | Execute a single goal | `DesktopAgent.execute(goal, ctx)` |
| `estimate` | Preview cost/confidence | `DesktopAgent.estimate(goal, ctx)` |
| `schedule add` | Add a routine | `RoutineScheduler.add()` |
| `schedule list` | List routines | `RoutineScheduler.list()` |
| `schedule remove` | Remove a routine | `RoutineScheduler.remove()` |
| `schedule due` | Show due routines | `RoutineScheduler.get_due()` |
| `skills list` | List loaded skills | `SkillLoader.discover()` |
| `skills match` | Match instruction to skill | `SkillLoader.match()` |
| `facts list` | List stored facts | `FactStore.get_facts()` |
| `facts search` | Search facts by keyword | `FactStore.search_facts()` |
| `health` | Run health checks | `DesktopAgent.health()` |
| `schema` | Print capability schema | `DesktopAgent.schema()` |
| `version` | Print version | `DesktopAgent.version` |
| `repl` | Interactive REPL | Custom loop |

### `execute` flags

```
desktop-agent execute "Open Notepad and type Hello"
  --capability automate       # default when instruction provided
  --dry-run                   # preview without executing
  --timeout 30                # seconds
  --json                      # raw JSON output
  --session ID                # reuse session
  --storage-dir PATH          # ledger/persistence directory
```

### `repl` flags

```
desktop-agent repl
  --provider openai           # LLM provider
  --model gpt-4o-mini         # model name
  --storage-dir PATH          # session persistence
```

### Entry point in pyproject.toml

```toml
[project.scripts]
desktop-agent = "agent_core.cli.main:main"
```

### Tests (~15)

- `test_cli/test_main.py` — CLI parsing tests
  - `execute` parses instruction
  - `execute --dry-run` sets context
  - `execute --capability click --params` parses JSON params
  - `estimate` parses instruction
  - `schedule add` parses name + cron + prompt
  - `schedule list` runs
  - `schedule remove` parses name
  - `skills list` runs
  - `skills match` parses instruction
  - `facts list` runs
  - `facts search` parses query
  - `health` runs
  - `schema` runs
  - `version` prints version
  - unknown subcommand exits with error

---

## Workstream B: Interactive REPL (~1h)

### New file: `src/agent_core/cli/repl.py`

REPL loop that:

1. Initializes `DesktopAgent` with `WindowsAdapter` (or passed surface)
2. Calls `configure_session(session_id)`
3. Loops:
   - Reads instruction from stdin (`> `)
   - Dispatches to `agent.execute(goal, ctx)`
   - Prints result (summary + confidence + duration)
   - Extracts facts automatically
4. On `exit` / Ctrl+C: calls `terminate_session()`

Special commands:
- `.health` — run health check
- `.facts` — show extracted facts
- `.soul` — show soul aspects
- `.skills` — list loaded skills
- `.undo ID` — undo a previous execution
- `.estimate INST` — preview without executing
- `.schema` — show capability schema
- `.help` — show commands

### Tests (~8)

- `test_cli/test_repl.py`
  - REPL creation with mock surface
  - `.help` prints commands
  - `.health` runs health check
  - `.facts` shows facts
  - `.soul` shows soul
  - `.schema` prints schema
  - `exit` terminates session
  - normal instruction dispatches to execute

---

## Workstream C: Output Formatting + Integration (~30min)

### New file: `src/agent_core/cli/formatters.py`

```python
def format_result(result: AgentResult, *, json_mode: bool = False) -> str:
    """Format an AgentResult for terminal output."""

def format_estimate(estimate: AgentEstimate) -> str:
    """Format estimate for terminal output."""

def format_health(status: HealthStatus) -> str:
    """Format health check result."""

def format_routine(routine: Routine) -> str:
    """Format a routine for listing."""

def format_skill(skill: SkillDefinition) -> str:
    """Format a skill for listing."""

def format_fact(fact: Fact) -> str:
    """Format a fact for listing."""

def format_schema(schema: dict) -> str:
    """Format capability schema as a table."""
```

### Tests (~7)

- `test_cli/test_formatters.py`
  - format_result success
  - format_result failure
  - format_estimate
  - format_health
  - format_routine
  - format_skill
  - format_schema

---

## Execution Order

```
Step 1: C — formatters.py + tests         (~30m)    No deps, standalone
Step 2: A — CLI main + entry point + tests (~1.5h)   Uses formatters
Step 3: B — REPL + tests                   (~1h)     Uses CLI
Step 4: pyproject.toml entry point + version bump
Step 5: Full test suite
```

---

## Files Changed

| # | File | Action | Δ Lines |
|---|------|--------|---------|
| 1 | `src/agent_core/cli/__init__.py` | Create | ~5 |
| 2 | `src/agent_core/cli/main.py` | Create | ~350 |
| 3 | `src/agent_core/cli/repl.py` | Create | ~180 |
| 4 | `src/agent_core/cli/formatters.py` | Create | ~120 |
| 5 | `pyproject.toml` | Edit: entry point + version | +3 |
| 6 | `tests/test_cli/__init__.py` | Create | ~0 |
| 7 | `tests/test_cli/test_main.py` | Create | ~200 |
| 8 | `tests/test_cli/test_repl.py` | Create | ~120 |
| 9 | `tests/test_cli/test_formatters.py` | Create | ~100 |

---

## Expected Outcome

| Metric | Before (v0.16.0) | After (v0.17.0) |
|--------|-------------------|------------------|
| Tests | 2,455 | ~2,485 |
| Entry point | None | `desktop-agent` CLI command |
| REPL | None | Interactive `desktop-agent repl` |
| Subcommands | None | 14 subcommands |
| Output format | None | Pretty-print + JSON mode |
| Session lifecycle | Manual code | Automatic per-invocation |
