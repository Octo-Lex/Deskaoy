"""Tests for post-action grounding verification (LangExtract pattern A)."""

import pytest
from deskaoy.verification.grounding import (
    ActionGrounding,
    GroundingTier,
    TIER_CONFIDENCE,
    verify_grounding,
    _detect_property_changes,
    _find_by_bounds,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeAXNode:
    def __init__(self, ref="e1", name="Button", role="button", bounds=None, disabled=False):
        self.ref = ref
        self.name = name
        self.role = role
        self.bounds = bounds
        self.disabled = disabled


class FakeSnapshot:
    def __init__(self, nodes=None):
        self.nodes = nodes or {}

    def resolve(self, ref):
        return self.nodes.get(ref)

    def find_by_text(self, text):
        text_lower = text.lower()
        return [n for n in self.nodes.values() if text_lower in n.name.lower()]


# ---------------------------------------------------------------------------
# Structural grounding (Tier 1)
# ---------------------------------------------------------------------------

class TestStructuralGrounding:
    def test_ref_found_structural(self):
        snap = FakeSnapshot({"e42": FakeAXNode(ref="e42", name="Submit")})
        g = verify_grounding(target_ref="e42", target_text="Submit", post_snapshot=snap)
        assert g.tier == GroundingTier.STRUCTURAL
        assert g.confidence == 0.95
        assert g.still_exists is True
        assert g.verification_method == "ax_tree"

    def test_ref_found_with_bounds(self):
        snap = FakeSnapshot({"e5": FakeAXNode(ref="e5", name="OK", bounds=(10, 20, 80, 30))})
        g = verify_grounding(
            target_ref="e5", target_text="OK",
            target_bounds=(10, 20, 80, 30), post_snapshot=snap,
        )
        assert g.tier == GroundingTier.STRUCTURAL
        assert g.properties_changed == []

    def test_properties_changed_disabled(self):
        snap = FakeSnapshot({"e1": FakeAXNode(ref="e1", name="Btn", disabled=True)})
        g = verify_grounding(target_ref="e1", target_text="Btn", post_snapshot=snap)
        assert g.tier == GroundingTier.STRUCTURAL
        assert "disabled" in g.properties_changed

    def test_properties_changed_name(self):
        snap = FakeSnapshot({"e1": FakeAXNode(ref="e1", name="New Name")})
        g = verify_grounding(target_ref="e1", target_text="Old Name", post_snapshot=snap)
        assert g.tier == GroundingTier.STRUCTURAL
        assert "name" in g.properties_changed

    def test_properties_changed_bounds(self):
        snap = FakeSnapshot({"e1": FakeAXNode(ref="e1", name="Btn", bounds=(10, 20, 100, 50))})
        g = verify_grounding(
            target_ref="e1", target_text="Btn",
            target_bounds=(10, 20, 80, 30), post_snapshot=snap,
        )
        assert g.tier == GroundingTier.STRUCTURAL
        assert "bounds" in g.properties_changed


# ---------------------------------------------------------------------------
# Visual grounding (Tier 2)
# ---------------------------------------------------------------------------

class TestVisualGrounding:
    def test_bounds_match_when_ref_gone(self):
        snap = FakeSnapshot({"e99": FakeAXNode(ref="e99", name="Other", bounds=(100, 200, 50, 30))})
        g = verify_grounding(
            target_ref="e42", target_text="Submit",
            target_bounds=(100, 200, 50, 30), post_snapshot=snap,
        )
        assert g.tier == GroundingTier.VISUAL
        assert g.confidence == 0.80
        assert g.verification_method == "visual_diff"
        assert g.still_exists is True

    def test_no_bounds_skips_visual(self):
        snap = FakeSnapshot({"e99": FakeAXNode(ref="e99", name="Other")})
        g = verify_grounding(
            target_ref="e42", target_text="Submit",
            target_bounds=None, post_snapshot=snap,
        )
        # Falls through to text tier
        assert g.tier != GroundingTier.VISUAL


# ---------------------------------------------------------------------------
# Text grounding (Tier 3)
# ---------------------------------------------------------------------------

class TestTextGrounding:
    def test_text_found_when_ref_and_bounds_gone(self):
        snap = FakeSnapshot({"e99": FakeAXNode(ref="e99", name="Submit Button")})
        g = verify_grounding(target_ref="e42", target_text="Submit", post_snapshot=snap)
        assert g.tier == GroundingTier.TEXT
        assert g.confidence == 0.60
        assert g.verification_method == "ocr"

    def test_text_not_found(self):
        snap = FakeSnapshot({"e99": FakeAXNode(ref="e99", name="Cancel")})
        g = verify_grounding(target_ref="e42", target_text="Submit", post_snapshot=snap)
        assert g.tier == GroundingTier.UNVERIFIED
        assert g.still_exists is False


# ---------------------------------------------------------------------------
# Unverified (Tier 4)
# ---------------------------------------------------------------------------

class TestUnverified:
    def test_no_snapshot(self):
        g = verify_grounding(target_ref="e42", target_text="Submit")
        assert g.tier == GroundingTier.UNVERIFIED
        assert g.confidence == 0.0
        assert g.still_exists is False
        assert g.verification_method == "none"

    def test_empty_snapshot(self):
        snap = FakeSnapshot({})
        g = verify_grounding(target_ref="e42", target_text="Submit", post_snapshot=snap)
        assert g.tier == GroundingTier.UNVERIFIED

    def test_no_target_info(self):
        snap = FakeSnapshot({"e1": FakeAXNode()})
        g = verify_grounding(post_snapshot=snap)
        assert g.tier == GroundingTier.UNVERIFIED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_find_by_bounds_match(self):
        snap = FakeSnapshot({"e1": FakeAXNode(ref="e1", bounds=(100, 200, 50, 30))})
        result = _find_by_bounds(snap, (100, 200, 50, 30))
        assert result is not None
        assert result.ref == "e1"

    def test_find_by_bounds_tolerance(self):
        snap = FakeSnapshot({"e1": FakeAXNode(ref="e1", bounds=(100, 200, 50, 30))})
        result = _find_by_bounds(snap, (103, 202, 50, 30), tolerance=5.0)
        assert result is not None

    def test_find_by_bounds_no_match(self):
        snap = FakeSnapshot({"e1": FakeAXNode(ref="e1", bounds=(100, 200, 50, 30))})
        result = _find_by_bounds(snap, (500, 500, 50, 30))
        assert result is None

    def test_detect_property_changes_none(self):
        node = FakeAXNode(name="Submit")
        changed = _detect_property_changes(node, "Submit", None)
        assert changed == []

    def test_to_dict(self):
        g = ActionGrounding(
            tier=GroundingTier.STRUCTURAL,
            confidence=0.95,
            target_ref="e42",
            target_text="Submit",
            still_exists=True,
            verification_method="ax_tree",
        )
        d = g.to_dict()
        assert d["tier"] == "structural"
        assert d["confidence"] == 0.95
        assert d["target_ref"] == "e42"

    def test_tier_confidence_map(self):
        assert TIER_CONFIDENCE[GroundingTier.STRUCTURAL] == 0.95
        assert TIER_CONFIDENCE[GroundingTier.VISUAL] == 0.80
        assert TIER_CONFIDENCE[GroundingTier.TEXT] == 0.60
        assert TIER_CONFIDENCE[GroundingTier.UNVERIFIED] == 0.0
