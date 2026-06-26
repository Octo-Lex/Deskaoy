"""Final integration tests for v1.0 Release Candidate (BATCH-15)."""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Release readiness tests require full project checkout with docs, LICENSE, etc.
pytestmark = pytest.mark.skipif(
    not (PROJECT_ROOT / "LICENSE").exists(),
    reason="Full project checkout required (LICENSE, CONTRIBUTING.md, docs/)",
)


class TestVersionConsistency:
    """Verify version is single-sourced correctly."""

    def test_cli_version_matches_pyproject(self):
        from deskaoy.cli.version import VERSION
        import tomllib
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
            pyproject_ver = tomllib.load(f)["project"]["version"]
        assert VERSION == pyproject_ver, f"cli={VERSION} != pyproject={pyproject_ver}"

    def test_agent_version_matches_pyproject(self):
        import tomllib
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
            pyproject_ver = tomllib.load(f)["project"]["version"]
        from deskaoy.desktop_agent import DesktopAgent
        da_ver = DesktopAgent.version
        assert da_ver == pyproject_ver, f"agent={da_ver} != pyproject={pyproject_ver}"


class TestEssentialFiles:
    """Verify all essential project files exist."""

    @pytest.mark.parametrize("fname", [
        "LICENSE",
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "pyproject.toml",
    ])
    def test_file_exists(self, fname):
        assert (PROJECT_ROOT / fname).exists(), f"{fname} missing"


class TestModuleImports:
    """Verify all key modules are importable."""

    MODULES = [
        "deskaoy.desktop_agent",
        "deskaoy.cascade.protocol",
        "deskaoy.cascade.differ",
        "deskaoy.cascade.formatter",
        "deskaoy.cascade.types",
        "deskaoy.safety.key_blocklist",
        "deskaoy.safety.sensitive_apps",
        "deskaoy.safety.health",
        "deskaoy.safety.rate_governor",
        "deskaoy.safety.cost_tracker",
        "deskaoy.safety.latency_budget",
        "deskaoy.safety.timeout_guard",
        "deskaoy.agent.two_step",
        "deskaoy.agent.cua_loop",
        "deskaoy.agent.loop",
        "deskaoy.agent.types",
        "deskaoy.orchestration.blocks",
        "deskaoy.orchestration.workflow",
        "deskaoy.evaluation",
        "deskaoy.guides",
        "deskaoy.performance",
        "deskaoy.adapters.windows",
        "deskaoy.adapters.environment",
        "deskaoy.results.types",
        "deskaoy.input.bezier",
        "deskaoy.input.jitter",
        "deskaoy.input.types",
        "deskaoy.memory.store",
        "deskaoy.memory.types",
        "deskaoy.cli.main",
        "deskaoy.cli.version",
    ]

    @pytest.mark.parametrize("module", MODULES)
    def test_import(self, module):
        mod = importlib.import_module(module)
        assert mod is not None


class TestCLICommands:
    """Verify CLI commands work."""

    def test_version_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "deskaoy.cli.main", "version"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "." in result.stdout  # Contains version number

    def test_help_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "deskaoy.cli.main", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "execute" in result.stdout

    def test_doctor_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "deskaoy.cli.main", "doctor"],
            capture_output=True, text=True, timeout=30,
        )
        # Doctor returns 0 if all pass, 1 if some fail (e.g., missing comtypes)
        # We just check it runs without crashing
        assert "Python" in result.stdout


