"""Tests for deskaoy.cascade.resolver — G1 Stale-Ref Resolver."""

from __future__ import annotations

from deskaoy.cascade.resolver import (
    ElementFingerprint,
    MatchLevel,
    StaleRefResolver,
    fingerprint_from_node,
)
from deskaoy.cascade.types import AXNode, AXSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node(ref: str, role: str, name: str = "", **kw) -> AXNode:
    return AXNode(ref=ref, role=role, name=name, **kw)


def _snap(nodes: dict[str, AXNode]) -> AXSnapshot:
    return AXSnapshot(url="test://app", title="Test", nodes=nodes)


# ---------------------------------------------------------------------------
# Fingerprint extraction
# ---------------------------------------------------------------------------

class TestFingerprint:

    def test_from_node(self):
        n = _node("e0", "button", "Submit", value="click")
        fp = fingerprint_from_node(n)
        assert fp.role == "button"
        assert fp.name == "Submit"
        assert fp.text_prefix == "click"

    def test_from_node_no_value(self):
        n = _node("e0", "textbox", "Search")
        fp = fingerprint_from_node(n)
        assert fp.text_prefix == ""

    def test_from_node_with_automation_id(self):
        n = _node("e0", "button", "OK", automation_id="btn_ok")
        fp = fingerprint_from_node(n)
        assert fp.automation_id == "btn_ok"


# ---------------------------------------------------------------------------
# Tier 1: EXACT match
# ---------------------------------------------------------------------------

class TestExactMatch:

    def test_exact_match(self):
        n = _node("e0", "button", "Submit")
        snap = _snap({"e0": _node("e0", "button", "Submit")})
        fp = fingerprint_from_node(n)
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert result.ok
        assert result.match_level == MatchLevel.EXACT
        assert result.node is not None
        assert result.node.name == "Submit"

    def test_exact_no_match_different_role(self):
        original = _node("e0", "button", "Submit")
        snap = _snap({"e0": _node("e0", "textbox", "Submit")})  # role changed
        fp = fingerprint_from_node(original)
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        # Should NOT exact match (role differs) but may reidentify
        assert result.match_level != MatchLevel.EXACT or not result.ok


# ---------------------------------------------------------------------------
# Tier 2: STABLE match (automation_id)
# ---------------------------------------------------------------------------

class TestStableMatch:

    def test_stable_via_automation_id(self):
        """Ref changes but automation_id matches."""
        fp = ElementFingerprint(
            role="button", name="Submit", automation_id="btn_submit",
        )
        # Element at a different ref but same automation_id
        snap = _snap({"e99": _node("e99", "button", "Submit", automation_id="btn_submit")})
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert result.ok
        assert result.match_level == MatchLevel.STABLE
        assert result.node.ref == "e99"

    def test_stable_ambiguous(self):
        """Multiple elements with same automation_id → ambiguous."""
        fp = ElementFingerprint(
            role="button", name="Submit", automation_id="btn",
        )
        snap = _snap({
            "e1": _node("e1", "button", "Submit", automation_id="btn"),
            "e2": _node("e2", "button", "Cancel", automation_id="btn"),
        })
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert not result.ok
        assert result.error_code == "ambiguous"

    def test_stable_no_automation_id(self):
        """No automation_id in fingerprint → skip tier 2."""
        fp = ElementFingerprint(role="button", name="Submit")
        snap = _snap({
            "e1": _node("e1", "button", "Submit"),
        })
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        # Should go to tier 3 (reidentify)
        assert result.ok
        assert result.match_level == MatchLevel.REIDENTIFIED


# ---------------------------------------------------------------------------
# Tier 3: REIDENTIFIED
# ---------------------------------------------------------------------------

class TestReidentified:

    def test_unique_fingerprint_match(self):
        fp = ElementFingerprint(role="button", name="Submit")
        snap = _snap({
            "e5": _node("e5", "button", "Submit"),  # exact same name
            "e6": _node("e6", "button", "Cancel"),
        })
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert result.ok
        assert result.match_level == MatchLevel.REIDENTIFIED
        assert result.node.name == "Submit"

    def test_clear_winner_with_multiple_candidates(self):
        """Top candidate scores much higher than second."""
        fp = ElementFingerprint(role="button", name="Submit")
        snap = _snap({
            "e5": _node("e5", "button", "Submit"),       # high match
            "e6": _node("e6", "textbox", "Submit Form"),  # low match
        })
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert result.ok
        assert result.node.ref == "e5"

    def test_ambiguous_candidates(self):
        """Multiple equally-good candidates → ambiguous."""
        fp = ElementFingerprint(role="button", name="Submit")
        snap = _snap({
            "e1": _node("e1", "button", "Submit"),
            "e2": _node("e2", "button", "Submit"),
        })
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert not result.ok
        assert result.error_code == "ambiguous"

    def test_no_match_at_all(self):
        fp = ElementFingerprint(role="button", name="Submit")
        snap = _snap({
            "e1": _node("e1", "textbox", "Search"),
            "e2": _node("e2", "link", "Home"),
        })
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert not result.ok
        assert result.error_code == "not_found"

    def test_empty_snapshot(self):
        fp = ElementFingerprint(role="button", name="Submit")
        snap = _snap({})
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert not result.ok
        assert result.error_code == "not_found"


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_ref_changed_but_element_survives(self):
        """Common case: page re-renders, element gets new ref."""
        original = _node("e42", "button", "OK")
        fp = fingerprint_from_node(original)

        # After re-render, button is now at e99
        snap = _snap({"e99": _node("e99", "button", "OK")})
        resolver = StaleRefResolver()
        result = resolver.resolve("e42", fp, snap)
        assert result.ok
        assert result.node.ref == "e99"

    def test_name_drift_but_id_stable(self):
        """Element name changed (localized) but automation_id is same."""
        fp = ElementFingerprint(role="button", name="Submit", automation_id="btn_submit")
        snap = _snap({
            "e42": _node("e42", "button", "Enviar", automation_id="btn_submit"),
        })
        resolver = StaleRefResolver()
        result = resolver.resolve("e0", fp, snap)
        assert result.ok
        assert result.match_level == MatchLevel.STABLE
