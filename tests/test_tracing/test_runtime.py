===================================================================
# TEST-43-01-04  configure_telemetry sets global runtime
# ===================================================================

class TestConfigureTelemetry:

    def setup_method(self):
        from deskaoy.tracing.runtime import reset_telemetry
        reset_telemetry()

    def teardown_method(self):
        from deskaoy.tracing.runtime import reset_telemetry
        reset_telemetry()

    def test_second_call_returns_same_runtime(self):
        from deskaoy.tracing.runtime import configure_telemetry

        rt1 = configure_telemetry()
        rt2 = configure_telemetry()
        assert rt1 is rt2

    def test_global_runtime_accessible(self):
        from deskaoy.tracing.runtime import configure_telemetry, get_telemetry

        rt = configure_telemetry()
        assert get_telemetry() is rt


# ===================================================================
# TEST-43-01-05  ImportError when OTel SDK missing
# ===================================================================

class TestImportError:

    def test_import_error_message(self):
        from deskaoy.tracing.runtime import TelemetryConfig, TelemetryRuntime

        with mock.patch.dict(sys.modules, raise_on_missing=True):
            # Force the import to fail by removing the module if present
            # and blocking re-import
            blocked = "opentelemetry.sdk.resources"
            original = sys.modules.pop(blocked, None)
            try:

                def _import_hook(name, *args, **kwargs):
                    if name == "opentelemetry.sdk.resources":
                        raise ImportError("nope")
                    return original_import(name, *args, **kwargs)

                original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

                with mock.patch("builtins.__import__", _import_hook), pytest.raises(ImportError, match="pip install deskaoy\\[tracing\\]"):
                    TelemetryRuntime(TelemetryConfig())
            finally:
                if original is not None:
                    sys.modules[blocked] = original


# ===================================================================
# TEST-43-01-06  OTLP exporter added when endpoint set
# ===================================================================

class TestOTLPExporter:

    def test_otlp_exporter_in_processor_chain(self):
        from deskaoy.tracing.runtime import TelemetryConfig, TelemetryRuntime

        rt = TelemetryRuntime(TelemetryConfig(otlp_endpoint="http://localhost:4317"))
        # Inspect the active span processors on the tracer provider
        provider = rt.tracer_provider
        # The provider has a _active_span_processor (or _span_processor)
        # which is a composite containing all added processors.
        # We look for any processor that wraps an OTLPSpanExporter.
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Access the internal span processor list
        spp = getattr(provider, "_active_span_processor", None)
        assert spp is not None

        # _active_span_processor is a _SpanProcessorComposite
        processors = getattr(spp, "_span_processors", [])
        has_otlp = any(
            isinstance(p, BatchSpanProcessor) for p in processors
        )
        assert has_otlp, f"No BatchSpanProcessor found among {processors}"


# ===================================================================
# TEST-43-01-07  OTLP NOT added when endpoint is None
# ===================================================================

class TestNoOTLP:

    def test_no_otlp_when_endpoint_none(self):
        from deskaoy.tracing.runtime import TelemetryConfig, TelemetryRuntime

        rt = TelemetryRuntime(TelemetryConfig(otlp_endpoint=None))
        provider = rt.tracer_provider
        spp = getattr(provider, "_active_span_processor", None)
        if spp is not None:
            processors = getattr(spp, "_span_processors", [])
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            has_otlp = any(
                isinstance(p, BatchSpanProcessor) for p in processors
            )
            assert not has_otlp, (
                f"BatchSpanProcessor should not be present when otlp_endpoint=None, "
                f"found {processors}"
            )

# ===================================================================
# TEST-43-04-01  Runtime exposes metrics property
# ===================================================================

class TestMetricsProperty:

    def test_metrics_returns_desktop_agent_metrics(self):
        from deskaoy.tracing.instruments import DesktopAgentMetrics

        rt, _ = _make_runtime()
        assert isinstance(rt.metrics, DesktopAgentMetrics)

    def test_metrics_identity_stable(self):
        """Same object returned every call."""
        rt, _ = _make_runtime()
        assert rt.metrics is rt.metrics


# ===================================================================
# TEST-43-04-02  Metrics recorded through runtime
# ===================================================================

class TestMetricsRecorded:

    def test_cdp_call_records_values(self):
        rt, _ = _make_runtime()
        rt.metrics.record_cdp_call("Runtime.evaluate", 12.5)
        rt.metrics.record_cdp_call("Runtime.evaluate", 7.3)

        # Force-flush metrics so the reader picks them up
        rt.force_flush(timeout_ms=2000)

        # Read collected metrics from the InMemoryMetricReader
        metrics_data = rt.metric_reader.get_metrics_data()
        resource_metrics = metrics_data.resource_metrics
        assert len(resource_metrics) > 0

        # Collect all metric names
        names: list[str] = []
        for rm in resource_metrics:
            for sm in rm.scope_metrics:
                for metric in sm.metrics:
                    names.append(metric.name)

        assert "deskaoy.cdp.calls" in names
        assert "deskaoy.cdp.duration" in names


# ===================================================================
# TEST-43-04-03  pyproject.toml has tracing extras
# ===================================================================

class TestPyprojectTracingExtras:

    def test_tracing_extras_exist(self):
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        opt = data["project"]["optional-dependencies"]

        # [tracing] must exist with opentelemetry-api and opentelemetry-sdk
        assert "tracing" in opt
        tracing_pkgs = opt["tracing"]
        assert any("opentelemetry-api" in p for p in tracing_pkgs)
        assert any("opentelemetry-sdk" in p for p in tracing_pkgs)

        # [tracing-otlp] must depend on [tracing] + OTLP exporter
        assert "tracing-otlp" in opt
        otlp_pkgs = opt["tracing-otlp"]
        assert any("deskaoy[tracing]" in p for p in otlp_pkgs)
        assert any("opentelemetry-exporter-otlp-proto-grpc" in p for p in otlp_pkgs)

        # [tracing-prometheus] must depend on [tracing] + prometheus exporter
        assert "tracing-prometheus" in opt
        prom_pkgs = opt["tracing-prometheus"]
        assert any("deskaoy[tracing]" in p for p in prom_pkgs)
        assert any("opentelemetry-exporter-prometheus" in p for p in prom_pkgs)

    def test_prometheus_not_core_dependency(self):
        """AC-04-04: opentelemetry-exporter-prometheus is NOT a core dependency."""
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        core_deps = data["project"].get("dependencies", [])
        assert not any(
            "opentelemetry-exporter-prometheus" in d for d in core_deps
        )
