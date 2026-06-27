"""Tests for deskaoy.cascade.formatter — G9 Snapshot Formatter."""

from __future__ import annotations

from deskaoy.cascade.formatter import (
    _FormatNode,
    _pass_collapse,
    _pass_dedup,
    _pass_filter,
    _pass_prune,
    format_snapshot,
)
from deskaoy.cascade.types import AXNode, AXSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap(nodes: dict[str, AXNode], url: str = "test://app", title: str = "Test") -> AXSnapshot:
    return AXSnapshot(url=url, title=title, nodes=nodes)


def _node(ref: str, role: str, name: str = "", **kw) -> AXNode:
    return AXNode(ref=ref, role=role, name=name, **kw)


# ---------------------------------------------------------------------------
# Pass 1: Filter
# ---------------------------------------------------------------------------

class TestPassFilter:

    def test_keeps_interactive(self):
        nodes = [
            _FormatNode(ref="e0", role="button", name="Submit"),
            _FormatNode(ref="e1", role="textbox", name="Search"),
        ]
        result = _pass_filter(nodes)
        assert len(result) == 2

    def test_removes_decorative(self):
        nodes = [
            _FormatNode(ref="e0", role="separator", name=""),
            _FormatNode(ref="e1", role="unknown", name=""),
            _FormatNode(ref="e2", role="button", name="OK"),
        ]
        result = _pass_filter(nodes)
        assert len(result) == 1
        assert result[0].ref == "e2"

    def test_keeps_named_containers(self):
        nodes = [
            _FormatNode(ref="e0", role="group", name="Login Form"),
        ]
        result = _pass_filter(nodes)
        assert len(result) == 1

    def test_removes_unnamed_decorative_panes(self):
        nodes = [
            _FormatNode(ref="e0", role="pane", name=""),
            _FormatNode(ref="e1", role="image", name=""),
        ]
        result = _pass_filter(nodes)
        # pane is structural (not decorative), image is decorative
        assert len(result) == 1
        assert result[0].ref == "e0"


# ---------------------------------------------------------------------------
# Pass 2: Dedup
# ---------------------------------------------------------------------------

class TestPassDedup:

    def test_deduplicates_identical_role_name(self):
        nodes = [
            _FormatNode(ref="e0", role="text", name="Results"),
            _FormatNode(ref="e1", role="text", name="Results"),
        ]
        result = _pass_dedup(nodes)
        assert len(result) == 1

    def test_keeps_interactive_duplicates(self):
        nodes = [
            _FormatNode(ref="e0", role="button", name="Submit"),
            _FormatNode(ref="e1", role="button", name="Submit"),
        ]
        result = _pass_dedup(nodes)
        assert len(result) == 2  # interactive elements are kept

    def test_single_node(self):
        nodes = [_FormatNode(ref="e0", role="button", name="OK")]
        result = _pass_dedup(nodes)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Pass 3: Prune
# ---------------------------------------------------------------------------

class TestPassPrune:

    def test_prunes_empty_container(self):
        parent = _FormatNode(ref="e0", role="group", name="")
        result = _pass_prune([parent])
        assert len(result) == 0

    def test_keeps_interactive(self):
        nodes = [_FormatNode(ref="e0", role="button", name="OK")]
        result = _pass_prune(nodes)
        assert len(result) == 1

    def test_keeps_named_container(self):
        nodes = [_FormatNode(ref="e0", role="group", name="Login")]
        result = _pass_prune(nodes)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Pass 4: Collapse
# ---------------------------------------------------------------------------

class TestPassCollapse:

    def test_removes_consecutive_unnamed_decorative(self):
        nodes = [
            _FormatNode(ref="e0", role="separator", name=""),
            _FormatNode(ref="e1", role="button", name="OK"),
        ]
        result = _pass_collapse(nodes)
        assert len(result) == 1
        assert result[0].ref == "e1"

    def test_keeps_named_nodes(self):
        nodes = [
            _FormatNode(ref="e0", role="group", name="Form"),
            _FormatNode(ref="e1", role="button", name="Submit"),
        ]
        result = _pass_collapse(nodes)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def test_empty_snapshot(self):
        snap = _snap({})
        text = format_snapshot(snap)
        assert "(empty)" in text
        assert "interactive: 0" in text

    def test_basic_formatting(self):
        snap = _snap({
            "e0": _node("e0", "button", "Submit"),
            "e1": _node("e1", "textbox", "Search", value="hello"),
        })
        text = format_snapshot(snap)
        assert "[e0]" in text
        assert 'button' in text
        assert 'name="Submit"' in text
        assert "[e1]" in text
        assert 'value="hello"' in text
        assert "---" in text
        assert "interactive:" in text

    def test_url_and_title_header(self):
        snap = _snap({}, url="win32://Notepad", title="Untitled - Notepad")
        text = format_snapshot(snap)
        assert "url: win32://Notepad" in text
        assert "title: Untitled - Notepad" in text

    def test_disabled_element_shown(self):
        snap = _snap({
            "e0": _node("e0", "button", "Submit", disabled=True),
        })
        text = format_snapshot(snap)
        assert "[disabled]" in text

    def test_noisy_snapshot_reduced(self):
        """Snapshot with noise elements should be smaller after formatting."""
        nodes = {}
        nodes["e0"] = _node("e0", "separator", "")
        nodes["e1"] = _node("e1", "unknown", "")
        nodes["e2"] = _node("e2", "pane", "")
        nodes["e3"] = _node("e3", "text", "")
        nodes["e4"] = _node("e4", "button", "OK")
        nodes["e5"] = _node("e5", "image", "")
        snap = _snap(nodes)
        text = format_snapshot(snap)
        # Only the button should survive the pipeline
        assert "[e4]" in text
        assert "interactive: 1" in text
        # Noise should be gone
        assert "[e0]" not in text
        assert "[e1]" not in text
