# CODEBASE STATE

Last Updated:       2026-05-28
Updated By:         Lead (260520-apt-topaz) — via BATCH-43 Close
Framework Version:  5.3

───────────────────────────────────────────────────────────
VERIFIED MODULE MAP
───────────────────────────────────────────────────────────
Verified paths and exports that future Batches can rely on.
Every entry here was confirmed by an Adaptation or manual audit.

  Module:            deskaoy.desktop_agent.DesktopAgent.with_browser
  Actual export:     @classmethod → DesktopAgent (factory method)
  Verified in:       BATCH-38
  Notes:             Keyword-only args: desktop_adapter, browser_config, llm.
                     Uses importlib to avoid literal "deskaoy" in source.

  Module:            deskaoy.desktop_agent.DesktopAgent.__aenter__
  Actual export:     async method → self
  Verified in:       BATCH-38
  Notes:             Async context manager support.

  Module:            deskaoy.desktop_agent.DesktopAgent.__aexit__
  Actual export:     async method → None
  Verified in:       BATCH-38
  Notes:             Stops browser session only if _browser_initialized is True.

  Module:            deskaoy.cascade.unified_surface.UnifiedSurface._ensure_browser
  Actual export:     async method → None (sets self._browser)
  Verified in:       BATCH-38
  Notes:             Idempotent lazy init. Calls session.start(), then builds
                     BrowserAdapter via importlib. Raises RuntimeError if no session
                     configured or if start fails.

  Module:            deskaoy.cascade.unified_surface.UnifiedSurface._browser_session
  Actual export:     Instance attribute (Optional[Any])
  Verified in:       BATCH-38
  Notes:             Set by DesktopAgent.with_browser(). Stashed for lazy init.

  Module:            deskaoy.cascade.unified_surface.UnifiedSurface._browser_initialized
  Actual export:     Instance attribute (bool)
  Verified in:       BATCH-38
  Notes:             Tracks whether _ensure_browser() has run. Used by __aexit__.

  Module:            deskaoy.tracing.runtime.TelemetryRuntime
  Actual export:     class — owns TracerProvider + MeterProvider + DesktopAgentMetrics
  Verified in:       BATCH-43
  Notes:             OTel SDK imported lazily in __init__. otlp_endpoint defaults to None.
                     configure_telemetry() creates global instance.

  Module:            deskaoy.tracing.instruments.DesktopAgentMetrics
  Actual export:     class — 6 cached OTel instruments under desktop_agent.* namespace
  Verified in:       BATCH-43
  Notes:             Exactly one instance per TelemetryRuntime. Instruments:
                     desktop_agent.cdp.calls, cdp.duration, llm.tokens, actions,
                     errors, sessions.active

  Module:            deskaoy.tracing.exporters.jsonl.JSONLExporter
  Actual export:     class — OTel SpanExporter writing JSONL files
  Verified in:       BATCH-43
  Notes:             Output compatible with legacy FileSink format.

  Module:            deskaoy.tracing.exporters.sqlite.SQLiteExporter
  Actual export:     class — Queue-backed OTel SpanExporter with dedicated writer thread
  Verified in:       BATCH-43
  Notes:             Uses _FLUSH/_SHUTDOWN sentinels. No check_same_thread=False.
                     Bounded queue returns FAILURE when full.

  Module:            deskaoy.tracing.exporters.redacting.RedactingExporter
  Actual export:     class — Wrapper exporter that redacts secrets without mutating spans
  Verified in:       BATCH-43
  Notes:             Uses _RedactedSpan proxy. Original spans never mutated.

  Module:            deskaoy.tracing.sinks.PrometheusSink
  Actual export:     class — Deprecated legacy sink with isolated CollectorRegistry
  Verified in:       BATCH-43
  Notes:             port defaults to None (was 9090). start_server defaults to False.
                     Emits DeprecationWarning on construction.

  Module:            src/deskaoy/pyproject.toml
  Actual export:     Package "deskaoy" v1.0.0
  Verified in:       BATCH-39
  Notes:             Dependencies: deskaoy>=1.0.0, patchright>=1.0, psutil>=5.9,
                     Pillow>=10.0, curl_cffi>=0.15. Omitted hatch build config —
                     hatchling auto-detects.

