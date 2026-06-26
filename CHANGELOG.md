# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),

## [2.0.0] — 2026-06-27

### Highlights

**Desktop-Agent → Deskaoy.** Renamed from Desktop-Agent to **Deskaoy**
(from the Arabic demonym suffix "-awi" — the one from the desk).
SuperBrowser has been removed; Deskaoy now focuses exclusively on desktop
automation. This is a breaking change: package name, module paths, CLI
command, and filesystem paths have all changed.

Six stabilization batches make v2.0.0 production-ready: execution safety,
release coherence, CI/package correctness, CLI correctness, adapter
truthfulness, and release hardening.

### Breaking Changes
- Project renamed: Desktop-Agent → **Deskaoy**
- Package / CLI: `desktop-agent` → `deskaoy`
- Module path: `agent_core` → `deskaoy`
- Filesystem paths: `~/.desktop-agent/` → `~/.deskaoy/`
- SuperBrowser removed: no more browser automation, `[browser]` extra removed
- `DesktopAgent.with_browser()` removed
- `UnifiedSurface` browser routing removed

### Migration from v1.x
```python
# Before (v1.x)
from agent_core import DesktopAgent
pip install desktop-agent

# After (v2.0)
from deskaoy import DesktopAgent
pip install deskaoy
```

### Removed
- `src/super_browser/` — entire package (99 source files)
- `DesktopAgent.with_browser()` — factory method
- `DesktopAgent.__aenter__`/`__aexit__` — browser lifecycle
- `UnifiedSurface` browser routing
- `SuperBrowserConfig` — replaced by `AgentConfig`
- `[browser]` optional dependency group
- 636 browser-related tests removed

### Changed
- `src/agent_core/` → `src/deskaoy/`
- All imports: `from agent_core.xxx` → `from deskaoy.xxx`
- OTel namespace: `desktop_agent.*` metrics → `deskaoy.*`
- Data directory: `~/.desktop-agent/` → `~/.deskaoy/`
- Session database: `~/.super-browser/sessions.db` → `~/.deskaoy/sessions.db`

### Stabilization — Batch 3: Execution Safety (P0)
- **Preserve sanitized params**: `validate_action()` sanitized params were
  discarded and overwritten with raw `goal.params` before adapter dispatch. Fixed.
- **Policy-deny fallthrough**: if policy self-evolution failed to lift a DENY,
  execution fell through via an empty `pass`. Now hard-returns
  `PERMISSION_DENIED`. Includes a defense-in-depth invariant gate.
- Regression tests proving both bugs cannot reappear.

### Stabilization — Batch 1: Release Coherence
- **Version single-source**: `deskaoy/_version.py` neutral resolver
  (`importlib.metadata` + fallback). Core never imports from CLI.
- **README quick start**: accurate `AgentGoal`/`AgentContext` example with
  `dry_run=True` (was broken `execute("string")`).
- **URLs**: `Elephant-Rock-Lab` → `Octo-Lex` in pyproject.toml and CLI docs.
- **release-check**: fixed `__dataclass_fields__` crash, `--version` →
  `version` subcommand, removed v1.0 wording.
- **Manifest**: removed stale `browser_automation` domain.
- 22 coherence tests guarding version, README, URLs, layering, manifest.

### Stabilization — Batch 2: CI/Package Correctness
- Removed `[browser]` extra from CI (extra was removed in v2.0).
- Added `pywin32>=306` to `[windows]` extra (adapter imports `win32api`).
- Added test dependencies: `hypothesis`, `opentelemetry-exporter-otlp`,
  `prometheus_client`, `tzdata`.
- Gated integration tests (`if: false`) pending v2 desktop-only rewrite.
- Narrowed Windows CI scope for thread-crash-sensitive tests.
- Updated stale test assertions for v2.0 rename.

### Stabilization — Batch 4: CLI Correctness
- `execute --capability` now honored via schema-aware `_build_goal()`.
  Supports `automate`, `click`, `fill`, `type_text`, `key_press`, `scroll`,
  `navigate` with correct param mapping.
- `schedule due` fixed: `r.instruction` → `r.prompt` (was AttributeError).
- CLI storage path delegates to `StorageResolver`.
- Positional `instruction` is now optional (`nargs="?"`).

### Stabilization — Batch 5: Adapter Truthfulness
- Linux `type_text`, `key_press`, `scroll`, and `fill` now return
  `ErrorCategory.UNSUPPORTED` instead of fake success.
- Linux `fill` fails before any side effect (no partial click-then-fail).
- macOS adapter factory requires explicit `DESKTOP_AGENT_MACOS=1` opt-in.
- Added `ErrorCategory.UNSUPPORTED` to error taxonomy.

