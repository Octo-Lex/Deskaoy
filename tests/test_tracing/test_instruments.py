"""Tests for DesktopAgentMetrics (BATCH-43 / TASK-01).

TEST-43-01-08 through TEST-43-01-10.
"""

from __future__ import annotations

import pytest

from deskaoy.tracing.runtime import TelemetryConfig, TelemetryRuntime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime() -> TelemetryRuntime:
    return TelemetryRuntime(TelemetryConfig())


# ===================================================================
# TEST-43-01-08  DesktopAgentMetrics creates instruments
# ===================================================================

class TestInstrumentsCreated:

    def test_record_cdp_call_increments(self):
        rt = _make_runtime()
        metrics = rt.metrics

        # record_cdp_call should not raise
        metrics.record_cdp_call("Page.navigate", 42.5)

        # Verify via metric reader
        reader = rt.metric_reader
        metrics_data = reader.get_metrics_data()
        # At least one metric point exists for cdp.calls
        found = False
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    if metric.name == "deskaoy.cdp.calls":
                        found = True
                        # Check data points
                        for dp in metric.data.data_points:
                            assert dp.value >= 1
        assert found, "deskaoy.cdp.calls metric not found"

    def test_record_llm_tokens_increments(self):
        rt = _make_runtime()
        metrics = rt.metrics
        metrics.record_llm_tokens("gpt-4o", 150)

        reader = rt.metric_reader
        metrics_data = reader.get_metrics_data()
        found = False
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    if metric.name == "deskaoy.llm.tokens":
                        found = True
        assert found, "deskaoy.llm.tokens metric not found"

    def test_record_action_increments(self):
        rt = _make_runtime()
        metrics = rt.metrics
        metrics.record_action("browser")
        # Should not raise

    def test_record_error_increments(self):
        rt = _make_runtime()
        metrics = rt.metrics
        metrics.record_error("timeout")
        # Should not raise


# ===================================================================
# TEST-43-01-09  DesktopAgentMetrics session lifecycle
# ===================================================================

class TestSessionLifecycle:

    def test_session_started_plus_ended_net_zero(self):
        rt = _make_runtime()
        metrics = rt.metrics

        metrics.session_started()
        metrics.session_ended()

        reader = rt.metric_reader
        metrics_data = reader.get_metrics_data()

        # Find the active sessions metric — net delta should be 0
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    if metric.name == "deskaoy.sessions.active":
                        # Sum of all data points should be 0 (started=+1, ended=-1)
                        total = sum(dp.value for dp in metric.data.data_points)
                        assert total == 0, (
                            f"Expected net 0 active sessions, got {total}"
                        )
                        return

        pytest.fail("deskaoy.sessions.active metric not found")


# ===================================================================
# TEST-43-01-10  One DesktopAgentMetrics per runtime
# ===================================================================

class TestSingletonMetrics:

    def test_same_object_identity(self):
        rt = _make_runtime()
        m1 = rt.metrics
        m2 = rt.metrics
        assert m1 is m2, "metrics property should return the same object"

    def test_different_runtimes_different_metrics(self):
        rt1 = _make_runtime()
        rt2 = _make_runtime()
        assert rt1.metrics is not rt2.metrics, (
            "Different runtimes must have different DesktopAgentMetrics instances"
        )
