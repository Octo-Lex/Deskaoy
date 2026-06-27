"""Tests for anchor matching and scoring."""

from __future__ import annotations

from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.memory.matching import (
    _ANCHOR_BASE_SCORES,
    _get_anchor_value,
    _nodes_near,
    _score_anchor,
    match_ax_node,
    rank_anchors,
    score_target,
)
from deskaoy.memory.types import (
    AnchorKind,
    DurableTarget,
    HealStrategy,
    TierRecord,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _target(**overrides) -> DurableTarget:
    defaults = {
        "target_id": "abc123",
        "intent": "click login",
        "surface": "browser",
        "domain": "example.com",
        "success_count": 5,
        "fail_count": 1,
    }
    defaults.update(overrides)
    return DurableTarget(**defaults)


def _snapshot(**nodes: dict) -> AXSnapshot:
    return AXSnapshot(
        url="https://example.com",
        title="Example",
        nodes={
            ref: AXNode(ref=ref, **props)
            for ref, props in nodes.items()
        },
    )


# ---------------------------------------------------------------------------
# score_target
# ---------------------------------------------------------------------------


class TestScoreTarget:
    def test_no_anchors(self):
        t = _target()
        assert score_target(t) == 0.0

    def test_high_reliability(self):
        t = _target(
            selector="button.login",
            success_count=20,
            fail_count=1,
        )
        score = score_target(t)
        assert score > 0.7

    def test_low_reliability(self):
        t = _target(
            selector="button.login",
            success_count=1,
            fail_count=10,
        )
        score = score_target(t)
        assert score < 0.5

    def test_stale_penalty(self):
        records = [TierRecord("s", "failed", 10.0, "selector")] * 3
        t = _target(selector="button.login", tier_history=records)
        score = score_target(t)
        assert score < 0.75  # stale penalty reduces from base ~0.95

    def test_diversity_bonus(self):
        t1 = _target(selector="button.login")
        t2 = _target(
            selector="button.login",
            uia_name="Login",
            ocr_text="Login",
            nearby_text=["Email"],
        )
        assert score_target(t2) >= score_target(t1)

    def test_score_range(self):
        t = _target(selector="button.login", success_count=10, fail_count=0)
        score = score_target(t)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# rank_anchors
# ---------------------------------------------------------------------------


class TestRankAnchors:
    def test_ranked_by_score(self):
        t = _target(
            selector="button.login",
            bbox_normalized=(0.5, 0.5, 0.1, 0.05),
        )
        anchors = rank_anchors(t)
        assert len(anchors) == 2
        # Selector should rank higher than bbox
        assert anchors[0].anchor_kind == AnchorKind.SELECTOR
        assert anchors[0].confidence >= anchors[1].confidence

    def test_empty_anchors(self):
        t = _target()
        anchors = rank_anchors(t)
        assert anchors == []

    def test_all_anchor_types(self):
        t = _target(
            selector="btn",
            ax_path="button/Login",
            uia_automation_id="loginBtn",
            uia_name="Login",
            uia_class="LoginButton",
            visual_fingerprint="abcd",
            ocr_text="Login",
            nearby_text=["Email"],
            bbox_normalized=(0.5, 0.5, 0.1, 0.05),
        )
        anchors = rank_anchors(t)
        assert len(anchors) == 9

    def test_anchor_values_populated(self):
        t = _target(selector="button.login", uia_name="Login")
        anchors = rank_anchors(t)
        for anchor in anchors:
            assert anchor.target_id == t.target_id
            assert anchor.anchor_value != ""


# ---------------------------------------------------------------------------
# match_ax_node
# ---------------------------------------------------------------------------


class TestMatchAxNode:
    def test_exact_name_role_match(self):
        t = _target(uia_name="Login", uia_control_type="button")
        snap = _snapshot(
            btn1={"role": "button", "name": "Login"},
            btn2={"role": "button", "name": "Signup"},
        )
        match = match_ax_node(t, snap)
        assert match is not None
        assert match.confidence >= 0.8
        assert match.healed is True
        assert match.anchor_value == "btn1"

    def test_case_insensitive_match(self):
        t = _target(uia_name="login", uia_control_type="button")
        snap = _snapshot(
            btn1={"role": "button", "name": "Login"},
        )
        match = match_ax_node(t, snap)
        assert match is not None

    def test_partial_text_match(self):
        t = _target(ocr_text="Log in")
        snap = _snapshot(
            btn1={"role": "button", "name": "Log in to your account"},
        )
        match = match_ax_node(t, snap)
        assert match is not None

    def test_no_match(self):
        t = _target(uia_name="Login", uia_control_type="button")
        snap = _snapshot(
            btn1={"role": "link", "name": "Signup"},
        )
        match = match_ax_node(t, snap)
        assert match is None

    def test_empty_snapshot(self):
        t = _target(uia_name="Login")
        snap = AXSnapshot(url="", title="", nodes={})
        match = match_ax_node(t, snap)
        assert match is None

    def test_nearby_text_anchor(self):
        t = _target(
            uia_control_type="button",
            nearby_text=["Email"],
        )
        snap = _snapshot(
            email_input={"role": "textbox", "name": "Email", "bounds": (100, 100, 200, 30)},
            login_btn={"role": "button", "name": "Login", "bounds": (100, 200, 200, 30)},
        )
        match = match_ax_node(t, snap)
        assert match is not None
        assert match.strategy == HealStrategy.NEARBY_TEXT_ANCHOR


# ---------------------------------------------------------------------------
# _get_anchor_value
# ---------------------------------------------------------------------------


class TestGetAnchorValue:
    def test_selector(self):
        t = _target(selector="button.login")
        assert _get_anchor_value(t, AnchorKind.SELECTOR) == "button.login"

    def test_bbox_normalized(self):
        t = _target(bbox_normalized=(0.1, 0.2, 0.3, 0.05))
        value = _get_anchor_value(t, AnchorKind.BBOX_NORMALIZED)
        assert "0.100" in value

    def test_nearby_text(self):
        t = _target(nearby_text=["Email", "Password"])
        value = _get_anchor_value(t, AnchorKind.NEARBY_TEXT)
        assert "Email" in value
        assert "Password" in value

    def test_empty_anchor(self):
        t = _target()
        assert _get_anchor_value(t, AnchorKind.COORDINATE) == ""


# ---------------------------------------------------------------------------
# _nodes_near
# ---------------------------------------------------------------------------


class TestNodesNear:
    def test_close_nodes(self):
        a = AXNode(ref="a", role="button", name="", bounds=(100, 100, 50, 50))
        b = AXNode(ref="b", role="button", name="", bounds=(120, 110, 50, 50))
        assert _nodes_near(a, b, threshold=200.0) is True

    def test_far_nodes(self):
        a = AXNode(ref="a", role="button", name="", bounds=(100, 100, 50, 50))
        b = AXNode(ref="b", role="button", name="", bounds=(1000, 1000, 50, 50))
        assert _nodes_near(a, b, threshold=200.0) is False

    def test_no_bounds(self):
        a = AXNode(ref="a", role="button", name="")
        b = AXNode(ref="b", role="button", name="")
        assert _nodes_near(a, b, threshold=200.0) is False


# ---------------------------------------------------------------------------
# _score_anchor
# ---------------------------------------------------------------------------


class TestScoreAnchor:
    def test_base_scores_exist(self):
        assert len(_ANCHOR_BASE_SCORES) == len(AnchorKind)

    def test_selector_highest(self):
        t = _target(selector="btn")
        assert _score_anchor(t, AnchorKind.SELECTOR) > _score_anchor(t, AnchorKind.COORDINATE)

    def test_boost_for_recently_used(self):
        records = [TierRecord("selector", "success", 10.0, "selector")]
        t = _target(selector="btn", tier_history=records)
        score_with_history = _score_anchor(t, AnchorKind.SELECTOR)

        t2 = _target(selector="btn")
        score_without = _score_anchor(t2, AnchorKind.SELECTOR)
        assert score_with_history >= score_without
