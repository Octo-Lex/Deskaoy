"""LLMLoggingMiddleware — auto-trace LLM calls.

When a :class:`TelemetryRuntime` is provided, the middleware creates its own
``deskaoy.llm.call`` OTel span with ``gen_ai.*`` and ``deskaoy.*``
attributes (AUTH-03).  When *runtime* is ``None`` it falls back to the
FlowLogger-based span path so that callers without OTel continue to work.
"""

from __future__ import annotations

from typing import Any

from deskaoy.tracing.flow_logger import FlowLogger
from deskaoy.tracing.types import SpanKind


class LLMLoggingMiddleware:

    def __init__(self, logger: FlowLogger, *, runtime: Any = None) -> None:
        self._logger = logger
        self._runtime = runtime  # TelemetryRuntime | None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def wrap(
        self,
        fn: Any,
        *args: Any,
        provider: str = "unknown",
        model: str = "unknown",
        **kwargs: Any,
    ) -> Any:
        """Execute *fn* inside an LLM tracing span.

        If a :class:`TelemetryRuntime` was supplied at construction the call is
        wrapped in a ``deskaoy.llm.call`` OTel span.  Otherwise the legacy
        FlowLogger :class:`SpanScope` is used.
        """
        if self._runtime is not None:
            return await self._wrap_otel(fn, *args, provider=provider, model=model, **kwargs)
        return await self._wrap_legacy(fn, *args, provider=provider, model=model, **kwargs)

    # ------------------------------------------------------------------
    # OTel path
    # ------------------------------------------------------------------

    async def _wrap_otel(
        self,
        fn: Any,
        *args: Any,
        provider: str = "unknown",
        model: str = "unknown",
        **kwargs: Any,
    ) -> Any:
        # Lazy imports — HB-03
        from opentelemetry.trace import StatusCode  # noqa: F811

        tracer = self._runtime.tracer()
        span_name = "deskaoy.llm.call"

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("gen_ai.system", provider)
            span.set_attribute("gen_ai.request.model", model)

            # Attach domain context from FlowLogger if available
            from deskaoy.tracing.flow_logger import _current_context
            ctx = _current_context.get()
            if ctx is not None:
                span.set_attribute("deskaoy.session.id", ctx.session_id)
                span.set_attribute("deskaoy.step.index", ctx.step_id)

            try:
                result = fn(*args, **kwargs)
                if hasattr(result, "__await__"):
                    result = await result

                token_input = getattr(result, "input_tokens", 0) or 0
                token_output = getattr(result, "output_tokens", 0) or 0
                cost_usd = getattr(result, "cost_usd", 0.0) or 0.0

                span.set_attribute("gen_ai.usage.input_tokens", token_input)
                span.set_attribute("gen_ai.usage.output_tokens", token_output)
                span.set_attribute("deskaoy.cost.usd", cost_usd)
                return result
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                raise

    # ------------------------------------------------------------------
    # Legacy (FlowLogger) path
    # ------------------------------------------------------------------

    async def _wrap_legacy(
        self,
        fn: Any,
        *args: Any,
        provider: str = "unknown",
        model: str = "unknown",
        **kwargs: Any,
    ) -> Any:
        span_scope = self._logger.span(
            SpanKind.LLM, f"llm.{provider}.chat",
            attributes={"provider": provider, "model": model},
        )
        async with span_scope as span:
            try:
                result = fn(*args, **kwargs)
                if hasattr(result, '__await__'):
                    result = await result

                span.token_input = getattr(result, 'input_tokens', 0) or 0
                span.token_output = getattr(result, 'output_tokens', 0) or 0
                span.token_cost_usd = getattr(result, 'cost_usd', 0.0) or 0.0
                span.attributes["token_input"] = span.token_input
                span.attributes["token_output"] = span.token_output
                return result
            except Exception as exc:
                span.set_error(exc)
                raise