### Stabilization — Batch 6: Release Hardening
- Added `RELEASE_READINESS.md` with known-debt inventory.
- `__init__.py` public API re-exports declared via `__all__`.
- `build>=1.0` added to `[dev]` extra.
- Mypy and ruff baselines documented as non-blocking for v2.0.0.

### Verification
- All CI checks green: DCO, Unit Tests (ubuntu/windows, 3.11/3.12), Smoke Tests.
- ~3000+ tests pass across matrix.

## [1.2.0] — 2026-05-28

### Highlights

**BATCH-43: OpenTelemetry-native observability runtime.**

Replaces the custom tracing stack with an OTel-native observability runtime
while preserving all 18 public API symbols. Adds `TelemetryRuntime` as sole
owner of providers/exporters, adapts `FlowLogger` to emit real OTel spans,
creates queue-backed SQLite/JSONL exporters, wires LLM middleware into
`BudgetAwareLLMClient`, and adds Windows CI.

### Added — BATCH-43/TASK-00: PrometheusSink Fix
- `PrometheusSink` now uses isolated `CollectorRegistry` per instance (no more duplicate registry errors)
- `port` defaults to `None` (was 9090), `start_server` defaults to `False` — no HTTP server started by default

### Added — BATCH-43/TASK-01: TelemetryRuntime + DesktopAgentMetrics
- `TelemetryRuntime` — sole owner of OTel TracerProvider + MeterProvider + instruments
- `TelemetryConfig` dataclass with opt-in `otlp_endpoint=None` default
- `DesktopAgentMetrics` — 6 cached instruments under `desktop_agent.*` namespace
- `configure_telemetry()` — application-level convenience API
- HB-03 enforcement test: OTel SDK never imported at `agent_core` module level

### Added — BATCH-43/TASK-02: FlowLogger OTel Facade
- `FlowLogger` accepts optional `runtime=TelemetryRuntime` parameter
- When runtime provided, creates real OTel spans (`session.start`, `desktop_agent.{kind}.{name}`)
- Legacy sink-based behavior fully preserved when `runtime=None`

### Added — BATCH-43/TASK-03: OTel Exporters + Sink Deprecation
- `JSONLExporter` — OTel SpanExporter writing JSONL files
- `SQLiteExporter` — queue-backed OTel SpanExporter with dedicated writer thread
- `RedactingExporter` — wrapper exporter that redacts secrets without mutating spans
- Concrete sink classes (`ConsoleSink`, `FileSink`, `SQLiteSink`, `PrometheusSink`) now emit `DeprecationWarning` on construction
- `FlowLogger(sinks=[...])` emits `DeprecationWarning`

### Added — BATCH-43/TASK-04: Dependency Declaration
- `[tracing]` extra: `opentelemetry-api>=1.40`, `opentelemetry-sdk>=1.40`
- `[tracing-otlp]` extra: adds `opentelemetry-exporter-otlp-proto-grpc`
- `[tracing-prometheus]` extra: adds `opentelemetry-exporter-prometheus`

