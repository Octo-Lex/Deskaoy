BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-43
Blueprint Version:        3.1
Cycle Mode:               STANDARD
Lead Programmer:          Lead (Session 260520-apt-topaz)
Date Issued:              2026-05-28
Review SLA:               30 min
Execution SLA per Task:   60 min
Partial Sign-Off SLA:     15 min
Task Sequencing:          SEQUENTIAL (Phase 0 → 1 → 2 → 3 → 4 → 5 → 6)

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────

Replace the custom tracing stack in agent_core.tracing with an
OpenTelemetry-native observability runtime while preserving all 18
public API symbols exported through super_browser.tracing.__init__.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────

What the code MUST do:
  - Fix PrometheusSink duplicate registry bug (isolated CollectorRegistry)
  - Create TelemetryRuntime as sole owner of OTel providers/exporters
  - Adapt FlowLogger to emit OTel spans internally while preserving domain facade
  - Create OTel SpanExporters (JSONL, SQLite queue-backed, RedactingExporter)
  - Deprecate TraceSink and concrete sink classes (import-compatible, warns)
  - Wire LLMLoggingMiddleware into BudgetAwareLLMClient with Desktop-Agent LLM span
  - Declare [tracing], [tracing-otlp], [tracing-prometheus] optional extras
  - Add Windows CI to GitHub Actions matrix

What the code MUST NOT do:
  - Start a Prometheus HTTP server by default in PrometheusSink
  - Enable OTLP export by default (otlp_endpoint=None)
  - Mutate ended OTel spans for redaction (use exporter wrapper instead)
  - Emit deprecation warnings at import time or __init_subclass__
  - Rely on auto-instrumentation for LLM business semantics
  - Register prometheus_client metrics in process-global registry
  - Import opentelemetry-sdk at agent_core module level

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────

  Lint command:  python -m ruff check src/

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: All 18 symbols in super_browser.tracing.__all__ MUST remain
         importable after this Batch. Removing or renaming any symbol
         is a violation.

  HB-02: FlowLogger MUST NOT register OTel providers, processors,
         readers, exporters, or Prometheus metrics. TelemetryRuntime
         is the sole owner of provider/exporter/instrument lifecycle.

  HB-03: opentelemetry-sdk MUST NOT be imported at agent_core module
         level. All OTel SDK imports MUST be lazy (inside functions or
         behind try/except ImportError).

  HB-04: No code change in this Batch MUST break any existing test that
         currently passes. The 94/95 passing tracing tests must remain
         green; the 1 failing test (PrometheusSink) must be fixed.

  HB-05: PrometheusSink() MUST NOT start an HTTP server by default.
         port parameter MUST default to None, not 9090.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

Current tracing source files (src/agent_core/tracing/):
  types.py (176 lines) — SpanKind(10-member StrEnum), SpanStatus(3-member StrEnum),
    TraceContext(dataclass), TraceEvent(dataclass), TraceSpan(dataclass),
    SessionSummary(frozen dataclass), CostRecord(dataclass)
  flow_logger.py (319 lines) — FlowLogger, TraceScope, SpanScope
  sinks.py (178 lines) — TraceSink(ABC), ConsoleSink, FileSink, SQLiteSink, PrometheusSink
  session_db.py (243 lines) — SessionDB (SQLite + FTS5, 3 tables + FTS virtual)
  middleware.py (42 lines) — LLMLoggingMiddleware (dead code, never wired)
  cost_analytics.py (49 lines) — CostAnalytics
  __init__.py (1 line, empty)

Re-export surface (src/super_browser/tracing/__init__.py, 29 lines):
  18 symbols in __all__: CostAnalytics, CostRecord, ConsoleSink, FileSink,
  FlowLogger, LLMLoggingMiddleware, PrometheusSink, SessionDB, SessionSummary,
  SQLiteSink, SpanKind, SpanScope, SpanStatus, TraceContext, TraceEvent,
  TraceSink, TraceSpan, TraceScope

External consumers:
  super_browser/agent/facade.py:99-107 — creates FlowLogger with ConsoleSink/FileSink
  agent_core/results/types.py:173 — trace_id docstring reference

