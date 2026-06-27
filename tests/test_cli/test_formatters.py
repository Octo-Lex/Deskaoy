"""Tests for CLI formatters (T01-21 through T01-27)."""
from __future__ import annotations

import json

from deskaoy.cli.formatters import (
    format_estimate,
    format_health,
    format_result,
    format_routine,
    format_schema,
    format_skill,
)
from deskaoy.os_types import (
    AgentEstimate,
    AgentResult,
    Confidence,
    ErrorCode,
    Issue,
    IssueSeverity,
    ResultStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_result(status: ResultStatus = ResultStatus.SUCCESS, **kw) -> AgentResult:
    return AgentResult(
        execution_id="exec-001",
        status=status,
        summary=kw.get("summary", "Task completed"),
        data=kw.get("data", {}),
        confidence=kw.get("confidence", Confidence(score=0.9, reason="high")),
        issues=kw.get("issues", []),
        mutations=kw.get("mutations", []),
    )


def _make_estimate(**kw) -> AgentEstimate:
    return AgentEstimate(
        cost_usd=kw.get("cost_usd", 0.001),
        latency_ms=kw.get("latency_ms", 500),
        confidence=kw.get("confidence", Confidence(score=0.85, reason="good")),
        requires_auth=kw.get("requires_auth", False),
        can_execute=kw.get("can_execute", True),
        refusal_reason=kw.get("refusal_reason", ""),
        provider_healthy=kw.get("provider_healthy", True),
        degradation_note=kw.get("degradation_note", ""),
    )


class MockHealthStatus:
    def __init__(self, healthy: bool = True):
        self.healthy = healthy
        self.message = "OK" if healthy else "FAIL"
        self.probes = {"adapter": True, "llm": True}


class MockRoutine:
    def __init__(self, name="test", schedule="0 8 * * *", instruction="hello"):
        self.name = name
        self.schedule = schedule
        self.instruction = instruction
        self.enabled = True


class MockSkill:
    def __init__(self, name="desktop-basics", description="Core desktop"):
        self.name = name
        self.description = description
        self.triggers = []

    class Trigger:
        def __init__(self, keyword="click"):
            self.keyword = keyword
            self.pattern = ""


class MockFact:
    def __init__(self, category="preference", subject="theme", content="dark mode"):
        self.category = category
        self.subject = subject
        self.content = content
        self.confidence = 0.9


# ---------------------------------------------------------------------------
# T01-21: format_result success
# ---------------------------------------------------------------------------

class TestFormatResult:

    def test_success_returns_success_string(self):
        r = _make_result(ResultStatus.SUCCESS)
        out = format_result(r)
        assert "SUCCESS" in out
        assert "✓" in out

    def test_json_mode_returns_valid_json(self):
        r = _make_result(ResultStatus.SUCCESS)
        out = format_result(r, json_mode=True)
        data = json.loads(out)
        assert data["status"] == "success"
        assert data["execution_id"] == "exec-001"

    def test_includes_confidence_bar(self):
        r = _make_result(ResultStatus.SUCCESS, confidence=Confidence(score=0.7, reason="medium"))
        out = format_result(r)
        assert "70%" in out

    def test_shows_issues(self):
        issue = Issue(
            severity=IssueSeverity.ERROR,
            code=ErrorCode.TIMEOUT,
            message="Action timed out",
        )
        r = _make_result(ResultStatus.FAILURE, issues=[issue])
        out = format_result(r)
        assert "timeout" in out.lower()


# ---------------------------------------------------------------------------
# T01-22: format_result failure
# ---------------------------------------------------------------------------

class TestFormatResultFailure:

    def test_failure_returns_failure_string(self):
        r = _make_result(ResultStatus.FAILURE, summary="Element not found")
        out = format_result(r)
        assert "FAILURE" in out
        assert "✗" in out

    def test_json_mode_failure(self):
        r = _make_result(ResultStatus.FAILURE)
        out = format_result(r, json_mode=True)
        data = json.loads(out)
        assert data["status"] == "failure"


# ---------------------------------------------------------------------------
# T01-23: format_estimate
# ---------------------------------------------------------------------------

class TestFormatEstimate:

    def test_returns_cost_and_confidence(self):
        e = _make_estimate()
        out = format_estimate(e)
        assert "$0.0010" in out
        assert "85%" in out
        assert "500ms" in out

    def test_json_mode_estimate(self):
        e = _make_estimate()
        out = format_estimate(e, json_mode=True)
        data = json.loads(out)
        assert data["cost_usd"] == 0.001
        assert data["can_execute"] is True

    def test_refusal_reason_shown(self):
        e = _make_estimate(can_execute=False, refusal_reason="No adapter")
        out = format_estimate(e)
        assert "No adapter" in out


# ---------------------------------------------------------------------------
# T01-24: format_health
# ---------------------------------------------------------------------------

class TestFormatHealth:

    def test_healthy_status(self):
        h = MockHealthStatus(healthy=True)
        out = format_health(h)
        assert "HEALTHY" in out
        assert "✓" in out

    def test_unhealthy_status(self):
        h = MockHealthStatus(healthy=False)
        out = format_health(h)
        assert "UNHEALTHY" in out
        assert "✗" in out

    def test_json_mode(self):
        h = MockHealthStatus()
        out = format_health(h, json_mode=True)
        data = json.loads(out)
        assert data["healthy"] is True


# ---------------------------------------------------------------------------
# T01-25: format_routine
# ---------------------------------------------------------------------------

class TestFormatRoutine:

    def test_shows_name_and_schedule(self):
        r = MockRoutine(name="morning", schedule="0 8 * * *", instruction="Check email")
        out = format_routine(r)
        assert "morning" in out
        assert "0 8 * * *" in out

    def test_json_mode(self):
        r = MockRoutine()
        out = format_routine(r, json_mode=True)
        data = json.loads(out)
        assert data["name"] == "test"


# ---------------------------------------------------------------------------
# T01-26: format_skill
# ---------------------------------------------------------------------------

class TestFormatSkill:

    def test_shows_name_and_description(self):
        s = MockSkill()
        out = format_skill(s)
        assert "desktop-basics" in out
        assert "Core desktop" in out

    def test_json_mode(self):
        s = MockSkill()
        out = format_skill(s, json_mode=True)
        data = json.loads(out)
        assert data["name"] == "desktop-basics"


# ---------------------------------------------------------------------------
# T01-27: format_schema
# ---------------------------------------------------------------------------

class TestFormatSchema:

    def test_shows_capabilities_table(self):
        schema = {
            "capabilities": {
                "automate": {"action_class": "sensitive", "methods": ["click", "type"]},
                "screenshot": {"action_class": "read_only", "methods": ["screenshot"]},
            }
        }
        out = format_schema(schema)
        assert "automate" in out
        assert "sensitive" in out
        assert "click" in out

    def test_json_mode(self):
        schema = {"capabilities": {"test": {"action_class": "read_only"}}}
        out = format_schema(schema, json_mode=True)
        data = json.loads(out)
        assert "capabilities" in data

    def test_empty_schema(self):
        schema = {"capabilities": {}}
        out = format_schema(schema)
        assert "no capabilities" in out
