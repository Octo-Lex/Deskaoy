"""DesktopAgentMetrics — cached OTel metric instruments.

All instruments live under the ``deskaoy.*`` namespace.
No code outside this class should call ``meter.create_*`` directly
(AUTH-01).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.metrics import Meter


class DesktopAgentMetrics:
    """Cached OTel metric instruments under ``deskaoy.*`` namespace.

    Exactly one instance is created per :class:`TelemetryRuntime`.
    """

    def __init__(self, meter: Meter) -> None:
        self._cdp_calls = meter.create_counter(
            "deskaoy.cdp.calls",
            description="Total CDP calls",
            unit="1",
        )
        self._cdp_duration = meter.create_histogram(
            "deskaoy.cdp.duration",
            description="CDP call duration",
            unit="ms",
        )
        self._llm_tokens = meter.create_counter(
            "deskaoy.llm.tokens",
            description="LLM tokens used",
            unit="1",
        )
        self._actions = meter.create_counter(
            "deskaoy.actions",
            description="Actions executed",
            unit="1",
        )
        self._errors = meter.create_counter(
            "deskaoy.errors",
            description="Errors by category",
            unit="1",
        )
        self._active_sessions = meter.create_up_down_counter(
            "deskaoy.sessions.active",
            description="Currently active sessions",
            unit="1",
        )

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_cdp_call(self, method: str, duration_ms: float) -> None:
        """Record one CDP call."""
        self._cdp_calls.add(1, {"method": method})
        self._cdp_duration.record(duration_ms, {"method": method})

    def record_llm_tokens(self, model: str, count: int) -> None:
        """Record LLM token consumption."""
        self._llm_tokens.add(count, {"model": model})

    def record_action(self, tier: str) -> None:
        """Record an action by tier."""
        self._actions.add(1, {"tier": tier})

    def record_error(self, category: str) -> None:
        """Record an error by category."""
        self._errors.add(1, {"category": category})

    def session_started(self) -> None:
        """Increment the active-session gauge."""
        self._active_sessions.add(1)

    def session_ended(self) -> None:
        """Decrement the active-session gauge."""
        self._active_sessions.add(-1)
