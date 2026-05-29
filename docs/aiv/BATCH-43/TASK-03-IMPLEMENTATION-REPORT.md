# TASK-03 Implementation Report — OTel Exporters and Legacy Sink Deprecation

**Task ID:**       BATCH-43/TASK-03
**Priority:**      High
**Status:**        ✅ APPROVED
**Implemented by:** Assistant (session 260528-misty-owl)
**Approved by:**   Lead (260520-apt-topaz)
**Date:**          2026-05-28

## Objective

Create 3 OTel exporters (JSONL, SQLite, Redacting) and add deprecation warnings to legacy concrete sinks.

## Files Created

| File | Lines | Detail |
|:-----|:------|:-------|
| `src/agent_core/tracing/exporters/__init__.py` | 1 | Package init |
| `src/agent_core/tracing/exporters/jsonl.py` | 85 | JSONLExporter — writes spans to JSONL files |
| `src/agent_core/tracing/exporters/sqlite.py` | 190 | SQLiteExporter — queue-backed with dedicated writer thread |
| `src/agent_core/tracing/exporters/redacting.py` | 100 | RedactingExporter — wrapper that redacts secrets without mutating spans |
| `tests/test_tracing/test_exporters.py` | 310 | 21 tests |

## Files Modified

| File | Detail |
|:-----|:-------|
| `src/agent_core/tracing/sinks.py` | `import warnings` + `DeprecationWarning` in `__init__` of ConsoleSink, FileSink, SQLiteSink, PrometheusSink |
| `src/agent_core/tracing/flow_logger.py` | `warnings.warn` when `sinks=` parameter is non-empty |

## Tests Added: +21

- JSONLExporter: output format, to_dict shape, file writing, shutdown
- SQLiteExporter: queue-backed writer, flush durability, shutdown drain, bounded queue rejection
- RedactingExporter: attribute redaction, no span mutation, delegate passthrough
- Deprecation: sink construction warnings, FlowLogger sinks warning, no warning on empty sinks

## Test Results

- **148 passed, 0 failed** (127 TASK-02 baseline + 21 new)
- 29 deprecation warnings (expected from legacy sink tests)

## Acceptance Criteria

| AC | Status |
|:---|:-------|
| AC-03-01: JSONL output compatible with FileSink format | ✅ MET |
| AC-03-02: SQLite output uses SessionDB.insert_events() | ✅ MET |
| AC-03-03: Queue-backed SQLite writer (COR-43-09) | ✅ MET |
| AC-03-04: RedactingExporter wraps delegate, no span mutation (COR-43-04) | ✅ MET |
| AC-03-05: Deprecation on concrete construction only (COR-43-05) | ✅ MET |
| AC-03-06: All existing sink tests pass | ✅ MET |

## Design Adaptations

1. **SQLite flush**: `_FLUSH` and `_SHUTDOWN` sentinel objects (not `None`) to avoid killing writer thread
2. **RedactingExporter**: `_RedactedSpan` proxy class instead of mutating OTel span internals
3. **FlowLogger warning**: only fires when `sinks` list is non-empty (empty list is falsy, no warning)

## Partial Sign-Off

`docs/aiv/BATCH-43/PARTIAL-TASK-03-2026-05-28.md`
