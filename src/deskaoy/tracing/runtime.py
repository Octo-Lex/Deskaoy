"""TelemetryRuntime — sole owner of OTel providers, exporters, and instruments.

All OTel SDK imports are lazy (inside ``__init__``) so that importing
``deskaoy`` never pulls in ``opentelemetry-sdk`` at module load time (HB-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opentelemetry.metrics import Meter
    from opentelemetry.trace import Tracer

_GLOBAL_RUNTIME: TelemetryRuntime | None = None

_INSTALL_MSG = (
    "Install opentelemetry-sdk: pip install deskaoy[tracing]"
)


@dataclass
class TelemetryConfig:
    """Configuration for :class:`TelemetryRuntime`."""

    service_name: str = "deskaoy"
    service_version: str = "1.1.0"
    otlp_endpoint: str | None = None  # opt-in — never defaults to a URL
    otlp_headers: dict[str, str] | None = None
    prometheus_port: int | None = None
    jsonl_path: Path | None = None
    sqlite_path: Path | None = None
    redact_patterns: tuple[str, ...] = (
        "password",
        "token",
        "key",
        "secret",
        "credential",
    )
    export_interval_ms: int = 5000
    max_queue_size: int = 2048


class TelemetryRuntime:
    """Owns all OTel providers, exporters, processors, and instruments.

    Exactly one :class:`DesktopAgentMetrics` instance is created per runtime
    and is accessible via the :attr:`metrics` property.
    """

    def __init__(self, config: TelemetryConfig) -> None:
        self._config = config

        # --- Lazy-import OTel SDK (HB-03) ---
        try:
            from opentelemetry.sdk.resources import Resource  # noqa: F401
            from opentelemetry.sdk.trace import TracerProvider as _TP  # noqa: F401
            from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: F401
        except ImportError as exc:
            raise ImportError(_INSTALL_MSG) from exc

        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version,
            }
        )

        # -- TracerProvider --
        self._tracer_provider = _TracerProvider(resource=resource)

        # Always add a simple processor so tests can swap in an
        # InMemorySpanExporter via ``add_span_processor``.
        # (No default exporter — OTLP is opt-in.)

        # OTLP exporter (only when endpoint is configured)
        if config.otlp_endpoint is not None:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            otlp_exporter = OTLPSpanExporter(
                endpoint=config.otlp_endpoint,
                headers=config.otlp_headers,
            )
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    otlp_exporter,
                    max_queue_size=config.max_queue_size,
                    schedule_delay_millis=config.export_interval_ms,
                )
            )

        # -- MeterProvider --
        from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader

        self._metric_reader = InMemoryMetricReader()
        self._meter_provider = _MeterProvider(
            metric_readers=[self._metric_reader],
            resource=resource,
        )

        # -- Instruments (exactly one instance) --
        from deskaoy.tracing.instruments import DesktopAgentMetrics

        self._metrics = DesktopAgentMetrics(self._meter_provider.get_meter(
            config.service_name, config.service_version
        ))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tracer(self) -> Tracer:
        """Return the OTel :class:`Tracer` for this runtime."""
        return self._tracer_provider.get_tracer(
            self._config.service_name,
            self._config.service_version,
        )

    def meter(self) -> Meter:
        """Return the OTel :class:`Meter` for this runtime."""
        return self._meter_provider.get_meter(
            self._config.service_name,
            self._config.service_version,
        )

    @property
    def metrics(self) -> Any:  # DesktopAgentMetrics — duck-typed to avoid import
        """The :class:`DesktopAgentMetrics` instance owned by this runtime."""
        return self._metrics

    @property
    def tracer_provider(self) -> Any:  # TracerProvider
        """Direct access to the underlying :class:`TracerProvider`."""
        return self._tracer_provider

    @property
    def metric_reader(self) -> Any:  # InMemoryMetricReader
        """Direct access to the metric reader (useful in tests)."""
        return self._metric_reader

    def shutdown(self) -> None:
        """Shut down all providers."""
        self._tracer_provider.shutdown()
        self._meter_provider.shutdown()

    def force_flush(self, timeout_ms: int = 5000) -> bool:
        """Force-flush spans and metrics.  Returns ``True`` on success."""
        trace_ok = self._tracer_provider.force_flush(timeout_millis=timeout_ms)
        import contextlib

        with contextlib.suppress(Exception):
            self._meter_provider.force_flush(timeout_millis=timeout_ms)
        return bool(trace_ok)


# ------------------------------------------------------------------
# Application-level convenience
# ------------------------------------------------------------------


def configure_telemetry(
    config: TelemetryConfig | None = None,
) -> TelemetryRuntime:
    """Create a :class:`TelemetryRuntime` and set it as the process-global default.

    Calling this multiple times returns the *same* runtime (idempotent).
    """
    global _GLOBAL_RUNTIME  # noqa: PLW0603
    if _GLOBAL_RUNTIME is not None:
        return _GLOBAL_RUNTIME
    if config is None:
        config = TelemetryConfig()
    _GLOBAL_RUNTIME = TelemetryRuntime(config)
    return _GLOBAL_RUNTIME


def get_telemetry() -> TelemetryRuntime | None:
    """Return the process-global runtime, or ``None`` if unconfigured."""
    return _GLOBAL_RUNTIME


def reset_telemetry() -> None:
    """Clear the process-global runtime (test helper)."""
    global _GLOBAL_RUNTIME  # noqa: PLW0603
    _GLOBAL_RUNTIME = None
