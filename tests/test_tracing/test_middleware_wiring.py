"""Middleware wiring test — verifies LLMLoggingMiddleware integrates with BudgetAwareLLMClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from deskaoy.budget.client import BudgetAwareLLMClient
from deskaoy.tracing.flow_logger import FlowLogger
from deskaoy.tracing.middleware import LLMLoggingMiddleware
from deskaoy.tracing.runtime import TelemetryConfig, TelemetryRuntime


def _make_budget_client(*, with_middleware: bool = False, exporter=None):
    """Create a BudgetAwareLLMClient with mocked deps."""
    governor = MagicMock()
    cascade = MagicMock()
    cascade.resolve = AsyncMock(return_value=("openai", "gpt-4", AsyncMock()))
    credential_pool = MagicMock()
    credential_pool.get = AsyncMock(return_value=MagicMock())
    circuit_breaker = MagicMock()
    circuit_breaker.allow = MagicMock(return_value=True)
    compressor = MagicMock()
    compressor.compress = AsyncMock(return_value=([], 0))

    middleware = None
    if with_middleware:
        runtime = TelemetryRuntime(TelemetryConfig())
        if exporter is not None:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            provider = TracerProvider()
            provider.add_span_processor(SimpleSpanProcessor(exporter))
            runtime._tracer_provider = provider
            runtime._tracer = provider.get_tracer("test")

        logger = FlowLogger()
        middleware = LLMLoggingMiddleware(logger, runtime=runtime)

    client = BudgetAwareLLMClient(
        governor=governor,
        cascade=cascade,
        credential_pool=credential_pool,
        circuit_breaker=circuit_breaker,
        compressor=compressor,
        middleware=middleware,
    )
    return client


class TestBudgetClientMiddleware:
    def test_client_accepts_middleware(self):
        """BudgetAwareLLMClient accepts middleware parameter."""
        client = _make_budget_client(with_middleware=True)
        assert client._middleware is not None

    def test_client_works_without_middleware(self):
        """BudgetAwareLLMClient works fine without middleware."""
        client = _make_budget_client(with_middleware=False)
        assert client._middleware is None

    def test_middleware_param_is_optional(self):
        """BudgetAwareLLMClient defaults middleware to None."""

        # Just verify the constructor accepts omitting middleware
        import inspect
        sig = inspect.signature(BudgetAwareLLMClient.__init__)
        mid_param = sig.parameters.get("middleware")
        assert mid_param is not None
        assert mid_param.default is None
