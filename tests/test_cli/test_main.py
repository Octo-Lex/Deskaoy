"""Tests for CLI main (T01-01 through T01-20, T01-31, T01-32)."""
from __future__ import annotations

import json
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from deskaoy.os_types import (
    AgentResult,
    AgentEstimate,
    ResultStatus,
    Confidence,
)
from deskaoy.cli.main import (
    main,
    _build_parser,
    _get_agent,
    _reset_agent,
    _resolve_storage_dir,
    _VERSION,
)


# ---------------------------------------------------------------------------
# Mock agent factory
# ---------------------------------------------------------------------------

def _mock_agent(**overrides):
    """Create a mock DesktopAgent with sensible defaults."""
    agent = MagicMock()

    # execute() returns AgentResult
    default_result = AgentResult(
        execution_id="test-exec",
        status=ResultStatus.SUCCESS,
        summary="Mocked success",
        confidence=Confidence(score=0.95, reason="test"),
    )
    execute_mock = AsyncMock(return_value=default_result)
    agent.execute = execute_mock

    # estimate() returns AgentEstimate
    default_estimate = AgentEstimate(
        cost_usd=0.001,
        latency_ms=500,
        confidence=Confidence(score=0.9, reason="test"),
        requires_auth=False,
        can_execute=True,
    )
    estimate_mock = AsyncMock(return_value=default_estimate)
    agent.estimate = estimate_mock

    # health() returns mock status
    health_status = MagicMock()
    health_status.healthy = True
    health_status.message = "OK"
    health_status.probes = {"adapter": True, "llm": True}
    health_mock = AsyncMock(return_value=health_status)
    agent.health = health_mock

    # schema() returns dict
    agent.schema.return_value = {
        "capabilities": {
            "automate": {"action_class": "sensitive", "methods": ["click", "type"]}
        }
    }

    # Subsystems
    agent.routine_scheduler = MagicMock()
    agent.routine_scheduler.list.return_value = []
    agent.routine_scheduler.add = MagicMock()
    agent.routine_scheduler.remove.return_value = True

    agent.skill_loader = MagicMock()
    agent.skill_loader.discover.return_value = []

    agent.fact_store = MagicMock()
    agent.fact_store.get_facts.return_value = []

    agent.configure_session = MagicMock()
    agent.terminate_session = MagicMock()

    # Apply overrides
    for k, v in overrides.items():
        setattr(agent, k, v)

    return agent


# ---------------------------------------------------------------------------
# T01-01: execute parses instruction string
# ---------------------------------------------------------------------------

class TestExecuteParsing:

    def test_parses_instruction(self):
        parser = _build_parser()
        args = parser.parse_args(["execute", "click the OK button"])
        assert args.instruction == "click the OK button"
        assert args.command == "execute"


# ---------------------------------------------------------------------------
# T01-02: execute --dry-run sets dry_run=True
# ---------------------------------------------------------------------------

    def test_dry_run_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["execute", "--dry-run", "click OK"])
        assert args.dry_run is True


# ---------------------------------------------------------------------------
# T01-03: execute --json sets json_mode
# ---------------------------------------------------------------------------

    def test_json_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--json", "execute", "click OK"])
        assert args.json is True


# ---------------------------------------------------------------------------
# T01-04: execute --timeout passes value
# ---------------------------------------------------------------------------

    def test_timeout_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--timeout", "30", "execute", "click OK"])
        assert args.timeout == 30


# ---------------------------------------------------------------------------
# T01-05: execute with mocked agent returns success
# ---------------------------------------------------------------------------

class TestExecuteDispatch:

    def test_success_exit_code(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["execute", "click OK"])
        assert code == 0
        out = capsys.readouterr().out
        assert "SUCCESS" in out


# ---------------------------------------------------------------------------
# T01-06: execute with failure exits 1
# ---------------------------------------------------------------------------

    def test_failure_exit_code(self, capsys):
        agent = _mock_agent()
        fail_result = AgentResult(
            execution_id="test-exec",
            status=ResultStatus.FAILURE,
            summary="Element not found",
            confidence=Confidence(score=0.1, reason="fail"),
        )
        agent.execute = AsyncMock(return_value=fail_result)
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["execute", "find missing element"])
        assert code == 1


# ---------------------------------------------------------------------------
# T01-07: estimate calls agent.estimate()
# ---------------------------------------------------------------------------

class TestEstimate:

    def test_estimate_dispatch(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["estimate", "open notepad"])
        assert code == 0
        out = capsys.readouterr().out
        assert "ESTIMATE" in out
        agent.estimate.assert_called_once()


