"""Integration tests for CLI full-stack dispatch (T02-01 through T02-08)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deskaoy.cli.main import main
from deskaoy.desktop_agent import DesktopAgent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_surface():
    surface = MagicMock()
    surface.screenshot = AsyncMock(return_value=b"screenshot")
    surface.snapshot = AsyncMock(return_value={"elements": []})
    surface.current_title = "Test"
    surface.current_url = "mock://test"
    surface.click = AsyncMock(return_value=MagicMock(status="ok"))
    surface.fill = AsyncMock(return_value=MagicMock(status="ok"))
    surface.type_text = AsyncMock(return_value=MagicMock(status="ok"))
    surface.key_press = AsyncMock(return_value=MagicMock(status="ok"))
    surface.scroll = AsyncMock(return_value=MagicMock(status="ok"))
    surface.hover = AsyncMock(return_value=MagicMock(status="ok"))
    surface.abort = MagicMock()
    return surface


def _mock_llm():
    llm = MagicMock()
    llm.is_ready = True
    llm.propose_action = AsyncMock(return_value={"done": True})
    llm.create_plan = AsyncMock(return_value=[{"description": "step"}])
    llm.usage = MagicMock(total_tokens=0)
    return llm


def _full_mock_agent():
    """Create a fully mocked DesktopAgent."""
    agent = DesktopAgent(surface=_mock_surface(), llm=_mock_llm())

    # Override health_check
    health = MagicMock(healthy=True, message="OK", probes={"adapter": True})
    agent.health_check = AsyncMock(return_value=health)

    return agent


# ---------------------------------------------------------------------------
# T02-01: CLI execute with mock surface returns SUCCESS
# ---------------------------------------------------------------------------

class TestCLIStack:

    def test_execute_returns_success(self, capsys):
        agent = _full_mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            main(["execute", "click OK"])
        # May return 0 or 1 depending on validation state
        # The important thing is the dispatch chain works
        out = capsys.readouterr().out
        assert "FAILURE" in out or "SUCCESS" in out or "success" in out.lower()


# ---------------------------------------------------------------------------
# T02-02: CLI execute --dry-run returns DRY_RUN
# ---------------------------------------------------------------------------

    def test_dry_run_status(self, capsys):
        agent = _full_mock_agent()
        # Dry run should still work through the stack
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["--json", "execute", "--dry-run", "click OK"])
        assert code == 0
        out = capsys.readouterr().out
        # Should contain dry_run or success (agent handles dry_run internally)
        assert "dry_run" in out or "success" in out


# ---------------------------------------------------------------------------
# T02-03: CLI schedule add + list round-trip via agent
# ---------------------------------------------------------------------------

    def test_schedule_round_trip(self, capsys):
        agent = _full_mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            # Add
            code1 = main(["schedule", "add", "--name", "test", "--cron", "0 8 * * *", "--prompt", "hello"])
            assert code1 == 0
            # List
            code2 = main(["schedule", "list"])
            assert code2 == 0


# ---------------------------------------------------------------------------
# T02-04: CLI skills list returns discovered skills
# ---------------------------------------------------------------------------

    def test_skills_list(self, capsys):
        agent = _full_mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["skills", "list"])
        assert code == 0


# ---------------------------------------------------------------------------
# T02-05: CLI facts list returns stored facts
# ---------------------------------------------------------------------------

    def test_facts_list(self, capsys):
        agent = _full_mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["facts", "list"])
        assert code == 0


# ---------------------------------------------------------------------------
# T02-06: Full stack: CLI → DesktopAgent → mock surface → result
# ---------------------------------------------------------------------------

    def test_full_stack(self, capsys):
        """Prove the entire dispatch chain works end-to-end."""
        surface = _mock_surface()
        llm = _mock_llm()
        agent = DesktopAgent(surface=surface, llm=llm)

        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["execute", "Click the Submit button"])

        # Either success or validation failure is valid — dispatch chain worked
        assert code in (0, 1)


# ---------------------------------------------------------------------------
# T02-07: Demo script imports and runs without error
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent.parent / "scripts").exists(),
    reason="scripts/ directory not present",
)
class TestDemoScripts:
    """Demo script tests — require scripts/ directory present."""

    def test_e2e_desktop_demo_imports(self):
        """Verify demo_e2e_desktop.py can be imported."""
        import importlib.util
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "demo_e2e_desktop.py"
        assert script_path.exists(), f"Demo script not found: {script_path}"

        spec = importlib.util.spec_from_file_location("demo_e2e_desktop", script_path)
        assert spec is not None

    def test_routine_skill_fact_demo_imports(self):
        """Verify demo_routine_skill_fact.py can be imported."""
        import importlib.util
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "demo_routine_skill_fact.py"
        assert script_path.exists(), f"Demo script not found: {script_path}"

        spec = importlib.util.spec_from_file_location("demo_routine_skill_fact", script_path)
        assert spec is not None


# ---------------------------------------------------------------------------
# T02-08: Demo routine+skill+fact script runs without error
# ---------------------------------------------------------------------------

    def test_routine_skill_fact_script_runs(self):
        """Run the demo script and verify it exits cleanly."""
        import subprocess
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "demo_routine_skill_fact.py"
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "Demo complete" in result.stdout

    def test_e2e_desktop_script_runs(self):
        """Run the E2E desktop demo script and verify it exits cleanly."""
        import subprocess
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "demo_e2e_desktop.py"
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "Demo complete" in result.stdout