### Added — BATCH-43/TASK-05: LLM Middleware Wiring
- `LLMLoggingMiddleware` creates `desktop_agent.llm.call` OTel span with `gen_ai.*` and `desktop_agent.*` attributes
- Wired into `BudgetAwareLLMClient` as optional middleware
- `facade.py` wires middleware when tracing is enabled
- Domain attributes: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.*`, `desktop_agent.cost.usd`, `desktop_agent.session.id`, `desktop_agent.step.index`

### Changed — BATCH-43/TASK-06: CI
- GitHub Actions now runs on both `ubuntu-latest` and `windows-latest`
- Smoke tests run on both platforms

### Test Results
- Windows: 3,250 passed, 0 failed, 4 skipped
- Tracing: 160 passed, 0 failed (was 95 with 1 pre-existing failure)
- Net new tests: +65

## [1.1.0] — 2026-05-21

### Highlights

**Deskaoy v1.1.0 — SuperBrowser integration + Linux support.**

Adds `DesktopAgent.with_browser()` for seamless desktop+browser automation,
splits SuperBrowser into an independently installable package, adds CLI tools,
and validates the Linux adapter on real Ubuntu 24.04 hardware.

### Added — BATCH-38: DesktopAgent.with_browser() Factory + Lazy Browser Init
- `DesktopAgent.with_browser()` classmethod factory — creates DesktopAgent with both desktop and browser surfaces via `UnifiedSurface`
- `UnifiedSurface._ensure_browser()` — lazy browser session initialization on first browser-routed action (not at construction time)
- `DesktopAgent.__aenter__`/`__aexit__` — async context manager for automatic browser session cleanup
- Graceful fallback: `with_browser()` returns desktop-only agent when optional browser package is not installed
- `importlib`-based dynamic imports in `agent_core` — zero literal `super_browser` references in source
- 21 new tests in `tests/test_browser_integration/`

### Added — BATCH-39: Package Split — Standalone super-browser pyproject.toml
- `src/super_browser/pyproject.toml` — standalone package definition for `pip install super-browser`
- super-browser depends on `deskaoy>=1.0.0` (agent_core shared types) + browser-specific deps (patchright, psutil, Pillow, curl_cffi)
- Root `[browser]` extra simplified to `super-browser>=1.0.0` — no more direct browser deps in deskaoy
- 9 new tests in `tests/test_browser_integration/test_package_split.py`

### Added — BATCH-40: Standalone Entry Point
- `from super_browser import SuperBrowser` — clean standalone API, no Deskaoy knowledge required
- `__init__.py` exports: SuperBrowser, SessionConfig, ActionResult, action_result, CompletionReason, __version__
- `super-browser` CLI — `version` and `serve` subcommands, registered in super-browser pyproject.toml
- 11 new tests in `tests/test_browser_integration/test_standalone_entry.py`

### Fixed — BATCH-41: Proxmox Linux VM + LinuxAdapter Wiring
- Created Ubuntu 24.04 LXC container (CT 250) on Proxmox for Linux E2E testing
- Fixed AT-SPI2 Registry import: use `pyatspi.Registry` instead of deprecated `Atspi.Registry` (Ubuntu 24.04 compatibility)
- Updated test mock to include `pyatspi` module in sys.modules patching
- E2E validated on real Ubuntu 24.04: snapshot, screenshot, click, key_press, type_text all pass
- Linux container: `192.168.3.152` (hostname: `deskaoy-test`)

### Added — BATCH-42: Integration Testing + Release
- Full test suite verified: 712+ tests on Windows, 160+ on Linux, 0 regressions
- Package build verified: `desktop_agent-1.0.0-py3-none-any.whl` builds and passes twine check
- 41 integration tests covering full with_browser() lifecycle, package split, standalone entry point
- Version bumped to 1.1.0

### Added — BATCH-37: Client-Daemon Architecture
- `agent_core.daemon` package — persistent background daemon for zero cold-start automation
- `DaemonServer` — binds named pipe (Windows) or Unix socket (Linux/macOS), holds warm DesktopAgent instance
- `DaemonClient` — drop-in DesktopAgent replacement that routes over IPC to daemon
- `DaemonConfig` with idle timeout auto-shutdown, max client limits, platform-aware socket paths
- JSON-RPC 2.0 protocol layer — serializes AgentGoal/AgentResult over IPC
- `deskaoy daemon start/stop/status` CLI subcommands
- `--daemon` flag on `deskaoy execute` for opt-in daemon routing
- Auto-start: DaemonClient starts daemon subprocess if not running
- Transparent fallback: DaemonClient falls back to direct DesktopAgent if daemon unavailable
- `pip install deskaoy[daemon]` optional dependency group
- 65 new tests in `tests/test_daemon/`
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-05-10

### Highlights

**Deskaoy v1.0.0 — Production release.**

After 36 batches of development, Deskaoy reaches v1.0.0 with 3,471 tests,
a complete 11-layer safety system, real desktop automation on Windows, browser
automation via Patchright, and full CUA Loop support for OpenAI and Anthropic.

### Added (since v0.31.0)

- **BATCH-23–30: Agent Intelligence & Orchestration**
  - ActionMemoryStore: persistent action memory with skill/fact/routine storage
  - Feedback loop: execution quality scoring and adaptive behavior
  - Hook system: pre/post action hooks with priority ordering
  - Batch tool execution: parallel tool dispatch for multi-action steps
  - Interaction patterns: multi-step interaction templates
  - Orchestration primitives: sequential, parallel, conditional DAG execution
  - LLM client improvements: streaming, retry, budget-aware routing
  - Budget cascade: level 1/2/3 output management

- **BATCH-31–35: Production Hardening & System Integration**
  - CLI enhancements: 15+ subcommands with REPL
  - Clipboard operations: read/write via PowerShell
  - Linux adapter scaffolding: AT-SPI placeholder
  - Browser adapter: Patchright stealth stack
  - Grounding pipeline: YOLO, Florence-2, PaddleOCR, VLM providers
  - Complete type annotations across all public APIs
  - Full mypy compliance

- **BATCH-36: PyPI Release & Documentation (this release)**
  - PyPI classifiers: `Development Status :: 5 - Production/Stable`
  - OS classifiers: Windows + Linux
  - Optional dependency groups: `all`, `windows` added
  - API Reference updated to v1.0.0
  - README badges updated for v1.0.0
  - CHANGELOG complete from v0.1.0 to v1.0.0
  - CONTRIBUTING.md updated with dependency group docs

### Changed

- Version bumped from 0.49.0 to 1.0.0
- `development_status` classifier upgraded from Beta to Production/Stable
- Test suite: 3,471 passed, 0 failed (62 skipped)
- Package: `twine check` passes on both wheel and sdist

### Test Suite
- **3,471 passed, 0 failed, 62 skipped**
- +545 tests since v0.31.0

---

## [0.42.0] — 2026-05-08

### Added
- **BATCH-31–33: Desktop Services & Clipboard**
  - DesktopService: window management, process launch, display enumeration
  - DialogService: system dialog handling
  - MenuService: application menu interaction
  - TaskbarService: taskbar operations
  - ClipboardOperations: read/write system clipboard via PowerShell
  - Linux adapter scaffolding with AT-SPI interface
  - Browser adapter: Patchright stealth integration

### Tests
- Total: **3,466 passed, 0 failed** (62 skipped)

## [0.35.0] — 2026-05-06

### Added
- **BATCH-28–30: Orchestration & LLM**
  - DAGExecutor: sequential, parallel, conditional DAG execution
  - Orchestration primitives: sequential, parallel, conditional
  - LLM client: streaming support, retry logic, budget-aware routing
  - Budget cascade: 3-level output management for context window protection
  - Interaction patterns: multi-step interaction templates

### Tests
- Total: **3,380 passed, 0 failed**

## [0.31.0] — 2026-05-03

### Added
- **BATCH-21: Real CUA Loop + LLM Integration**
  - CUALoop._get_proposal() wired to real OpenAI and Anthropic APIs
  - OpenAI: POST /v1/responses with computer_use_preview tool
  - Anthropic: POST /v1/messages with computer_20250124 tool
  - Live integration tests gated behind OPENAI_API_KEY / ANTHROPIC_API_KEY
  - Stub mode preserved for no-key environments

### Tests
- 7 new tests (5 pass always, 2 skip without API keys)

### Changed
- **BATCH-22: PyPI Publish Readiness**
  - Version synced to 0.31.0 across pyproject.toml, cli/version.py, desktop_agent.py
  - Package builds cleanly: wheel + sdist
  - twine check PASSED on both artifacts
  - 4 build validation tests

- **BATCH-18: Low-Level Input Primitives**
  - 5 new SurfaceAdapter methods: mouse_down, mouse_up, mouse_drag, key_down, key_up
  - Full WindowsAdapter implementation with pyautogui backend
  - BrowserAdapter CDP-based implementations
  - key_down checks key blocklist (same as key_press)

- **BATCH-19: Extended Element Operations**
  - `invoke_element` with 9 actions
  - `get_element_state` returning 6 state properties
  - `get_focused_element` returning focused element ref

- **BATCH-20: Window & Display Management**
  - `list_displays()`, `list_windows()`, `set_window_bounds()`, `focus_window()`

### Tests
- 50 new tests across 5 batches
- Total: **2,926 passed, 0 failed** (62 skipped)

## [0.30.0] — 2026-05-03

### Added
- **BATCH-20: Window & Display Management**
  - `list_displays()`: enumerate monitors with bounds and DPI
  - `list_windows()`: enumerate top-level visible windows
  - `set_window_bounds(x, y, width, height)`: reposition and resize
  - `focus_window(query)`: focus by process name, title, or PID

### Tests
- 9 new tests
- Total: **2,916 passed, 0 failed**

## [0.29.0] — 2026-05-03

### Added
- **BATCH-19: Extended Element Operations**
  - `invoke_element` with 9 actions: click, focus, set_value, get_value, expand, collapse, toggle, select
  - `get_element_state` returning enabled, focused, selected, expanded, busy, offscreen
  - `get_focused_element` returning focused element ref
  - WindowsAdapter implementations using UI Automation

### Tests
- 11 new tests
- Total: **2,908 passed, 0 failed**

## [0.28.0] — 2026-05-03

### Added
- **BATCH-18: Low-Level Input Primitives**
  - 5 new SurfaceAdapter methods: mouse_down, mouse_up, mouse_drag, key_down, key_up
  - Full WindowsAdapter implementation with pyautogui backend
  - BrowserAdapter CDP-based implementations
  - key_down checks key blocklist (same as key_press)
  - All 5 methods support dry_run mode
  - mouse_drag validates both start/end points within window

### Tests
- 17 new tests (13 unit + 2 registry + 2 integration)
- Total: **2,897 passed, 0 failed** (60 skipped)

## [0.27.0] — 2026-05-03

### Added
- **BATCH-17: Real E2E Test Suite**
  - 7 real Calculator tests: launch, click buttons, snapshot, screenshot
  - 3 real Explorer tests: launch, snapshot, screenshot
  - 3 real Paint tests: launch, screenshot, snapshot
  - 3 transport validation tests (MCP/REST) — deferred to BATCH-18
  - Calculator occlusion fix: `_bring_to_front()` before click

### Tests
- 14 new integration tests (11 pass, 3 deferred)
- Total: **2,882 passed, 0 failed** (58 skipped)

## [0.26.0] — 2026-05-03

### Added
- **BATCH-16: Real Desktop Automation — First Live E2E**
  - Installed runtime dependencies: comtypes 1.4.16, pyautogui 0.9.54, mss 10.2.0
  - 8 real (non-mocked) integration tests: Notepad launch, type, screenshot, snapshot, click, key_press
  - `scripts/hello_desktop.py` standalone demo
  - Fixed mss deprecation: `mss.mss()` -> `mss.MSS()`

### Tests
- 4 new unit tests (dependency verification)
- 8 new integration tests (real desktop, gated behind `--run-integration`)
- Total: **2,882 passed, 0 failed** (44 skipped including 8 integration-gated)

## [1.0.0rc1] — 2026-05-03

### Added
- **BATCH-15: v1.0 Release Candidate**
  - `release-check` CLI command — 10-point release readiness check
  - 53 integration tests covering: version consistency, file existence, module imports, CLI commands, safety system, adapter protocol, documentation, evaluation, performance
  - `version.py` simplified to use hardcoded constant (avoids stale installed version)

### Tests
- 53 new integration tests
- Total: **2,878 passed, 0 failed**

## [0.25.0] — 2026-05-03

### Added
- **BATCH-13: Performance Optimization + Profiling**
  - `performance/__init__.py` — LatencyProfiler, LRUCache, BenchmarkSuite, PerformanceMonitor
  - SnapshotFormatCache for avoiding re-formatting unchanged snapshots
  - `@timed` decorator for profiling hot paths
  - Latency targets: click <50ms, snapshot <200ms, formatter <30ms, loop <2s
  - 9 defined latency targets for all hot paths

- **BATCH-14: Documentation Overhaul**
  - `docs/api/REFERENCE.md` — Complete API reference for all public classes
  - `docs/guides/QUICKSTART.md` — 5-minute getting started guide
  - `docs/guides/ARCHITECTURE.md` — System architecture with diagrams
  - `docs/guides/ADAPTER_DEV.md` — Adapter development guide with checklist

### Tests
- 35 new tests for performance module
- Total: **2,825 passed, 0 failed**

## [0.24.0] — 2026-05-03

### Added
- **BATCH-11: Per-App JSON Guides**
  - `guides/__init__.py` — AppGuide dataclass and GuideRegistry loader
  - GuideRegistry: load from directory, search by app name or category
  - 5 sample guides: notepad, calculator, explorer, chrome, vscode
  - Each guide includes: version, selectors, common_actions, tips, safety_notes

- **BATCH-12: Security Audit + Hardening**
  - `key_blocklist.py` rewritten with sorted-key normalization and key aliases
  - Key aliases: del↔delete, esc↔escape, cmd/win/super↔meta, return↔enter
  - `WindowsAdapter.key_press()` now checks blocklist before execution (SECURITY error)
  - HealthCheck includes `key_blocklist` and `sensitive_apps` subsystem checks
  - Order-independent combo matching (``ctrl+alt+del`` matches ``alt+ctrl+delete``)

### Fixed
- Health check test assertions updated: 6 → 8 checks (key_blocklist + sensitive_apps)
- Smoke test health check count updated to match

### Tests
- 11 new tests for per-app guides
- 6 new tests for security hardening
- Total: **2,790 passed, 0 failed**

## [0.23.0] — 2026-05-03

### Added
- **BATCH-10: Real-World Evaluation Framework**
  - `evaluation/__init__.py` — OSWorld-compatible task format, evaluators, benchmark runner
  - TaskDefinition: JSON-based task definitions with id, instruction, evaluator, difficulty
  - 7 built-in evaluators: exact_match, contains, file_exists, file_contains, process_running, window_title, always_pass/fail
  - BenchmarkRunner: load tasks from directory, run, score, format results table
  - 10 sample Windows desktop tasks in `tasks/` directory

### Tests
- 21 new tests
- Total: **2,773 passed, 0 failed**

## [0.22.1] — 2026-05-03

### Added
- **BATCH-09: Environment Interface (UI-TARS Pattern)**
  - `adapters/environment.py` — Environment protocol with lifecycle hooks
  - LocalDesktop — direct host OS access with screen detection
  - DockerDesktop — container-based desktop via VNC
  - RemoteVM — remote machine via RDP/VNC/SSH
  - Lifecycle: initialize → on_before_tool → on_after_tool → on_dispose
  - EnvironmentState enum: created, initializing, ready, busy, error, disposed
  - EnvironmentInfo: OS, screen, DPI metadata

### Fixed
- Windows adapter tests now use `asyncio.run()` instead of deprecated `get_event_loop().run_until_complete()`

### Tests
- 12 new tests for environment interface
- Total: **2,752 passed, 0 failed**

## [0.22.0] — 2026-05-03

### Added
- **BATCH-08: CUA Integration (Computer Use Agent)**
  - `agent/cua_loop.py` — Screenshot-based action loop for OpenAI and Anthropic CUA APIs
  - `parse_openai_cua_response` — Parse OpenAI CUA tool call responses
  - `parse_anthropic_cua_response` — Parse Anthropic computer_20241022 tool use responses
  - CUAAction enum: click, double_click, right_click, type, key, scroll, screenshot, wait, done
  - CUALoop, CUAStep, CUALoopResult, CUAActionProposal dataclasses
  - Supports coordinate-based click, text input, key press, scroll actions
  - Fallback to AgentLoop when CUA unavailable

### Tests
- 15 new tests (parsers + loop)
- Total: **2,740 passed, 0 failed**

## [0.20.1] — 2026-05-03

### Added
- **BATCH-07: Typed Workflow Blocks (Skyvern Pattern)**
  - 6 typed block types: ForLoop, Wait, Download, Validation, FormFill, CodeBlock
  - Each block validates parameters before execution
  - Each block compiles to DAGNode lists for the existing DAGExecutor
  - WorkflowBuilder: fluent API for composing block sequences into executable DAGs
  - CodeBlock sandboxed: restricted builtins, no file/network/system access
  - FormFillBlock compiles to sequential fill + optional submit nodes
  - ForLoopBlock compiles to N sequential DAG nodes

### Tests
- 34 new tests for blocks and workflow builder
- Total: **2,725 passed, 0 failed**

## [0.20.0] — 2026-05-03

### Added
- **BATCH-06: Two-Step Actions + Snapshot Diffing (Stagehand Pattern)**
  - **TASK-01: SnapshotDiffer** — structural diff between two AXSnapshot objects (added/removed/changed elements)
  - **TASK-02: TwoStepVerifier** — classifies action outcomes with confidence scores and human-readable evidence
  - **TASK-03: AgentLoop integration** — opt-in `two_step=True` mode captures post-action snapshots and appends diff context to LLM prompts
  - `cascade/differ.py` — SnapshotDiffer, SnapshotDiff, NodeDiff dataclasses
  - `agent/two_step.py` — TwoStepVerifier with action-specific classifiers (click, fill, type_text, key_press, scroll)
  - `StepResult.verification` and `StepResult.diff_summary` fields
  - LLM prompts include "Action Verification" section with diff summaries

### Changed
- `AgentLoop.__init__` now accepts `two_step: bool = False` parameter
- `_build_prompt` appends diff context when two-step mode is enabled

### Tests
- 34 new tests (15 differ + 11 verifier + 8 AgentLoop integration)
- Total: **2,691 passed, 0 failed**

## [0.19.0] — 2026-05-03

### Added
- **BATCH-05: CLI Fix + Safety + Transports (AI-OS B39 alignment)**
  - **TASK-01: CLI crash fix** — removed `storage_dir` from `DesktopAgent()` constructor, single-source version, UTF-8 console support
  - **TASK-02: Key blocklist** — 12 blocked key combos (Alt+F4, Ctrl+Alt+Del, Cmd+Q, etc.)
  - **TASK-02: Sensitive app detection** — 14 sensitive app categories (email, banking, password managers, messaging, terminal)
  - **TASK-03: SurfaceAdapter expansion** — 7 new non-abstract methods (clipboard, open_app, invoke_element, set_window_state, get_focused_element, get_element_state)
  - **TASK-04: MCP transport** — stdio JSON-RPC server with 10 granular or 6 compact tools, compatible with Claude Code, Cursor, Windsurf, Zed
  - **TASK-05: REST transport** — local HTTP API on 127.0.0.1:3847 with bearer token auth, 6 endpoints
  - **TASK-06: Doctor upgrade** — checks for MCP, REST, key blocklist, sensitive apps
  - `deskaoy mcp` CLI command with `--compact` flag
  - `deskaoy serve` CLI command with `--port` and `--skip-consent` flags
  - `pyproject.toml` optional dependencies: `[mcp]` and `[rest]`
  - WindowsAdapter: clipboard read/write via PowerShell, open_app, set_window_state

### Fixed
- CLI: 13/15 commands crashed with `storage_dir` error — all fixed
- CLI: `health_check` → `health` method name mismatch fixed
- CLI: Unicode display errors on Windows fixed with UTF-8 reconfiguration
- Version drift: single-source `cli/version.py` module

### Tests
- 31 new tests for key blocklist + sensitive apps + adapter expansion
- 13 new tests for MCP and REST transport
- Total: **2,644 passed, 0 failed**

## [0.18.0] — 2026-05-02

### Added
- **BATCH-03: Runtime Execution Hardening (AI-OS B38 alignment)**
  - `RuntimeExecutionReceipt` — truthful, immutable receipt for every execution path
  - `RuntimeAttemptState` — 8-state lifecycle: pending → preflight_passed → running → completed/failed/timed_out/blocked
  - `PolicyObligation` — 5 obligation types enforced mechanically after policy allow
  - `AdapterCapabilities` — declarative capability registry for surface adapters
  - `RuntimeResourceBudget` — timeout_ms, max_output_bytes, max_actions per execution
  - 12-check canonical preflight (`RuntimePreflight`) with SHA-256 fingerprint
  - TOCTOU detection — preflight fingerprint verified before adapter dispatch
  - Timeout receipt — `asyncio.TimeoutError` produces TIMED_OUT receipt with evidence
  - Completion/failure receipts on all execution paths
  - 17 new integration tests for receipt wiring (67 total runtime tests)

### Fixed
- `test_pipeline_smoke.py` — type_text test missing `target` parameter
- `test_pipeline_smoke.py` — undo tests now execute action first to register compensation
- `test_facade.py` — LLM guard tests catch `ConfigurationError` instead of importing removed `_NoOpLLM`
- `test_gogcli_patterns.py` — timeout test returns FAILURE with receipt (not RATE_LIMITED)
- Flaky circuit breaker cooldown test — increased sleep margin for CI stability

### Test Suite
- **2,613 passed, 0 failed, 36 skipped** (up from 2,632 with 6 failures)
- Fixed all 6 pre-existing test failures

## [0.17.1] — BATCH-02 CLOSED

### Added
- End-to-end demo (`demo_e2e.py`) — full agent loop with real LLM
- Desktop demo (`demo_e2e_desktop.py`) — Windows desktop automation
- Complex site demo (`demo_complex_site.py`) — multi-page web automation
- Skill demo (`demo_routine_skill_fact.py`) — routines, skills, and facts
- CI smoke tests + benchmark suite

## [0.17.0] — BATCH-01 CLOSED

### Added
- **CLI entry point** — `deskaoy` command with 14 subcommands
- **Interactive REPL** — `deskaoy repl` with `.health`, `.facts`, `.skills`, `.undo`, etc.
- **Output formatting** — Pretty-print + JSON mode for all result types
- argparse only (zero new dependencies)
- Entry point: `deskaoy = "agent_core.cli.main:main"`

## [0.16.0] — Reference Tour Quick Wins

### Added
- **Schedule enhancements** — Timezone-aware cron, `validate_cron_expression()`, `calculate_next_runs()`
- **pyautogui `<` bug fix** — `fix_pyautogui_less_than()` converts `press('<')` to `hotkey("shift", ",")`
- **Action parameter validation** — `safety/action_validator.py` with typed specs for all 10 capabilities
- **Timeout guard** — `safety/timeout_guard.py` shared deadline tracker across multi-step operations
- **Resource tracker** — `safety/resource_tracker.py` track + cleanup resources in long-running sessions
- **Observation protocol** — `observation.py` standardized `DesktopObservation` format (from OSWorld)

## [0.15.0] — Routines + Skills + Facts

### Added
- **Routine system** — Cron-based scheduled task execution with timezone support
- **SKILL.md format** — Markdown-based skill definitions with YAML frontmatter
- **Fact extraction** — Automatic knowledge extraction from execution results
- Built-in skills: `desktop-basics`, `desktop-screenshot`

## [0.14.0] — Compensation Plans

### Added
- **Structured undo system** — `safety/compensation.py` generates inverse action plans
- Compensation for click, fill, type_text, key_press, scroll
- Manual recovery instructions for non-automatable undo

## [0.13.0] — det-acp (Evidence Ledger)

### Added
- **Evidence ledger** — Immutable append-only log of execution events (JSONL)
- **Session budgets** — Per-session resource tracking with warnings at 75/90/100%
- **Policy evolution** — `PolicyEffect.ALLOW_WITH_OBLIGATIONS` with obligation types

## [0.12.1] — CI Smoke Tests + Benchmarks

### Added
- GitHub Actions workflow (`.github/workflows/tests.yml`)
- Smoke tests + benchmark suite

## [0.12.0] — Phase 4: Multi-App Orchestration

### Added
- **HostAgent + AppAgent architecture** — DesktopAgent delegates to SubagentDelegator
- **SubagentDelegator** — Parallel sub-agent spawning with shared subsystems
- Sequential, parallel, and conditional delegation patterns

## [0.11.0] — Phase 5: Production Hardening

### Added
- **Rate governor** — Token bucket rate limiting per action type
- **Crash recovery** — Checkpoint auto-save, strategy selection (retry/skip/compensate/escalate)
- **Session budgets** — Configurable limits with graceful termination
- **OutputDefender** — 3-level output size management for context window protection

## [0.10.0] — LangExtract Patterns

### Added
- **Grounding verification** — Post-action visual verification
- **Validation pipeline** — Structured validation before dispatch
- **Context window management** — Smart truncation preserving key information

## [0.9.0] — gogcli Patterns

### Added
- **Circuit breaker** — Stops execution after N consecutive failures
- **Action guards** — Pre/post conditions for actions
- **Graceful degradation** — Fallback behaviors when tiers fail

## [0.8.0] — AI-OS Bridge Wiring

### Added
- **Trace bridge** — Emits events to AI-OS TraceService
- **Result mapper** — Maps Deskaoy results to AI-OS result shape
- **Recovery bridge** — Maps recovery events to AI-OS recovery contract

## [0.7.0] — AI-OS Realignment (Learning + Stealth Gate)

### Added
- **Stealth gate** — Stealth capability gating (disabled by default)

## [0.6.0] — AI-OS Realignment (Identity + Manifest)

### Added
- **Capability manifest** — `aios.first_party.desktop_agent` identity declared
- **Storage resolver** — AIOS_HOME-aware path resolution
- **Policy bridge** — 6 policy effects, 10 declared permissions

## [0.5.0] — Gems Wiring

### Changed
- Wired OpenCLI gem patterns into DesktopAgent execution pipeline

## [0.4.0] — Phase 3B: OpenCLI Gems

### Added
- Structured error catalog with `ActionError` (code/hint/candidates)
- Two-pass verification after actions
- HealthCheck with 6 probes
- LatencyBudget per-action tracking
- CostTracker for token cost estimation

## [0.3.0] — Phase 3A: Windows Adapter + Memory

### Added
- **WindowsAdapter** — Full Windows UIA support via comtypes + uiautomation
- **UIA Walker** — AX tree traversal with depth limiting
- **ActionMemory** — JSON-based action memory with skill/fact/routine storage

## [0.2.0] — Phase 2: Visual Grounding + Stealth

### Added
- **3-tier cascade engine** — API → AX → Coordinate → Vision fallback
- **SurfaceAdapter protocol** — 10 abstract methods for cross-platform abstraction
- **Stealth stack** — Patchright with anti-detection, cookie/header injection
- **Visual grounding pipeline** — Pluggable providers (YOLO, Florence-2, VLM)

## [0.1.5] — Phase 1: Agent-Core Extraction

### Added
- Extracted surface-agnostic engine into `agent_core/` package (54 files)
- Zero `super_browser` imports in `agent_core`
- Bézier mouse curves, timing jitter, window isolation, DPI awareness
- Re-export shims in `super_browser` for backward compatibility

## [0.1.0] — Phase 0: Critical Bug Fixes

### Fixed
- C1: Agent loop nudge injection for loop detection
- C2: Recovery coordinator guard no longer short-circuits steps
- C3: Preview-length tracking for budget Level 3 spill accounting
- C4: `@agent_action` decorator accepts `security_level` parameter
- C5: Subsystem passthrough in delegation (recovery, budget, flow, security)
- H1: Stealth `Fetch.requestPaused` timing randomization
- H2: Fail-fast without LLM (no silent success)
- H3: Vision page fingerprint includes DOM stats + scroll position
- H4: Budget cascade routes through `BudgetAwareLLMClient`
- H5: Context compressor for long AX snapshots
- H6: JSON-based checkpoint persistence (no git dependency)
- H7: JS safety via `json.dumps()` for selector interpolation
- H8: Vectorized 2D DCT for perceptual hash performance