class TestSafetySystem:
    """Verify safety system is fully operational."""

    def test_all_blocked_keys(self):
        from deskaoy.safety.key_blocklist import BLOCKED_KEYS, is_blocked_key
        assert len(BLOCKED_KEYS) >= 12
        for key in BLOCKED_KEYS:
            assert is_blocked_key(key) is True

    def test_sensitive_app_categories(self):
        from deskaoy.safety.sensitive_apps import SENSITIVE_APPS
        assert len(SENSITIVE_APPS) >= 14

    def test_health_check_structure(self):
        from deskaoy.safety.health import HealthCheck
        import asyncio
        from unittest.mock import MagicMock

        agent = MagicMock()
        agent._surface = None
        agent._llm = None
        agent._policy_bridge = None
        agent._storage_resolver = None
        agent._recovery_bridge = None

        checker = HealthCheck(agent)
        status = asyncio.run(checker.check())
        assert len(status.checks) == 14  # 9 original + 4 service + 1 macos_adapter (BATCH-33) (BATCH-26)
        assert "key_blocklist" in status.checks
        assert "sensitive_apps" in status.checks
        assert "menu_service" in status.checks
        assert "taskbar_service" in status.checks
        assert "dialog_service" in status.checks
        assert "desktop_service" in status.checks


class TestSurfaceAdapterProtocol:
    """Verify SurfaceAdapter protocol compliance."""

    def test_windows_adapter_has_required_methods(self):
        from deskaoy.adapters.windows import WindowsAdapter
        from deskaoy.cascade.protocol import SurfaceAdapter

        adapter = WindowsAdapter(hwnd=1)
        # Check it's a SurfaceAdapter subclass
        assert isinstance(adapter, SurfaceAdapter)

        # Check required methods exist
        required = [
            "click", "fill", "type_text", "key_press", "scroll",
            "screenshot", "snapshot", "hover", "wait_for_selector",
            "evaluate", "current_url", "current_title",
        ]
        for method in required:
            assert hasattr(adapter, method), f"Missing method: {method}"

    def test_key_press_checks_blocklist(self):
        """Verify key_press method checks the blocklist."""
        from deskaoy.adapters.windows import WindowsAdapter
        from unittest.mock import MagicMock
        import asyncio

        adapter = WindowsAdapter(hwnd=1)
        adapter._win32gui = MagicMock()
        adapter._win32api = MagicMock()
        adapter._win32con = MagicMock()
        adapter._pyautogui = MagicMock()

        result = asyncio.run(adapter.key_press("f4", modifiers=1))  # Alt+F4
        assert result.ok is False
        assert result.error is not None
        assert "Blocked" in str(result.error) or "SECURITY" in str(result.error.category)


class TestDocumentationExists:
    """Verify all documentation files exist."""

    @pytest.mark.parametrize("doc_path", [
        "docs/api/REFERENCE.md",
        "docs/guides/QUICKSTART.md",
        "docs/guides/ARCHITECTURE.md",
        "docs/guides/ADAPTER_DEV.md",
    ])
    def test_doc_exists(self, doc_path):
        path = PROJECT_ROOT / doc_path
        assert path.exists(), f"Missing doc: {doc_path}"
        assert path.stat().st_size > 100, f"Doc too small: {doc_path}"


class TestEvaluationFramework:
    """Verify evaluation framework works end-to-end."""

    def test_benchmark_runner_loads_tasks(self):
        from deskaoy.evaluation import BenchmarkRunner, TaskDefinition
        runner = BenchmarkRunner(name="test")
        # Verify the runner exists and has the expected API
        assert runner.name == "test"
        assert hasattr(runner, "run_task")
        # Create a task and run it
        task = TaskDefinition(id="test-1", instruction="test", evaluator={"type": "always_pass"})
        result = runner.run_task(task)
        assert result.task_id == "test-1"


class TestPerfModule:
    """Verify performance module works end-to-end."""

    def test_benchmark_suite_runs(self):
        from deskaoy.performance import BenchmarkSuite
        suite = BenchmarkSuite()
        suite.add("add", lambda: 1 + 1, iterations=10, target_ms=1.0)
        results = suite.run()
        assert len(results) == 1
        assert results[0].passed is True

    def test_lru_cache_basic(self):
        from deskaoy.performance import LRUCache
        cache = LRUCache(max_size=5)
        cache.put("a", 1)
        assert cache.get("a") == 1
        assert cache.hit_rate == 1.0
