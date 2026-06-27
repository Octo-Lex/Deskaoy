orce_flush is delegated."""
        inner = InMemorySpanExporter()
        redacting = RedactingExporter(inner)
        assert redacting.force_flush(1000) is True

    def test_delegates_shutdown(self):
        """shutdown is delegated without error."""
        inner = InMemorySpanExporter()
        redacting = RedactingExporter(inner)
        redacting.shutdown()  # should not raise


# ===================================================================
# TEST-43-03-07  Concrete sinks emit DeprecationWarning
# ===================================================================


class TestSinkDeprecationWarnings:

    def test_console_sink_warns(self):
        """ConsoleSink.__init__ emits DeprecationWarning."""
        from deskaoy.tracing.sinks import ConsoleSink
        from deskaoy.tracing.types import SpanKind

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ConsoleSink(min_level=SpanKind.ACTION)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "ConsoleSink should emit DeprecationWarning"
            assert "ConsoleSink is deprecated" in str(dep_warnings[0].message)

    def test_file_sink_warns(self, tmp_path):
        """FileSink.__init__ emits DeprecationWarning."""
        from deskaoy.tracing.sinks import FileSink

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FileSink(tmp_path / "x.jsonl")
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "FileSink should emit DeprecationWarning"
            assert "FileSink is deprecated" in str(dep_warnings[0].message)

    def test_sqlite_sink_warns(self, tmp_path):
        """SQLiteSink.__init__ emits DeprecationWarning."""
        from deskaoy.tracing.sinks import SQLiteSink

        db = SessionDB(tmp_path / "test.db")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            SQLiteSink(db)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "SQLiteSink should emit DeprecationWarning"
            assert "SQLiteSink is deprecated" in str(dep_warnings[0].message)

    def test_prometheus_sink_warns(self):
        """PrometheusSink.__init__ emits DeprecationWarning."""
        from deskaoy.tracing.sinks import PrometheusSink

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            PrometheusSink()
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "PrometheusSink should emit DeprecationWarning"
            assert "PrometheusSink is deprecated" in str(dep_warnings[0].message)


# ===================================================================
# TEST-43-03-08  FlowLogger(sinks=) emits DeprecationWarning
# ===================================================================


class TestFlowLoggerSinksDeprecation:

    def test_sinks_param_emits_warning(self):
        """FlowLogger(sinks=[...]) emits DeprecationWarning."""
        from deskaoy.tracing.flow_logger import FlowLogger
        from deskaoy.tracing.sinks import TraceSink
        from deskaoy.tracing.types import TraceEvent

        class NoopSink(TraceSink):
            async def emit(self, event: TraceEvent) -> None:
                pass
            async def flush(self) -> None:
                pass
            async def close(self) -> None:
                pass

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FlowLogger(sinks=[NoopSink()])
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            fl_warnings = [
                x for x in dep_warnings
                if "FlowLogger" in str(x.message)
            ]
            assert len(fl_warnings) >= 1, (
                "FlowLogger(sinks=[...]) should emit DeprecationWarning"
            )
            assert "deprecated" in str(fl_warnings[0].message).lower()

    def test_no_warning_without_sinks(self):
        """FlowLogger() without sinks does NOT emit warning."""
        from deskaoy.tracing.flow_logger import FlowLogger

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FlowLogger()
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) == 0, (
                f"FlowLogger() without sinks should not warn, got: {dep_warnings}"
            )


# ===================================================================
# TEST-43-03-09  No import-time deprecation warnings
# ===================================================================


class TestNoImportTimeWarnings:

    def test_no_warnings_on_import(self):
        """Importing sinks module does not emit deprecation warnings."""
        import importlib

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Re-import the module (forces fresh module-level execution).
            import deskaoy.tracing.sinks as sinks_mod
            importlib.reload(sinks_mod)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) == 0, (
                f"No import-time warnings expected, got: {dep_warnings}"
            )


# ===================================================================
# TEST-43-03-10  Runtime + JSONL integration
# ===================================================================


class TestRuntimeJSONLIntegration:

    def test_spans_in_jsonl_file(self, tmp_path):
        """Spans appear in JSONL file when wired via TelemetryRuntime."""
        jsonl_path = tmp_path / "trace.jsonl"
        jsonl_exporter = JSONLExporter(jsonl_path)

        cfg = TelemetryConfig()
        rt = TelemetryRuntime(cfg)
        rt.tracer_provider.add_span_processor(
            SimpleSpanProcessor(jsonl_exporter)
        )

        tracer = rt.tracer()
        with tracer.start_as_current_span("integration.test") as span:
            span.set_attribute("test_key", "test_value")

        rt.force_flush(timeout_ms=5000)
        jsonl_exporter.shutdown()

        assert jsonl_path.exists()
        lines = [
            l for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            if l.strip()
        ]
        assert len(lines) >= 1, f"Expected >= 1 line in JSONL, got {len(lines)}"
        parsed = json.loads(lines[0])
        assert "name" in parsed


# ===================================================================
# TEST-43-03-11  Runtime + SQLite integration
# ===================================================================


class TestRuntimeSQLiteIntegration:

    def test_spans_in_session_db(self, tmp_path):
        """Spans appear in SessionDB when wired via TelemetryRuntime."""
        db_path = tmp_path / "test.db"
        sqlite_exporter = SQLiteExporter(db_path, batch_size=1, max_queue=128)

        cfg = TelemetryConfig()
        rt = TelemetryRuntime(cfg)
        rt.tracer_provider.add_span_processor(
            SimpleSpanProcessor(sqlite_exporter)
        )

        tracer = rt.tracer()
        with tracer.start_as_current_span("integration.sqlite") as span:
            span.set_attribute("test_key", "test_value")

        rt.force_flush(timeout_ms=5000)
        sqlite_exporter.force_flush(5000)
        sqlite_exporter.shutdown()

        conn = sqlite3.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
            assert count >= 1, f"Expected >= 1 event in SessionDB, got {count}"
        finally:
            conn.close()