Key constructors:
  FlowLogger(sinks: list[TraceSink] | None, *, max_events_per_trace: int = 10000,
             redact_patterns: tuple[str,...])
  SessionDB(db_path: Path) — self._conn: Optional[sqlite3.Connection] = None
    in __init__; sqlite3.connect called lazily in initialize() method
  BudgetAwareLLMClient(governor, cascade, credential_pool, circuit_breaker,
                       compressor, llm_client=None)

Installed OTel packages (transitive, not declared):
  opentelemetry-api==1.41.0, opentelemetry-sdk==1.41.0
  opentelemetry-exporter-otlp-proto-grpc==1.41.0
  opentelemetry-semantic-conventions-ai==0.5.1
  prometheus_client (installed, direct dep of PrometheusSink)
  opentelemetry-exporter-prometheus: MISSING

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────

  AUTH-01: TelemetryRuntime owns TracerProvider, MeterProvider, all processors,
           readers, exporters, and the DesktopAgentMetrics instrument instance.
           No other code creates providers or registers instruments.

  AUTH-02: FlowLogger emits telemetry via runtime.tracer() when runtime is provided.
           When runtime is None, it falls back to the current sink-based behavior.
           FlowLogger never calls set_tracer_provider() or similar globals.

  AUTH-03: LLMLoggingMiddleware creates its own "desktop_agent.llm.call" span.
           It does not rely on auto-instrumentation for business semantics.
           Provider auto-instrumentation creates nested spans inside it.

  AUTH-04: configure_telemetry() is an application-level convenience only.
           Library consumers may create TelemetryRuntime directly.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────

  BATCH-42 (closed) — v1.1.0 release baseline
  STATE.md exists — last updated 2026-05-21 (BATCH-42 Close)
  No unresolved Carry-Forward Obligations
  All 3,216 Windows tests pass (1 pre-existing PrometheusSink failure)
  All 2,804 Linux tests pass (Proxmox CT 250)

───────────────────────────────────────────────────────────
STATE.md STATUS
───────────────────────────────────────────────────────────

  State file exists:       [X] YES
  Last Updated:            2026-05-21
  Batches since update:    1 (BATCH-43 is the first since BATCH-42)
  Reconciliation audit:    [X] N/A (< 5 batches since update)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────

  Baseline at Blueprint issuance:  3,512+ tests (STATE.md BATCH-42)
  Tracing tests:                   95 (7+17+34+4+22+11=95; 94 pass, 1 fail — PrometheusSink)
  Note: 3,216 = Windows pytest run with 12 ignore dirs (excludes integration,
        smoke, benchmarks, stress, browser, vision, etc.). 3,843 = total test
        methods in repo. 3,512+ = STATE.md verified count from BATCH-42.
  Expected delta (all Tasks):      +61 new tests
  Expected total at Batch close:   3,573+ tests

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-00: BATCH-43/TASK-00 — Fix PrometheusSink Registry Collision
  Priority:          Critical
  Description:       Fix the duplicate CollectorRegistry bug in PrometheusSink.
                     Create isolated CollectorRegistry per instance. Do NOT start
                     HTTP server by default. Port defaults to None, start_server
                     defaults to False. Add passing regression test.
  Files in scope:    src/agent_core/tracing/sinks.py
                     tests/test_tracing/test_sinks.py
  Depends on:        None
  Required Tests:
    | Test ID          | Type | Behavior Verified                    | Failure Mode                          | Falsified By                                     | Pass Criteria                          |
    |:-----------------|:-----|:-------------------------------------|:--------------------------------------|:-------------------------------------------------|:---------------------------------------|
    | TEST-43-00-01    | unit | PrometheusSink() creates isolated registry | Duplicate CollectorRegistry ValueError | Remove registry= param from Counter(), run test | No ValueError, metrics registered on isolated registry |
    | TEST-43-00-02    | unit | Two PrometheusSink instances coexist | Second construction crashes           | Revert to global REGISTRY, construct two sinks   | Both construct without error           |
    | TEST-43-00-03    | unit | PrometheusSink() does not start HTTP server | Network listener opened unexpectedly  | Remove start_server=False default, check socket  | No port 9090 listener after construction |
    | TEST-43-00-04    | unit | Previously failing test now passes  | test_no_error_without_prometheus fails | Revert isolated registry fix                     | test passes, no ValueError             |
  Acceptance Criteria:
    AC-00-01: PrometheusSink() can be constructed repeatedly in one process
    AC-00-02: No HTTP server started by default
    AC-00-03: All 95 tracing tests pass (0 fail)
  Traceability:
    AC-00-01 → TEST-43-00-01, TEST-43-00-02
    AC-00-02 → TEST-43-00-03
    AC-00-03 → TEST-43-00-04

