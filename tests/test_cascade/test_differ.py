"""Tests for Snapshot Differ (BATCH-06 TASK-01)."""
from __future__ import annotations

import pytest

from deskaoy.cascade.differ import SnapshotDiffer, SnapshotDiff, NodeDiff
from deskaoy.cascade.types import AXNode, AXSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(nodes: dict[str, dict] | None = None, **kwargs) -> AXSnapshot:
    """Create an AXSnapshot from a dict of {ref: {attr: value}}."""
    snap = AXSnapshot(url=kwargs.get("url", "test://"), title=kwargs.get("title", "Test"))
    if nodes:
        for ref, attrs in nodes.items():
            snap.nodes[ref] = AXNode(ref=ref, **attrs)
    return snap


def _node(ref: str, role: str = "button", name: str = "", value: str | None = None,
          disabled: bool = False, focused: bool = False) -> AXNode:
    return AXNode(ref=ref, role=role, name=name, value=value, disabled=disabled, focused=focused)


# ---------------------------------------------------------------------------
# Test Snapshot Differ
# ---------------------------------------------------------------------------

class TestSnapshotDiffer:
    """TEST-06-01-01 through TEST-06-01-09."""

    @pytest.fixture
    def differ(self):
        return SnapshotDiffer()

    def test_identical_snapshots_empty_diff(self, differ):
        """TEST-06-01-01: Identical snapshots produce empty diff."""
        before = _make_snapshot({"e1": {"role": "button", "name": "OK"}})
        after = _make_snapshot({"e1": {"role": "button", "name": "OK"}})
        diff = differ.diff(before, after)
        assert diff.is_empty is True
        assert diff.total_changes == 0

    def test_added_element_detected(self, differ):
        """TEST-06-01-02: Added element detected in 'after' snapshot."""
        before = _make_snapshot({"e1": {"role": "button", "name": "OK"}})
        after = _make_snapshot({
            "e1": {"role": "button", "name": "OK"},
            "e2": {"role": "textbox", "name": "Input"},
        })
        diff = differ.diff(before, after)
        assert len(diff.added) == 1
        assert diff.added[0].ref == "e2"
        assert diff.added[0].role == "textbox"

    def test_removed_element_detected(self, differ):
        """TEST-06-01-03: Removed element detected from 'before' snapshot."""
        before = _make_snapshot({
            "e1": {"role": "button", "name": "OK"},
            "e2": {"role": "dialog", "name": "Confirm"},
        })
        after = _make_snapshot({"e1": {"role": "button", "name": "OK"}})
        diff = differ.diff(before, after)
        assert len(diff.removed) == 1
        assert diff.removed[0].ref == "e2"

    def test_changed_value_detected(self, differ):
        """TEST-06-01-04: Changed value detected with field, before, after."""
        before = _make_snapshot({"e1": {"role": "textbox", "name": "Input", "value": ""}})
        after = _make_snapshot({"e1": {"role": "textbox", "name": "Input", "value": "hello"}})
        diff = differ.diff(before, after)
        assert len(diff.changed) == 1
        assert diff.changed[0].field == "value"
        assert diff.changed[0].before == ""
        assert diff.changed[0].after == "hello"

    def test_diff_to_text_readable(self, differ):
        """TEST-06-01-05: diff_to_text produces readable output."""
        before = _make_snapshot({"e1": {"role": "textbox", "name": "Input", "value": ""}})
        after = _make_snapshot({
            "e1": {"role": "textbox", "name": "Input", "value": "hello"},
            "e2": {"role": "button", "name": "Submit"},
        })
        diff = differ.diff(before, after)
        text = differ.diff_to_text(diff)
        assert "DIFF:" in text
        assert "+" in text  # added
        assert "~" in text  # changed

    def test_is_significant_empty(self, differ):
        """TEST-06-01-06: is_significant returns False for empty diff."""
        diff = SnapshotDiff()
        assert differ.is_significant(diff) is False

    def test_is_significant_with_changes(self, differ):
        """TEST-06-01-07: is_significant returns True for added/changed."""
        # Added
        diff = SnapshotDiff(added=[_node("e2")])
        assert differ.is_significant(diff) is True

        # Value changed
        diff2 = SnapshotDiff(changed=[NodeDiff(ref="e1", role="textbox", field="value", before="", after="x")])
        assert differ.is_significant(diff2) is True

        # Only focus changed — not significant
        diff3 = SnapshotDiff(changed=[NodeDiff(ref="e1", role="textbox", field="focused", before="False", after="True")])
        assert differ.is_significant(diff3) is False

    def test_large_diff_truncates(self, differ):
        """TEST-06-01-08: Large diff (>50 nodes) truncates output."""
        nodes = {f"e{i}": {"role": "button", "name": f"Btn{i}"} for i in range(100)}
        before = _make_snapshot()
        after = _make_snapshot(nodes)
        diff = differ.diff(before, after)
        text = differ.diff_to_text(diff, max_changes=5)
        assert "truncated" in text

    def test_empty_snapshots_handled(self, differ):
        """TEST-06-01-09: Empty snapshots handled gracefully."""
        before = _make_snapshot()
        after = _make_snapshot()
        diff = differ.diff(before, after)
        assert diff.is_empty is True

        # Empty → non-empty
        after2 = _make_snapshot({"e1": {"role": "button", "name": "OK"}})
        diff2 = differ.diff(before, after2)
        assert len(diff2.added) == 1

    def test_empty_diff_text(self, differ):
        """Empty diff produces 'no changes' text."""
        diff = SnapshotDiff()
        text = differ.diff_to_text(diff)
        assert "no changes" in text

    def test_element_appeared(self, differ):
        """element_appeared checks for matching added elements."""
        before = _make_snapshot()
        after = _make_snapshot({"e1": {"role": "dialog", "name": "Success"}})
        diff = differ.diff(before, after)
        assert differ.element_appeared(diff, role="dialog") is True
        assert differ.element_appeared(diff, role="menu") is False
        assert differ.element_appeared(diff, name_contains="success") is True

    def test_element_disappeared(self, differ):
        """element_disappeared checks for matching removed elements."""
        before = _make_snapshot({"e1": {"role": "dialog", "name": "Confirm"}})
        after = _make_snapshot()
        diff = differ.diff(before, after)
        assert differ.element_disappeared(diff, role="dialog") is True
        assert differ.element_disappeared(diff, name_contains="confirm") is True

    def test_has_value_change(self, differ):
        """has_value_change checks for value changes on specific element."""
        before = _make_snapshot({"e1": {"role": "textbox", "name": "Input", "value": "old"}})
        after = _make_snapshot({"e1": {"role": "textbox", "name": "Input", "value": "new"}})
        diff = differ.diff(before, after)
        assert differ.has_value_change(diff, "e1") is True
        assert differ.has_value_change(diff, "e2") is False

    def test_multiple_field_changes(self, differ):
        """Multiple field changes on same element produce separate NodeDiffs."""
        before = _make_snapshot({"e1": {"role": "textbox", "name": "Input", "value": "", "disabled": False}})
        after = _make_snapshot({"e1": {"role": "textbox", "name": "Input", "value": "typed", "disabled": True}})
        diff = differ.diff(before, after)
        assert len(diff.changed) == 2
        fields = {c.field for c in diff.changed}
        assert "value" in fields
        assert "disabled" in fields

    def test_sort_order_numeric(self, differ):
        """Refs are sorted numerically (e1, e2, ..., e10, not e1, e10, e2)."""
        before = _make_snapshot()
        after = _make_snapshot({
            f"e{i}": {"role": "button", "name": f"B{i}"}
            for i in [10, 2, 1, 5]
        })
        diff = differ.diff(before, after)
        refs = [n.ref for n in diff.added]
        assert refs == ["e1", "e2", "e5", "e10"]