# ---------------------------------------------------------------------------
# T01-08 through T01-11: schedule subcommands
# ---------------------------------------------------------------------------

class TestSchedule:

    def test_add(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["schedule", "add", "--name", "daily", "--cron", "0 8 * * *", "--prompt", "hello"])
        assert code == 0
        out = capsys.readouterr().out
        assert "daily" in out
        agent.routine_scheduler.add.assert_called_once()

    def test_list(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["schedule", "list"])
        assert code == 0

    def test_remove(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["schedule", "remove", "--name", "daily"])
        assert code == 0
        out = capsys.readouterr().out
        assert "daily" in out

    def test_remove_not_found(self, capsys):
        agent = _mock_agent()
        agent.routine_scheduler.remove.return_value = False
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["schedule", "remove", "--name", "nonexist"])
        assert code == 1

    def test_due(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["schedule", "due"])
        assert code == 0


# ---------------------------------------------------------------------------
# T01-12, T01-13: skills subcommands
# ---------------------------------------------------------------------------

class TestSkills:

    def test_list(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["skills", "list"])
        assert code == 0

    def test_match(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["skills", "match", "type text"])
        assert code == 0


# ---------------------------------------------------------------------------
# T01-14, T01-15: facts subcommands
# ---------------------------------------------------------------------------

class TestFacts:

    def test_list(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["facts", "list"])
        assert code == 0

    def test_search(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["facts", "search", "email"])
        assert code == 0


# ---------------------------------------------------------------------------
# T01-16: health
# ---------------------------------------------------------------------------

class TestHealth:

    def test_health_healthy(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["health"])
        assert code == 0
        out = capsys.readouterr().out
        assert "HEALTHY" in out

    def test_health_unhealthy(self, capsys):
        agent = _mock_agent()
        health_status = MagicMock()
        health_status.healthy = False
        health_status.message = "FAIL"
        health_status.probes = {"adapter": False}
        agent.health = AsyncMock(return_value=health_status)
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["health"])
        assert code == 1


# ---------------------------------------------------------------------------
# T01-17: schema
# ---------------------------------------------------------------------------

class TestSchema:

    def test_schema_output(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["schema"])
        assert code == 0
        out = capsys.readouterr().out
        assert "automate" in out


# ---------------------------------------------------------------------------
# T01-18: version
# ---------------------------------------------------------------------------

class TestVersion:

    def test_version_output(self, capsys):
        code = main(["version"])
        assert code == 0
        out = capsys.readouterr().out
        assert "deskaoy" in out
        # Should contain version-like string
        assert any(c.isdigit() for c in out)


# ---------------------------------------------------------------------------
# T01-19: unknown subcommand
# ---------------------------------------------------------------------------

class TestUnknownCommand:

    def test_unknown_exits_nonzero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["nonexistent_command"])
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# T01-20: --storage-dir
# ---------------------------------------------------------------------------

class TestStorageDir:

    def test_storage_dir_passed(self):
        parser = _build_parser()
        args = parser.parse_args(["--storage-dir", "/tmp/test", "version"])
        assert args.storage_dir == "/tmp/test"

    def test_default_storage_dir(self):
        sd = _resolve_storage_dir()
        # StorageResolver delegates to ~/.deskaoy-dev (dev mode) or
        # $AIOS_HOME/capabilities/aios.first_party.deskaoy (production).
        assert "deskaoy" in sd.lower()

    def test_env_storage_dir(self):
        import os
        with patch.dict(os.environ, {"AIOS_HOME": "/custom/aios"}):
            sd = _resolve_storage_dir()
        # Now delegates to StorageResolver: $AIOS_HOME/capabilities/<capability_id>
        assert sd.replace("\\", "/") == "/custom/aios/capabilities/aios.first_party.deskaoy"


# ---------------------------------------------------------------------------
# T01-31: REPL KeyboardInterrupt → terminate_session (tested in test_repl.py)
# T01-32: execute --session passes ID
# ---------------------------------------------------------------------------

class TestSessionFlag:

    def test_session_id_passed(self):
        agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["--session", "my-session-123", "execute", "click OK"])
        assert code == 0
        # Verify the context had the right session_id
        call_args = agent.execute.call_args
        ctx = call_args[0][1]  # second positional arg
        assert ctx.session_id == "my-session-123"


# ---------------------------------------------------------------------------
# No command → help (exit 0)
# ---------------------------------------------------------------------------

class TestNoCommand:

    def test_no_command_shows_help(self, capsys):
        code = main([])
        assert code == 0