TASK-01: BATCH-43/TASK-01 — TelemetryRuntime and DesktopAgentMetrics
  Priority:          High
  Description:       Create TelemetryRuntime (owns TracerProvider + MeterProvider)
                     and DesktopAgentMetrics (cached instruments under desktop_agent.*
                     namespace). OTel SDK imported lazily. OTLP endpoint defaults to None.
                     Phase 1 tests use InMemorySpanExporter only.
  Files in scope:    src/agent_core/tracing/runtime.py (NEW)
                     src/agent_core/tracing/instruments.py (NEW)
                     tests/test_tracing/test_runtime.py (NEW)
                     tests/test_tracing/test_instruments.py (NEW)
                     tests/test_tracing/test_no_otel_at_import.py (NEW)
  Depends on:        TASK-00
  Required Tests:
    | Test ID          | Type | Behavior Verified                    | Failure Mode                          | Falsified By                                     | Pass Criteria                          |
    |:-----------------|:-----|:-------------------------------------|:--------------------------------------|:-------------------------------------------------|:---------------------------------------|
    | TEST-43-01-01    | unit | TelemetryRuntime creates TracerProvider | Provider not created                  | Skip TracerProvider creation in __init__         | tracer() returns non-None Tracer       |
    | TEST-43-01-02    | unit | TelemetryRuntime creates MeterProvider | Provider not created                  | Skip MeterProvider creation in __init__          | meter() returns non-None Meter         |
    | TEST-43-01-03    | unit | TelemetryRuntime shutdown flushes    | Spans lost on shutdown                | Remove shutdown() body, check InMemoryExporter   | force_flush returns True, spans exported |
    | TEST-43-01-04    | unit | configure_telemetry sets global runtime | Global not accessible                 | Don't store in module var                        | Second call returns same runtime       |
    | TEST-43-01-05    | unit | ImportError when OTel SDK missing    | Silent failure / wrong error          | Mock import to raise ImportError                 | ImportError with install message       |
    | TEST-43-01-06    | unit | OTLP exporter added only when endpoint set | OTLP connects to unconfigured collector | Set otlp_endpoint to non-None, check processors | OTLPSpanExporter in processor chain    |
    | TEST-43-01-07    | unit | OTLP NOT added when endpoint is None | Unwanted network connection           | Set otlp_endpoint=None, inspect processors       | No OTLPSpanExporter present            |
    | TEST-43-01-08    | unit | DesktopAgentMetrics creates instruments | No metrics recorded                   | Remove create_counter call                       | record_cdp_call() increments counter   |
    | TEST-43-01-09    | unit | DesktopAgentMetrics session lifecycle | Session count wrong                   | Remove up_down_counter                           | session_started + session_ended = net 0 |
    | TEST-43-01-10    | unit | One DesktopAgentMetrics per runtime  | Duplicate instruments                 | Create metrics twice for same runtime            | Same object identity (is check)        |
    | TEST-43-01-11    | unit | HB-03: OTel SDK not in sys.modules after agent_core import | OTel eagerly imported at module level | Add `import opentelemetry.sdk` to agent_core/__init__.py | 'opentelemetry.sdk' not in sys.modules after `import agent_core` |
  Acceptance Criteria:
    AC-01-01: TelemetryRuntime creates isolated TracerProvider + MeterProvider
    AC-01-02: OTLP endpoint is None by default (no automatic export)
    AC-01-03: ImportError raised with clear message when OTel SDK missing
    AC-01-04: DesktopAgentMetrics uses desktop_agent.* namespace
    AC-01-05: Exactly one DesktopAgentMetrics instance per TelemetryRuntime
    AC-01-06: FlowLogger unchanged, all 95 existing tests pass
    AC-01-07: HB-03 enforced — OTel SDK not imported at agent_core load
  Traceability:
    AC-01-01 → TEST-43-01-01, TEST-43-01-02
    AC-01-02 → TEST-43-01-07
    AC-01-03 → TEST-43-01-05
    AC-01-04 → TEST-43-01-08
    AC-01-05 → TEST-43-01-10
    AC-01-06 → (verified by running full tracing test suite)
    AC-01-07 → TEST-43-01-11

