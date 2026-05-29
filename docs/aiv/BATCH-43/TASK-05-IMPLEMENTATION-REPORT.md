# TASK-05 Implementation Report — LLM Middleware Wiring

**Task ID:**       BATCH-43/TASK-05
**Priority:**      High
**Status:**        ✅ APPROVED
**Implemented by:** Assistant (session 260528-vital-crane)
**Approved by:**   Lead (260520-apt-topaz)
**Date:**          2026-05-28

## Objective

Refactor `LLMLoggingMiddleware` to create `desktop_agent.llm.call` OTel span with `gen_ai.*` and `desktop_agent.*` attributes. Wire into `BudgetAwareLLMClient` and `facade.py`.

## Files Changed

| File | Action | Lines | Detail |
|:-----|:-------|:------|:-------|
| `src/agent_core/tracing/middleware.py` | MODIFIED | 42→130 | Added `runtime` kwarg, `_wrap_otel()` creates OTel span with gen_ai.* + desktop_agent.* attrs, legacy fallback preserved |
| `src/agent_core/budget/client.py` | MODIFIED | +8 | `middleware: Optional[Any] = None` param, Step 5 dispatches through middleware |
| `src/super_browser/agent/facade.py` | MODIFIED | +10 | Creates TelemetryRuntime + LLMLoggingMiddleware in trace_enabled block |
| `tests/test_tracing/test_middleware_wiring.py` | NEW | ~200 | 7 tests covering all TEST-43-05-xx IDs |

## OTel Span Attributes

| Attribute | Source |
|:----------|:-------|
| `gen_ai.system` | `provider` param |
| `gen_ai.request.model` | `model` param |
| `gen_ai.usage.input_tokens` | Token count from result |
| `gen_ai.usage.output_tokens` | Token count from result |
| `desktop_agent.cost.usd` | Cost calculation |
| `desktop_agent.session.id` | FlowLogger.current_context() |
| `desktop_agent.step.index` | FlowLogger.current_context() |

## Tests Added: +7

| Test ID | Behavior |
|:--------|:---------|
| TEST-43-05-01 | Middleware creates `desktop_agent.llm.call` span |
| TEST-43-05-02 | gen_ai.* attributes set on span |
| TEST-43-05-03 | desktop_agent.* attributes set on span |
| TEST-43-05-04 | Fallback when runtime=None (FlowLogger path) |
| TEST-43-05-05 | Exception sets span status to ERROR |
| TEST-43-05-06 | BudgetAwareLLMClient invokes middleware |
| TEST-43-05-07 | facade.py wires middleware when tracing |

## Test Results

- **160 passed, 0 failed** (153 TASK-04 baseline + 7 new)

## Acceptance Criteria

| AC | Status |
|:---|:-------|
| AC-05-01: LLM spans include provider/model/tokens/error | ✅ MET |
| AC-05-02: Desktop-Agent attributes on LLM spans | ✅ MET |
| AC-05-03: Tests prove middleware invoked by real LLM call path | ✅ MET |
| AC-05-04: Middleware optional — works without it | ✅ MET |

## Key Design Decisions

- DEC-43-04: Middleware creates own span (not auto-instrumentation)
- COR-43-07: LLM middleware creates its own span, does not rely on auto-instrumentation

## Partial Sign-Off

`docs/aiv/BATCH-43/PARTIAL-TASK-05-2026-05-28.md`
