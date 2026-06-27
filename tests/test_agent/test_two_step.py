"""Tests for Two-Step Verifier (BATCH-06 TASK-02)."""
from __future__ import annotations

import pytest

from deskaoy.agent.two_step import TwoStepResult, TwoStepVerifier
from deskaoy.cascade.types import AXNode, AXSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap(nodes: dict[str, dict] | None = None) -> AXSnapshot:
    """Create a snapshot from {ref: {attr: val}}."""
    snap = AXSnapshot(url="test://", title="Test")
    if nodes:
        for ref, attrs in nodes.items():
            snap.nodes[ref] = AXNode(ref=ref, **attrs)
    return snap


class TestTwoStepVerifier:
    """TEST-06-02-01 through TEST-06-02-07."""

    @pytest.fixture
    def verifier(self):
        return TwoStepVerifier()

    def test_returns_result_with_confidence(self, verifier):
        """TEST-06-02-01: verify() returns TwoStepResult with confidence."""
        before = _snap({"e1": {"role": "textbox", "name": "Input", "value": ""}})
        after = _snap({"e1": {"role": "textbox", "name": "Input", "value": "hello"}})
        result = verifier.verify(before, after, "fill", "Input")
        assert isinstance(result, TwoStepResult)
        assert 0.0 <= result.confidence <= 1.0

    def test_click_dialog_opened(self, verifier):
        """TEST-06-02-02: Click detected as applied when dialog opens."""
        before = _snap({"e1": {"role": "button", "name": "Open"}})
        after = _snap({
            "e1": {"role": "button", "name": "Open"},
            "e2": {"role": "dialog", "name": "Confirm"},
        })
        result = verifier.verify(before, after, "click", "Open")
        assert result.action_applied is True
        assert result.confidence >= 0.8

    def test_fill_value_changes(self, verifier):
        """TEST-06-02-03: Fill detected as applied when value changes."""
        before = _snap({"e1": {"role": "textbox", "name": "Name", "value": ""}})
        after = _snap({"e1": {"role": "textbox", "name": "Name", "value": "Alice"}})
        result = verifier.verify(before, after, "fill", "Name")
        assert result.action_applied is True
        assert result.confidence >= 0.9

    def test_inconclusive_no_change(self, verifier):
        """TEST-06-02-04: Inconclusive when no detectable change."""
        before = _snap({"e1": {"role": "button", "name": "OK"}})
        after = _snap({"e1": {"role": "button", "name": "OK"}})
        result = verifier.verify(before, after, "click", "OK")
        assert result.action_applied is False
        assert result.confidence < 0.5
        assert result.is_conclusive is False

    def test_evidence_human_readable(self, verifier):
        """TEST-06-02-05: Evidence string is human-readable."""
        before = _snap({"e1": {"role": "textbox", "name": "Input", "value": ""}})
        after = _snap({"e1": {"role": "textbox", "name": "Input", "value": "typed"}})
        result = verifier.verify(before, after, "type_text", "Input")
        assert isinstance(result.evidence, str)
        assert len(result.evidence) > 10

    def test_confidence_range(self, verifier):
        """TEST-06-02-06: Confidence is always between 0.0 and 1.0."""
        # Test multiple scenarios
        scenarios = [
            # No change
            (_snap({"e1": {"role": "button", "name": "OK"}}),
             _snap({"e1": {"role": "button", "name": "OK"}}), "click", "OK"),
            # Value change
            (_snap({"e1": {"role": "textbox", "name": "T", "value": ""}}),
             _snap({"e1": {"role": "textbox", "name": "T", "value": "x"}}), "fill", "T"),
            # Dialog opens
            (_snap({"e1": {"role": "button", "name": "Open"}}),
             _snap({"e1": {"role": "button", "name": "Open"}, "e2": {"role": "dialog", "name": "D"}}),
             "click", "Open"),
        ]
        for before, after, action, target in scenarios:
            result = verifier.verify(before, after, action, target)
            assert 0.0 <= result.confidence <= 1.0, f"Confidence out of range: {result.confidence}"

    def test_handles_empty_snapshots(self, verifier):
        """TEST-06-02-07: verify() handles empty snapshots."""
        before = _snap()
        after = _snap()
        result = verifier.verify(before, after, "click", "")
        assert result.action_applied is False

    def test_key_press_dismisses_dialog(self, verifier):
        """Key press that closes a dialog is detected."""
        before = _snap({
            "e1": {"role": "button", "name": "OK"},
            "e2": {"role": "dialog", "name": "Confirm"},
        })
        after = _snap({"e1": {"role": "button", "name": "OK"}})
        result = verifier.verify(before, after, "key_press", "Escape")
        assert result.action_applied is True
        assert "dismissed" in result.evidence.lower()

    def test_scroll_changes_visible(self, verifier):
        """Scroll that changes visible elements is detected."""
        before = _snap({"e1": {"role": "button", "name": "Top"}})
        after = _snap({"e2": {"role": "button", "name": "Bottom"}})
        result = verifier.verify(before, after, "scroll", "down")
        assert result.action_applied is True

    def test_type_text_appended(self, verifier):
        """Type text that appends to value is detected."""
        before = _snap({"e1": {"role": "textbox", "name": "T", "value": "ab"}})
        after = _snap({"e1": {"role": "textbox", "name": "T", "value": "abc"}})
        result = verifier.verify(before, after, "type_text", "T")
        assert result.action_applied is True
        assert result.confidence >= 0.8

    def test_unknown_action_generic(self, verifier):
        """Unknown action falls back to generic verification."""
        before = _snap({"e1": {"role": "button", "name": "A"}})
        after = _snap({"e1": {"role": "button", "name": "A"}, "e2": {"role": "button", "name": "B"}})
        result = verifier.verify(before, after, "custom_action", "A")
        assert isinstance(result, TwoStepResult)
        assert result.confidence > 0