TASK-02: BATCH-43/TASK-02 — FlowLogger OTel Facade
  Priority:          High
  Description:       Adapt FlowLogger to emit OTel spans internally when runtime
                     is provided. Preserve domain facade interface. trace_id format
                     changes to OTel hex only when runtime is active.
  Files in scope:    src/agent_core/tracing/flow_logger.py
                     tests/test_tracing/test_flow_logger.py
                     tests/test_tracing/test_flow_logger_otel.py (NEW)
  Depends on:        TASK-01
  Required Tests:
    | Test ID          | Type | Behavior Verified                    | Failure Mode                          | Falsified By                                     | Pass Criteria                          |
    |:-----------------|:-----|:-------------------------------------|:--------------------------------------|:-------------------------------------------------|:---------------------------------------|
    | TEST-43-02-01    | unit | FlowLogger with runtime creates OTel span | No span in exporter                   | Skip start_as_current_span call                  | InMemoryExporter has 1 span            |
    | TEST-43-02-02    | unit | FlowLogger without runtime unchanged | Existing behavior breaks              | Set runtime param to None, check UUID trace_id   | trace_id is UUID format                |
    | TEST-43-02-03    | unit | trace_id is hex when runtime active  | trace_id still UUID format            | Skip OTel span context reading                   | trace_id matches r'^[0-9a-f]{32}$'     |
    | TEST-43-02-04    | unit | Span error sets OTel ERROR status    | Error spans show OK                   | Remove status=StatusCode.ERROR in __aexit__      | span.status == ERROR                   |
    | TEST-43-02-05    | unit | FlowLogger.events still populated    | Events buffer empty with runtime      | Skip _store_event call                           | len(logger.events) > 0                 |
    | TEST-43-02-06    | unit | current_context works with runtime   | Returns None when runtime active      | Skip _current_context.set in TraceScope          | current_context() returns TraceContext  |
    | TEST-43-02-07    | unit | Redaction preserved with runtime     | Secrets leak into span attributes     | Remove redaction call                            | No "password" in span attributes        |
    | TEST-43-02-08    | unit | All existing flow_logger tests pass  | Regression                            | Revert any OTel integration change               | 34 existing tests pass                 |
  Acceptance Criteria:
    AC-02-01: OTel spans visible via InMemorySpanExporter when runtime provided
    AC-02-02: FlowLogger(sinks=[...]) still works (backward compat)
    AC-02-03: FlowLogger.events still works
    AC-02-04: FlowLogger.current_context() still works
    AC-02-05: All 95 existing tracing tests pass
  Traceability:
    AC-02-01 → TEST-43-02-01
    AC-02-02 → TEST-43-02-02
    AC-02-03 → TEST-43-02-05
    AC-02-04 → TEST-43-02-06
    AC-02-05 → TEST-43-02-08

