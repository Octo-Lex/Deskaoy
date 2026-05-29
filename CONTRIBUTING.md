# Contributing to Desktop-Agent

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.11+
- pip or uv

### Install

```bash
# Clone the repository
git clone <repo-url>
cd Desktop-Agent

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify installation
desktop-agent doctor
```

### Run Tests

```bash
# Full test suite
pytest

# Specific modules
pytest tests/test_runtime/
pytest tests/test_agent_core/
pytest tests/test_safety/

# With coverage
pytest --cov=agent_core --cov-report=term-missing

# Skip integration tests (require real browser)
pytest -m "not integration"

# Skip grounding tests (require ML weights)
pytest -m "not grounding"
```

## Project Structure

```
src/
├── agent_core/           # Surface-agnostic agent engine
│   ├── adapters/         # Surface adapters (Windows, Browser, etc.)
│   ├── agent/            # Agent loop, delegation, loop detection
│   ├── cascade/          # Multi-tier element resolution
│   ├── cli/              # Command-line interface
│   ├── recovery/         # Recovery system (checkpoint, strategies)
│   ├── runtime/          # Runtime execution (preflight, receipts)
│   ├── safety/           # Safety subsystem (validation, compensation)
│   └── ...
└── super_browser/        # Browser automation layer

tests/                    # Test suite (3,471+ tests)
plans/                    # Planning documents
docs/                     # Documentation
```

## Optional Dependency Groups

The package uses optional dependency groups in `pyproject.toml`:

| Group | Description |
|-------|-------------|
| `[browser]` | Browser automation via Patchright |
| `[llm]` | LLM clients (OpenAI, Anthropic) |
| `[mcp]` | MCP stdio transport |
| `[rest]` | REST HTTP server |
| `[windows]` | Windows desktop automation |
| `[dev]` | Development tools (pytest, ruff, mypy) |
| `[grounding]` | Visual grounding (YOLO, OCR) |
| `[all]` | Everything except grounding |

## Code Style

- **Type hints** on all public functions and methods
- **Docstrings** on all public APIs (Google style)
- **Dataclasses** for structured data (not raw dicts)
- **StrEnum** for enumeration types
- **Async/await** for all I/O operations
- **No new hard dependencies** without discussion

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/my-feature
```

### 2. Write Code

Follow the existing patterns:
- New capabilities go in `desktop_agent.py` with a `CAPABILITIES` entry
- New adapters implement `SurfaceAdapter` from `cascade/protocol.py`
- New safety checks go in `safety/`
- New types go in the appropriate `types.py`

### 3. Write Tests

Every new feature needs tests:
- Mirror the source structure: `src/agent_core/foo.py` → `tests/test_foo/test_foo.py`
- Use `pytest` + `pytest-asyncio`
- Use `AsyncMock` for surface adapters
- Each test file should have 5-15 tests
- Run the full suite before submitting: `pytest`

### 4. Run Quality Checks

```bash
# All tests pass
pytest

# No import errors
python -c "import agent_core; print('OK')"

# Doctor passes
desktop-agent doctor
```

## Key Principles

1. **Safety by default** — Stealth off, policy on, loops detected
2. **Evidence-led** — Every execution produces a receipt + audit trail
3. **Graceful degradation** — Budget exhaustion = partial results, not crashes
4. **AI-OS first** — Production runs within AI-OS platform
5. **Type-driven** — 50+ dataclasses, StrEnums, and protocols
6. **Test everything** — Target 2+ test files per source file

## Reporting Issues

When reporting bugs, please include:

1. Python version (`python --version`)
2. Desktop-Agent version (`desktop-agent version`)
3. Doctor output (`desktop-agent doctor`)
4. Minimal reproduction steps
5. Expected vs. actual behavior

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
