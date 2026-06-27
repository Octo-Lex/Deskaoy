"""Tests for pre-flight instruction validation (LangExtract pattern B)."""

from unittest.mock import MagicMock

from deskaoy.validation import (
    KNOWN_ACTIONS,
    ValidationIssue,
    ValidationIssueKind,
    ValidationLevel,
    ValidationReport,
    extract_actions,
    validate_instruction,
)

# ---------------------------------------------------------------------------
# extract_actions
# ---------------------------------------------------------------------------

class TestExtractActions:
    def test_single_action(self):
        assert extract_actions("click the Submit button") == ["click"]

    def test_multiple_actions(self):
        actions = extract_actions("click Submit then type_text hello and scroll down")
        assert "click" in actions
        assert "type_text" in actions
        assert "scroll" in actions

    def test_case_insensitive(self):
        assert extract_actions("Click the button") == ["click"]

    def test_no_actions(self):
        assert extract_actions("go to the thing") == []

    def test_all_known_actions(self):
        text = "click double_click right_click hover type_text fill key_press key_combo scroll select_option drag screenshot snapshot navigate wait focus"
        actions = extract_actions(text)
        assert len(actions) == len(KNOWN_ACTIONS)


# ---------------------------------------------------------------------------
# ValidationReport
# ---------------------------------------------------------------------------

class TestValidationReport:
    def test_valid_no_issues(self):
        report = ValidationReport(valid=True)
        assert not report.has_errors
        assert report.error_count == 0

    def test_has_errors_with_unknown_action(self):
        report = ValidationReport(
            valid=False,
            issues=[ValidationIssue(
                kind=ValidationIssueKind.UNKNOWN_ACTION,
                message="No known action",
            )],
        )
        assert report.has_errors

    def test_has_errors_with_missing_surface(self):
        report = ValidationReport(
            valid=False,
            issues=[ValidationIssue(
                kind=ValidationIssueKind.MISSING_SURFACE,
                message="No surface",
            )],
        )
        assert report.has_errors

    def test_no_errors_for_policy_denied(self):
        """Policy denied is a warning, not a hard error."""
        report = ValidationReport(
            valid=True,
            issues=[ValidationIssue(
                kind=ValidationIssueKind.POLICY_DENIED,
                message="Policy denies",
            )],
        )
        assert not report.has_errors

    def test_to_dict(self):
        report = ValidationReport(
            valid=False,
            issues=[ValidationIssue(
                kind=ValidationIssueKind.UNKNOWN_ACTION,
                message="No action",
                action="foo",
                suggestion="Try click",
            )],
        )
        d = report.to_dict()
        assert d["valid"] is False
        assert len(d["issues"]) == 1
        assert d["issues"][0]["kind"] == "unknown_action"


# ---------------------------------------------------------------------------
# validate_instruction
# ---------------------------------------------------------------------------

class TestValidateInstruction:
    def _make_agent(self, has_surface=True, reachable=True, has_policy=False, policy_denied=False):
        agent = MagicMock()
        if not has_surface:
            agent._surface_adapter = None
        else:
            adapter = MagicMock()
            if reachable:
                adapter.is_reachable = MagicMock(return_value=True)
            else:
                adapter.is_reachable = MagicMock(return_value=False)
            agent._surface_adapter = adapter

        if has_policy:
            policy = MagicMock()
            if policy_denied:
                decision = MagicMock()
                decision.effect = "deny"
                policy.preflight = MagicMock(return_value=decision)
            else:
                decision = MagicMock()
                decision.effect = "allow"
                policy.preflight = MagicMock(return_value=decision)
            agent._policy_bridge = policy
        else:
            agent._policy_bridge = None

        return agent

    def test_valid_instruction(self):
        agent = self._make_agent()
        report = validate_instruction("click Submit button", agent=agent)
        assert report.valid
        assert not report.has_errors

    def test_no_surface_adapter(self):
        agent = self._make_agent(has_surface=False)
        report = validate_instruction("click Submit", agent=agent)
        assert not report.valid
        assert any(i.kind == ValidationIssueKind.MISSING_SURFACE for i in report.issues)

    def test_surface_unreachable(self):
        agent = self._make_agent(reachable=False)
        report = validate_instruction("click Submit", agent=agent)
        assert any(i.kind == ValidationIssueKind.SURFACE_UNREACHABLE for i in report.issues)

    def test_unknown_action_vague_instruction(self):
        agent = self._make_agent()
        report = validate_instruction("do the thing with the stuff", agent=agent)
        assert any(i.kind == ValidationIssueKind.UNKNOWN_ACTION for i in report.issues)

    def test_level_off_skips(self):
        agent = self._make_agent(has_surface=False)
        report = validate_instruction("click", agent=agent, level=ValidationLevel.OFF)
        assert report.valid

    def test_level_error_logs_on_issues(self):
        agent = self._make_agent(has_surface=False)
        report = validate_instruction("click", agent=agent, level=ValidationLevel.ERROR)
        assert not report.valid

    def test_policy_denied_caught(self):
        agent = self._make_agent(has_policy=True, policy_denied=True)
        report = validate_instruction("click the button", agent=agent)
        assert any(i.kind == ValidationIssueKind.POLICY_DENIED for i in report.issues)

    def test_multiple_issues(self):
        agent = self._make_agent(reachable=False)
        report = validate_instruction("go to the thing", agent=agent)
        assert report.error_count >= 1

    def test_suggestion_provided(self):
        agent = self._make_agent()
        report = validate_instruction("go to the thing", agent=agent)
        issues = [i for i in report.issues if i.kind == ValidationIssueKind.UNKNOWN_ACTION]
        if issues:
            assert issues[0].suggestion != ""