TASK-03: BATCH-43/TASK-03 — OTel Exporters and Legacy Sink Deprecation
  Priority:          High
  Description:       Create JSONLExporter, SQLiteExporter (queue-backed), RedactingExporter.
                     Convert sinks to deprecated adapters (warn on construction only).
  Files in scope:    src/agent_core/tracing/exporters/__init__.py (NEW)
                     src/agent_core/tracing/exporters/jsonl.py (NEW)
                     src/agent_core/tracing/exporters/sqlite.py (NEW)
                     src/agent_core/tracing/exporters/redacting.py (NEW)
                     src/agent_core/tracing/sinks.py
                     tests/test_tracing/test_exporters.py (NEW)
                     tests/test_tracing/test_sinks.py
  Depends on:        TASK-02
  Required Tests:
    | Test ID          | Type | Behavior Verified                    | Failure Mode                          | Falsified By                                     | Pass Criteria                          |
    |:-----------------|:-----|:-------------------------------------|:--------------------------------------|:-------------------------------------------------|:---------------------------------------|
    | TEST-43-03-01    | unit | JSONLExporter writes spans to file   | Empty file / wrong format             | Skip file.write in export()                      | File has 1+ non-empty lines            |
    | TEST-43-03-02    | unit | SQLiteExporter batch inserts spans   | Spans not in database                 | Skip queue drain in writer thread                | SessionDB has matching events          |
    | TEST-43-03-03    | unit | SQLiteExporter returns FAILURE on full queue | Silent data loss                     | Set max_queue=1, send 2 batches                  | Second export returns FAILURE          |
    | TEST-43-03-04    | unit | SQLiteExporter force_flush durable   | Spans not flushed to disk             | Skip drain in force_flush                        | force_flush returns True, data on disk |
    | TEST-43-03-05    | unit | RedactingExporter strips secrets    | API keys in output                    | Remove redaction logic                           | No "Bearer" or "sk-" in output         |
    | TEST-43-03-06    | unit | RedactingExporter delegates to inner | Spans lost                            | Skip delegate.export() call                      | Inner exporter received spans          |
    | TEST-43-03-07    | unit | Concrete sinks emit DeprecationWarning | No warning / wrong location          | Remove warnings.warn from __init__               | warnings.catch_warnings records warning |
    | TEST-43-03-08    | unit | FlowLogger(sinks=) emits DeprecationWarning | No warning when sinks passed         | Remove warning from FlowLogger.__init__          | warnings.catch_warnings records warning |
    | TEST-43-03-09    | unit | No import-time deprecation warnings  | Warning on module import              | Import module, check warnings list               | No warnings during import              |
    | TEST-43-03-10    | unit | Runtime + JSONL integration          | JSONL exporter not wired              | Skip exporter creation in TelemetryRuntime       | Spans appear in JSONL file             |
    | TEST-43-03-11    | unit | Runtime + SQLite integration         | SQLite exporter not wired             | Skip exporter creation                           | Spans appear in SessionDB              |
  Acceptance Criteria:
    AC-03-01: JSONL output matches existing FileSink format
    AC-03-02: SQLite output matches existing SQLiteSink format
    AC-03-03: Queue-backed SQLite writer has no thread safety violations
    AC-03-04: RedactingExporter creates redacted copies, does not mutate spans
    AC-03-05: Deprecation warnings on concrete sink construction only (not import)
    AC-03-06: All existing sink tests pass
  Traceability:
    AC-03-01 → TEST-43-03-01
    AC-03-02 → TEST-43-03-02
    AC-03-03 → TEST-43-03-03, TEST-43-03-04
    AC-03-04 → TEST-43-03-05, TEST-43-03-06
    AC-03-05 → TEST-43-03-07, TEST-43-03-08, TEST-43-03-09
    AC-03-06 → (verified by running existing sink tests)

TASK-04: BATCH-43/TASK-04 — Metrics Wiring and Dependency Declaration
  Priority:          Medium
  Description:       Wire DesktopAgentMetrics into TelemetryRuntime. Declare
                     [tracing], [tracing-otlp], [tracing-prometheus] extras.
  Files in scope:    src/agent_core/tracing/runtime.py
                     pyproject.toml
                     tests/test_tracing/test_runtime.py
  Depends on:        TASK-03
  Required Tests:
    | Test ID          | Type | Behavior Verified                    | Failure Mode                          | Falsified By                                     | Pass Criteria                          |
    |:-----------------|:-----|:-------------------------------------|:--------------------------------------|:-------------------------------------------------|:---------------------------------------|
    | TEST-43-04-01    | unit | Runtime exposes metrics property     | AttributeError                        | Remove @property decorator                       | runtime.metrics returns DesktopAgentMetrics |
    | TEST-43-04-02    | unit | Metrics recorded through runtime     | Counter not incremented               | Skip metrics.record_cdp_call                     | MeterReader has recorded values        |
    | TEST-43-04-03    | unit | pyproject.toml has tracing extras    | pip install fails                     | Remove [tracing] section                         | extras parseable and installable       |
  Acceptance Criteria:
    AC-04-01: DesktopAgentMetrics accessible via TelemetryRuntime.metrics
    AC-04-02: desktop_agent.* namespace used for all instruments
    AC-04-03: [tracing], [tracing-otlp], [tracing-prometheus] extras declared
    AC-04-04: opentelemetry-exporter-prometheus NOT a core dependency
  Traceability:
    AC-04-01 → TEST-43-04-01
    AC-04-02 → TEST-43-04-02
    AC-04-03 → TEST-43-04-03
    AC-04-04 → (verified by inspecting pyproject.toml)

