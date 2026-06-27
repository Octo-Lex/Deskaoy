"""Tests for ScriptRunner — BATCH-29 TASK-02.

Covers:
  - Script validation (valid, missing steps, unknown action, bad types)
  - load_script (file not found, invalid JSON, valid)
  - Dry-run mode
  - Sequential execution (all pass, stop on failure)
  - Step action mapping
  - ScriptResult success_rate
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deskaoy.agent.script_runner import (
    ScriptResult,
    ScriptRunner,
    ScriptValidationError,
    load_script,
    validate_script,
)
from deskaoy.os_types import AgentResult, Confidence, ResultStatus

# ---------------------------------------------------------------------------
# Mock agent
# ---------------------------------------------------------------------------

def _mock_agent() -> MagicMock:
    agent = MagicMock()
    result = AgentResult(
        execution_id="test",
        status=ResultStatus.SUCCESS,
        summary="step ok",
        confidence=Confidence(score=0.9, reason="test"),
    )
    agent.execute = AsyncMock(return_value=result)
    return agent


def _write_script(data: dict, tmpdir: Path) -> Path:
    """Write a script dict to a temp file."""
    p = tmpdir / "test.deskaoy.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# T29-11: validate_script — valid scripts
# ---------------------------------------------------------------------------

class TestValidateScriptValid:

    def test_valid_minimal_script(self):
        errors = validate_script({
            "steps": [
                {"action": "click", "target": "OK"},
            ]
        })
        assert errors == []

    def test_valid_full_script(self):
        errors = validate_script({
            "name": "Test Script",
            "steps": [
                {"action": "click", "target": "OK button"},
                {"action": "type", "value": "Hello"},
                {"action": "snapshot"},
                {"action": "screenshot"},
            ]
        })
        assert errors == []


# ---------------------------------------------------------------------------
# T29-12: validate_script — missing/invalid steps
# ---------------------------------------------------------------------------

class TestValidateScriptErrors:

    def test_missing_steps(self):
        errors = validate_script({"name": "No steps"})
        assert any("'steps' is required" in e for e in errors)

    def test_empty_steps(self):
        errors = validate_script({"steps": []})
        assert any("must not be empty" in e for e in errors)

    def test_steps_not_list(self):
        errors = validate_script({"steps": "not a list"})
        assert any("must be an array" in e for e in errors)

    def test_step_missing_action(self):
        errors = validate_script({"steps": [{"target": "OK"}]})
        assert any("'action' is required" in e for e in errors)

    def test_step_unknown_action(self):
        errors = validate_script({"steps": [{"action": "foobar"}]})
        assert any("unknown action" in e for e in errors)

    def test_step_bad_target_type(self):
        errors = validate_script({"steps": [{"action": "click", "target": 123}]})
        assert any("'target' must be a string" in e for e in errors)

    def test_not_a_dict(self):
        errors = validate_script("not a dict")
        assert any("must be a JSON object" in e for e in errors)


# ---------------------------------------------------------------------------
# T29-13: load_script — file loading
# ---------------------------------------------------------------------------

class TestLoadScript:

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="Script not found"):
            load_script("/nonexistent/path.deskaoy.json")

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.deskaoy.json"
        p.write_text("not json{{{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_script(p)

    def test_validation_error(self, tmp_path):
        p = _write_script({"steps": []}, tmp_path)
        with pytest.raises(ScriptValidationError, match="Script validation failed"):
            load_script(p)

    def test_valid_script_loaded(self, tmp_path):
        data = {
            "name": "My Script",
            "steps": [{"action": "click", "target": "OK"}],
        }
        p = _write_script(data, tmp_path)
        loaded = load_script(p)
        assert loaded["name"] == "My Script"
        assert len(loaded["steps"]) == 1


# ---------------------------------------------------------------------------
# T29-14: Dry-run mode
# ---------------------------------------------------------------------------

class TestScriptRunnerDryRun:

    @pytest.mark.asyncio
    async def test_dry_run_does_not_execute(self, tmp_path):
        agent = _mock_agent()
        runner = ScriptRunner(agent)
        data = {
            "name": "Dry Test",
            "steps": [
                {"action": "click", "target": "OK"},
                {"action": "type", "value": "Hello"},
            ]
        }
        p = _write_script(data, tmp_path)
        result = await runner.run(p, dry_run=True)

        assert result.ok is True
        assert result.dry_run is True
        assert result.steps_total == 2
        assert result.steps_ok == 2
        assert result.steps_failed == 0
        # Agent should NOT have been called
        agent.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_shows_preview(self, tmp_path):
        agent = _mock_agent()
        runner = ScriptRunner(agent)
        data = {
            "name": "Preview",
            "steps": [{"action": "click", "target": "OK"}],
        }
        p = _write_script(data, tmp_path)
        result = await runner.run(p, dry_run=True)
        assert "[dry-run]" in result.step_results[0].output


# ---------------------------------------------------------------------------
# T29-15: Sequential execution — all pass
# ---------------------------------------------------------------------------

class TestScriptRunnerExecution:

    @pytest.mark.asyncio
    async def test_all_steps_pass(self, tmp_path):
        agent = _mock_agent()
        runner = ScriptRunner(agent)
        data = {
            "name": "All Pass",
            "steps": [
                {"action": "click", "target": "OK"},
                {"action": "snapshot"},
            ]
        }
        p = _write_script(data, tmp_path)
        result = await runner.run(p)

        assert result.ok is True
        assert result.steps_total == 2
        assert result.steps_ok == 2
        assert result.steps_failed == 0
        assert agent.execute.call_count == 2


# ---------------------------------------------------------------------------
# T29-16: Sequential execution — stop on failure
# ---------------------------------------------------------------------------

class TestScriptRunnerStopOnFailure:

    @pytest.mark.asyncio
    async def test_stops_on_first_failure(self, tmp_path):
        agent = _mock_agent()

        # First call succeeds, second fails
        success = AgentResult(
            execution_id="test",
            status=ResultStatus.SUCCESS,
            summary="ok",
            confidence=Confidence(score=0.9, reason="test"),
        )
        failure = AgentResult(
            execution_id="test",
            status=ResultStatus.FAILURE,
            summary="click failed",
            confidence=Confidence(score=0.0, reason="not found"),
        )
        agent.execute = AsyncMock(side_effect=[success, failure])

        runner = ScriptRunner(agent)
        data = {
            "name": "Partial Fail",
            "steps": [
                {"action": "click", "target": "OK"},
                {"action": "click", "target": "BadTarget"},
                {"action": "snapshot"},
            ]
        }
        p = _write_script(data, tmp_path)
        result = await runner.run(p)

        assert result.ok is False
        assert result.steps_ok == 1
        assert result.steps_failed == 1
        # Third step should NOT have been executed
        assert agent.execute.call_count == 2


# ---------------------------------------------------------------------------
# T29-17: ScriptResult.success_rate
# ---------------------------------------------------------------------------

class TestScriptResultProperties:

    def test_success_rate_full(self):
        result = ScriptResult(name="test", ok=True, steps_total=4, steps_ok=4, steps_failed=0)
        assert result.success_rate == 1.0

    def test_success_rate_zero(self):
        result = ScriptResult(name="test", ok=False, steps_total=4, steps_ok=0, steps_failed=4)
        assert result.success_rate == 0.0

    def test_success_rate_empty(self):
        result = ScriptResult(name="test", ok=True, steps_total=0)
        assert result.success_rate == 1.0