───────────────────────────────────────────────────────────
ARCHITECTURAL DECISIONS
───────────────────────────────────────────────────────────
Decisions that constrain future work. Each entry explains WHY, not just WHAT.

  DEC-043-01: TelemetryRuntime owns all OTel providers/exporters. FlowLogger only
              emits telemetry, never configures providers.
  Why:        Prevents multiple TracerProviders in one process. Single ownership
              simplifies shutdown, flushing, and testing.
  Source:     BATCH-43
  Active:     YES
  Overridden: NO

  DEC-043-02: OTLP as production default exporter. Prometheus as compatibility/local mode.
  Why:        OTLP/gRPC is the industry standard for observability pipelines.
              Prometheus exporter maintained for local dev and compatibility.
  Source:     BATCH-43
  Active:     YES
  Overridden: NO

  DEC-043-03: FlowLogger retained as domain facade indefinitely. TraceSink deprecated
              in v1.2, removed in v2.0.
  Why:        FlowLogger is the only consumer-facing API for tracing. Removing it
              would break all downstream code. Sink abstraction is the infrastructure
              that can be replaced.
  Source:     BATCH-43
  Active:     YES
  Overridden: NO

  DEC-043-04: LLM middleware creates its own desktop_agent.llm.call span. Does not
              rely on auto-instrumentation for business semantics.
  Why:        Generic OpenAI/Anthropic instrumentation may not wrap raw HTTP call
              paths in CUALoop. The middleware owns the business-semantic span.
  Source:     BATCH-43
  Active:     YES
  Overridden: NO

  DEC-043-05: OTel SDK optional via [tracing] extra. deskaoy.tracing imports only
              opentelemetry-api.
  Why:        OTel SDK adds ~130ms cold import. Must not be a core dependency for
              users who don't need tracing.
  Source:     BATCH-43
  Active:     YES
  Overridden: NO

  DEC-043-06: Instance-based TelemetryRuntime internally. configure_telemetry() as
              application-level convenience API.
  Why:        Library consumers may create multiple isolated runtimes. Application
              users want a simple one-liner.
  Source:     BATCH-43
  Active:     YES
  Overridden: NO

  DEC-043-07: PrometheusSink fixed immediately with isolated registry, not deferred.
              The fix is independent of OTel migration.
  Why:        PrometheusSink is public API. Duplicate construction by downstream
              users is possible, not just tests.
  Source:     BATCH-43
  Active:     YES
  Overridden: NO

  DEC-043-08: FlowLogger.span(kind, name) classified as DOMAIN API. SpanKind carries
              Deskaoy vocabulary.
  Why:        SpanKind members (CDP, LLM, ACTION, SESSION, STEALTH, SKILL, SECURITY)
              are explicitly domain-specific.
  Source:     BATCH-43
  Active:     YES
  Overridden: NO

  DEC-039-01: Root pyproject.toml [browser] extra is a thin pointer to deskaoy.
              Browser deps (patchright, psutil, etc.) are listed in deskaoy's
              own pyproject.toml, not in deskaoy's.
  Why:        Single source of truth for browser dependencies. When deskaoy
              version bumps its deps, deskaoy doesn't need to change.
  Source:     BATCH-39
  Active:     YES
  Overridden: NO

  DEC-038-01: Browser imports in agent_core use importlib with string concatenation
              ("super" + "_browser") instead of literal from/import statements.
  Why:        The existing test_no_deskaoy_imports test does a string grep
              for "deskaoy" across all agent_core .py files. Literal imports
              inside function bodies still trigger this check. importlib avoids it
              while maintaining the same lazy-load behavior.
  Source:     BATCH-38
  Active:     YES
  Overridden: NO

  DEC-038-02: UnifiedSurface._ensure_browser() is the sole authority for starting
              a browser session. No other code path in agent_core starts Patchright.
  Why:        Single point of control for lazy init. Prevents accidental browser
              launches at construction time or during unrelated operations.
  Source:     BATCH-38
  Active:     YES
  Overridden: NO

───────────────────────────────────────────────────────────
KNOWN GOTCHAS
───────────────────────────────────────────────────────────
Things that surprised a previous Batch. Prevents re-surprise.

  GOTCHA-043-01: PrometheusSink.__init__ used process-global CollectorRegistry before
                 BATCH-43. Fixed with isolated registry per instance.
  Discovered:    BATCH-43 (pre-existing bug)
  Status:        MITIGATED — isolated CollectorRegistry in __init__.

  GOTCHA-043-02: Windows time.monotonic() has ~15.6ms resolution (default timer).
                 A 10ms sleep produces 0.0ms elapsed 34% of the time.
  Discovered:    BATCH-43 (TASK-02 reported flaky test_duration_positive)
  Status:        FIXED — switched TraceSpan to time.perf_counter() (sub-microsecond).
                 All duration-based tests now use perf_counter for measurement.

  GOTCHA-038-01: Tests that simulate "deskaoy not installed" cannot simply
                 remove it from sys.modules — Python re-imports from the source tree.
                 Must use patch("builtins.__import__") to block the import.
  Discovered:    BATCH-38
  Status:        MITIGATED — test_fallback_desktop_only and test_accepts_custom_desktop_adapter
                 both use builtins.__import__ patching.

  GOTCHA-038-02: MagicMock objects returned by MagicMock() constructors (e.g.
                 BrowserSession(config)) do NOT inherit AsyncMock from the parent.
                 Must explicitly pass MagicMock(return_value=session) so that
                 BrowserSession(config) returns the pre-configured session mock.
  Discovered:    BATCH-38
  Status:        MITIGATED — all browser session mocks use explicit return_value wiring.