TASK-05: BATCH-43/TASK-05 — LLM Middleware Wiring
  Priority:          High
  Description:       Refactor LLMLoggingMiddleware to create desktop_agent.llm.call
                     span with gen_ai.* and desktop_agent.* attributes. Wire into
                     BudgetAwareLLMClient. Wire in facade.py.
  Files in scope:    src/agent_core/tracing/middleware.py
                     src/agent_core/budget/client.py
                     src/super_browser/agent/facade.py
                     tests/test_tracing/test_middleware.py
                     tests/test_tracing/test_middleware_wiring.py (NEW)
  Depends on:        TASK-04
  Required Tests:
    | Test ID          | Type | Behavior Verified                    | Failure Mode                          | Falsified By                                     | Pass Criteria                          |
    |:-----------------|:-----|:-------------------------------------|:--------------------------------------|:-------------------------------------------------|:---------------------------------------|
    | TEST-43-05-01    | unit | Middleware creates desktop_agent.llm.call span | No span created                     | Skip tracer.start_as_current_span                | InMemoryExporter has "desktop_agent.llm.call" |
    | TEST-43-05-02    | unit | Middleware sets gen_ai attributes    | No gen_ai.* on span                  | Remove set_attribute calls                       | span has gen_ai.system, gen_ai.request.model |
    | TEST-43-05-03    | unit | Middleware sets domain attributes    | No desktop_agent.* on span           | Remove domain attribute setting                  | span has desktop_agent.cost.usd, session.id |
    | TEST-43-05-04    | unit | Middleware without runtime fallback | Crashes when runtime=None            | Set runtime=None, call wrap()                    | Uses FlowLogger span, no crash         |
    | TEST-43-05-05    | unit | Middleware error sets span ERROR     | Error span shows OK                  | Skip status=ERROR on exception                   | span.status == ERROR on exception      |
    | TEST-43-05-06    | unit | BudgetAwareLLMClient invokes middleware | Middleware never called              | Remove middleware check from call()              | InMemoryExporter has LLM span after call() |
    | TEST-43-05-07    | unit | facade.py wires middleware when tracing | Middleware not created               | Remove middleware creation in facade              | BudgetAwareLLMClient._middleware is set |
  Acceptance Criteria:
    AC-05-01: LLM spans include provider/model/tokens/error status
    AC-05-02: Desktop-Agent attributes (session, step, cost) on LLM spans
    AC-05-03: Tests prove middleware invoked by real LLM call path
    AC-05-04: Middleware optional — BudgetAwareLLMClient works without it
  Traceability:
    AC-05-01 → TEST-43-05-02
    AC-05-02 → TEST-43-05-03
    AC-05-03 → TEST-43-05-06, TEST-43-05-07
    AC-05-04 → TEST-43-05-04