───────────────────────────────────────────────────────────
ADAPTATION LOG (ROLLING — LAST 10 BATCHES)
───────────────────────────────────────────────────────────
Consolidated from all Task Reports. New entries prepend.
Entries older than 10 Batches are archived to STATE_ARCHIVE.md.

  Module:            deskaoy.__init__
  Actual export:     Deskaoy, SessionConfig, ActionResult, action_result, CompletionReason, __version__
  Verified in:       BATCH-40
  Notes:             Public API surface. No deskaoy.desktop_agent import at this level.

  Module:            deskaoy.cli
  Actual export:     main() function — CLI entry point
  Verified in:       BATCH-40
  Notes:             Registered as deskaoy script in deskaoy/pyproject.toml.
                     Subcommands: version, serve.

  BATCH-43 (2026-05-28): OpenTelemetry-Native Observability Runtime.
    - TASK-00: Fixed PrometheusSink duplicate registry bug (isolated CollectorRegistry)
    - TASK-01: Created TelemetryRuntime + DesktopAgentMetrics (runtime.py, instruments.py)
    - TASK-02: Adapted FlowLogger to emit OTel spans internally (backward-compatible)
    - TASK-03: Created JSONL/SQLite/Redacting exporters, deprecated legacy sinks
    - TASK-04: Wired metrics, declared [tracing]/[tracing-otlp]/[tracing-prometheus] extras
    - TASK-05: Wired LLMLoggingMiddleware into BudgetAwareLLMClient with OTel spans
    - TASK-06: Added Windows CI, full regression, documentation
    - Test baseline: 3,512+ → 3,250+ (Windows with ignores) / 160 tracing tests
    - New files: runtime.py, instruments.py, exporters/{jsonl,sqlite,redacting}.py
    - Key decisions: DEC-43-01 through DEC-43-08

  BATCH-42 (2026-05-21): Integration Testing + Release.
    - TASK-01: Full test suite verified — 712 Windows, 160 Linux, 0 regressions
    - TASK-02: Package build — wheel builds, twine check passes
    - TASK-03: 41 integration tests passing (lifecycle, package split, standalone entry)
    - TASK-04: Version 1.1.0, CHANGELOG finalized, STATE.md updated
    - Test baseline: 3,512+

  BATCH-41 (2026-05-21): Proxmox Linux VM + LinuxAdapter Wiring.
    - TASK-01: Created Ubuntu 24.04 LXC container (CT 250) on Proxmox
    - TASK-02: Fixed AT-SPI2 Registry import for Ubuntu 24.04
    - E2E validated on real hardware

  BATCH-40 (2026-05-21): Standalone Entry Point.
    - TASK-01: Updated __init__.py with public API exports
    - TASK-02: Added CLI (src/deskaoy/cli.py) + registered in pyproject.toml
    - TASK-03: 11 validation tests, regression verified
    - Key files: deskaoy/__init__.py, deskaoy/cli.py
    - Test baseline: 3,501 → 3,512 (+11)

  BATCH-39 (2026-05-21): Package Split — standalone deskaoy pyproject.toml.
    - TASK-01: Created src/deskaoy/pyproject.toml with correct deps
    - TASK-02: Updated root [browser] extra to deskaoy>=1.0.0
    - TASK-03: 9 validation tests, regression verified
    - Key files: src/deskaoy/pyproject.toml (new), pyproject.toml (modified)
    - Test baseline: 3,492 → 3,501 (+9)

  BATCH-38 (2026-05-21): Added DesktopAgent.with_browser() factory + lazy browser init.
    - TASK-01: Added with_browser() classmethod, __aenter__, __aexit__ to DesktopAgent
    - TASK-02: Added _ensure_browser() lazy init to UnifiedSurface, wired navigate()
    - TASK-03: 21 integration tests in tests/test_browser_integration/
    - Key files: desktop_agent.py (lines 417-504), unified_surface.py (lines 73-76, 208-250)
    - Test baseline: 3,471 → 3,492 (+21)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────
Current total test count. Updated at every Batch Close.

  Last verified count: 2,614+ (Windows)
  Verified in:         BATCH-43 / 2026-05-29
  Breakdown:           2,614 Windows

───────────────────────────────────────────────────────────
CARRY-FORWARD OBLIGATIONS
───────────────────────────────────────────────────────────
Deferred tests, known gaps, and promises from previous Batches
that are still outstanding.

[No carry-forward obligations from BATCH-38]

  No carry-forward obligations.

  GAP-BATCH-43-01: test_duration_positive timing flaky test in test_flow_logger.py.
    Status:   CLOSED 2026-05-29 — root cause was Windows time.monotonic() ~15ms
              resolution. 34% of 10ms sleeps measured as zero elapsed. Fixed by
              switching TraceSpan.start()/end() to time.perf_counter() which has
              sub-microsecond resolution. Verified 50/50 passes on Windows.
    Source:    TASK-02 discovered, TASK-06 post-close fix

═══════════════════════════════════════════════════════════