TASK-06: BATCH-43/TASK-06 — CI, Regression, and Release Gate
  Priority:          Critical
  Description:       Add Windows CI to GitHub Actions. Full Windows + Linux
                     regression. Update CHANGELOG, STATE.md, sign-off docs.
  Files in scope:    .github/workflows/tests.yml
                     docs/aiv/BATCH-43/SIGN-OFF.md (NEW)
                     docs/aiv/BATCH-43/BATCH_43.md (NEW)
                     CHANGELOG.md
                     STATE.md
  Depends on:        TASK-05
  Required Tests:
    | Test ID          | Type | Behavior Verified                    | Failure Mode                          | Falsified By                                     | Pass Criteria                          |
    |:-----------------|:-----|:-------------------------------------|:--------------------------------------|:-------------------------------------------------|:---------------------------------------|
    | TEST-43-06-01    | e2e  | Windows full regression 3,216+ pass  | Test count drops or failures          | Revert any TASK-00 fix, run suite                | 0 failures, count >= 3,216            |
    | TEST-43-06-02    | e2e  | Linux full regression 2,804+ pass   | Test count drops or failures          | Run on Proxmox CT 250                           | 0 failures, count >= 2,804            |
    | TEST-43-06-03    | e2e  | Tracing tests all pass (95 + ~60 new)| Any tracing test fails                | Revert OTel integration                         | 0 failures in tests/test_tracing/      |
    | TEST-43-06-04    | manual | GitHub Actions YAML valid          | CI syntax error                       | Remove matrix line                              | YAML parses, both OS jobs defined      |
  Acceptance Criteria:
    AC-06-01: Windows CI passes on GitHub Actions
    AC-06-02: Ubuntu CI passes on GitHub Actions
    AC-06-03: Proxmox stress suite remains green (70 tests)
    AC-06-04: twine check --strict passes
    AC-06-05: Import time impact documented (before/after)
  Traceability:
    AC-06-01 → TEST-43-06-01, TEST-43-06-04
    AC-06-02 → TEST-43-06-02, TEST-43-06-04
    AC-06-03 → TEST-43-06-02
    AC-06-04 → TEST-43-06-03
    AC-06-05 → (manual measurement, documented in SIGN-OFF)

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  BAC-01: All 18 symbols in super_browser.tracing.__all__ remain import-compatible.
  BAC-02: TelemetryRuntime is the sole owner of provider/exporter/instrument lifecycle.
  BAC-03: OTel SDK and exporters are optional extras, not core imports.
  BAC-04: PrometheusSink() can be constructed repeatedly without duplicate registry failure.
  BAC-05: FlowLogger.events remains functional for v1.x.
  BAC-06: SQLite export is queue-backed (thread-safe).
  BAC-07: LLM middleware tested through real LLM call path before claiming integration.
  BAC-08: Ubuntu and Windows CI both pass on GitHub Actions.
  BAC-09: CHANGELOG.md updated with BATCH-43 entry.
  BAC-10: All documents archived under /docs/aiv/BATCH-43/.

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────

Reviewer Report ID:       REVIEW-BATCH-43-2026-05-28
Review Cycle:             1
Lead Decision:            [X] ACCEPT WITH MODIFICATIONS

Flags acted on:
  FLAG-01 (MEDIUM, HB-03 enforcement) → Added TEST-43-01-11 to TASK-01.
    New test file: tests/test_tracing/test_no_otel_at_import.py.
    Verifies opentelemetry.sdk not in sys.modules after agent_core import.
  FLAG-02 (MEDIUM, baseline discrepancy) → Fixed. Test Baseline section now
    clarifies: 3,512+ (STATE.md), 3,216 (Windows with ignores), 3,843 (total).
  FLAG-03 (LOW, test count 35→34) → Fixed. TEST-43-02-08 now reads 34.
  FLAG-04 (LOW, SessionDB constructor) → Fixed. Data Models now describes
    lazy initialization correctly.
  FLAG-05 (LOW, TASK-03 file count) → NOT ACTED ON. 7 files at boundary but
    not over. Independently rollbackable.
  FLAG-06 (LOW, flaky test) → NOT ACTED ON. No flow_logger flaky gotcha
    exists in STATE.md. If timing issues emerge, handled as Deviation.
  FLAG-07 (MEDIUM, STATE.md stale) → NOT ACTED ON. Verified STATE.md on disk
    shows Last Updated: 2026-05-21 by BATCH-42 Close. STATE.md IS current.
    Reviewer may have read cached version.

Blueprint Version after response: 3.1
Lead Sign:                Lead (260520-apt-topaz) — 2026-05-28 19:05 UTC+3

═══════════════════════════════════════════════════════════
