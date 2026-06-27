"""Tests for memory types — DurableTarget, ActionEvidence, TierRecord, AnchorMatch."""

from __future__ import annotations

from deskaoy.memory.types import (
    ActionEvidence,
    AnchorKind,
    AnchorMatch,
    DurableTarget,
    HealStrategy,
    SurfaceKind,
    TierRecord,
    compute_target_id,
)

# ---------------------------------------------------------------------------
# compute_target_id
# ---------------------------------------------------------------------------


class TestComputeTargetId:
    def test_stable(self):
        """Same inputs → same ID."""
        a = compute_target_id("click login", "browser", "example.com")
        b = compute_target_id("click login", "browser", "example.com")
        assert a == b

    def test_case_insensitive_intent(self):
        """Intent is case-insensitive."""
        a = compute_target_id("Click Login", "browser", "example.com")
        b = compute_target_id("click login", "browser", "example.com")
        assert a == b

    def test_whitespace_normalized(self):
        a = compute_target_id("  click login  ", "browser", "example.com")
        b = compute_target_id("click login", "browser", "example.com")
        assert a == b

    def test_different_surface(self):
        a = compute_target_id("click login", "browser", "example.com")
        b = compute_target_id("click login", "desktop", "example.com")
        assert a != b

    def test_different_domain(self):
        a = compute_target_id("click login", "browser", "example.com")
        b = compute_target_id("click login", "browser", "other.com")
        assert a != b

    def test_different_intent(self):
        a = compute_target_id("click login", "browser", "example.com")
        b = compute_target_id("click signup", "browser", "example.com")
        assert a != b

    def test_length(self):
        tid = compute_target_id("click login", "browser", "example.com")
        assert len(tid) == 16


# ---------------------------------------------------------------------------
# TierRecord
# ---------------------------------------------------------------------------


class TestTierRecord:
    def test_creation(self):
        record = TierRecord(
            tier="selector", outcome="success", duration_ms=50.0,
            anchor_used="selector",
        )
        assert record.tier == "selector"
        assert record.outcome == "success"
        assert record.duration_ms == 50.0
        assert record.anchor_used == "selector"
        assert record.error is None
        assert record.timestamp > 0

    def test_with_error(self):
        record = TierRecord(
            tier="vision", outcome="failed", duration_ms=200.0,
            anchor_used="visual_fingerprint", error="timeout",
        )
        assert record.error == "timeout"


# ---------------------------------------------------------------------------
# DurableTarget
# ---------------------------------------------------------------------------


class TestDurableTarget:
    def _make_target(self, **overrides) -> DurableTarget:
        defaults = {
            "target_id": "abc123",
            "intent": "click login",
            "surface": "browser",
            "domain": "example.com",
        }
        defaults.update(overrides)
        return DurableTarget(**defaults)

    def test_reliability_no_data(self):
        t = self._make_target()
        assert t.reliability == 0.5

    def test_reliability_perfect(self):
        t = self._make_target(success_count=10, fail_count=0)
        assert t.reliability == 1.0

    def test_reliability_terrible(self):
        t = self._make_target(success_count=0, fail_count=10)
        assert t.reliability == 0.0

    def test_reliability_mixed(self):
        t = self._make_target(success_count=7, fail_count=3)
        assert t.reliability == 0.7

    def test_is_stale_few_records(self):
        t = self._make_target()
        assert t.is_stale is False

    def test_is_stale_recent_failures(self):
        records = [
            TierRecord("selector", "failed", 10.0, "selector"),
        ] * 3
        t = self._make_target(tier_history=records)
        assert t.is_stale is True

    def test_is_stale_mixed_recent(self):
        records = [
            TierRecord("selector", "success", 10.0, "selector"),
            TierRecord("selector", "failed", 10.0, "selector"),
            TierRecord("selector", "failed", 10.0, "selector"),
        ]
        t = self._make_target(tier_history=records)
        assert t.is_stale is False  # not all 3 failed

    def test_available_anchors_empty(self):
        t = self._make_target()
        assert t.available_anchors == []

    def test_available_anchors_with_data(self):
        t = self._make_target(
            selector="button.login",
            uia_name="Login",
            nearby_text=["Email", "Password"],
        )
        kinds = t.available_anchors
        assert AnchorKind.SELECTOR in kinds
        assert AnchorKind.UIA_NAME in kinds
        assert AnchorKind.NEARBY_TEXT in kinds

    def test_best_anchor_no_history(self):
        t = self._make_target(selector="button.login")
        assert t.best_anchor == AnchorKind.SELECTOR

    def test_best_anchor_from_history(self):
        records = [
            TierRecord("vision", "failed", 100.0, "visual_fingerprint"),
            TierRecord("selector", "success", 10.0, "selector"),
        ]
        t = self._make_target(selector="button.login", tier_history=records)
        assert t.best_anchor == AnchorKind.SELECTOR

    def test_to_dict_and_back(self):
        t = self._make_target(
            selector="button.login",
            success_count=5,
            nearby_text=["Email"],
        )
        d = t.to_dict()
        assert d["selector"] == "button.login"
        assert d["success_count"] == 5

        t2 = DurableTarget.from_dict(d)
        assert t2.target_id == t.target_id
        assert t2.selector == t.selector
        assert t2.success_count == t.success_count
        assert t2.nearby_text == t.nearby_text

    def test_to_dict_preserves_tier_history(self):
        records = [
            TierRecord("selector", "success", 10.0, "selector"),
            TierRecord("vision", "failed", 100.0, "visual_fingerprint"),
        ]
        t = self._make_target(tier_history=records)
        d = t.to_dict()
        assert len(d["tier_history"]) == 2
        assert d["tier_history"][0]["tier"] == "selector"

    def test_from_dict_ignores_unknown_fields(self):
        d = {
            "target_id": "abc",
            "intent": "click",
            "surface": "browser",
            "domain": "test.com",
            "unknown_field": "should be ignored",
        }
        t = DurableTarget.from_dict(d)
        assert t.target_id == "abc"
        assert not hasattr(t, "unknown_field") or getattr(t, "unknown_field", None) is None


# ---------------------------------------------------------------------------
# ActionEvidence
# ---------------------------------------------------------------------------


class TestActionEvidence:
    def test_minimal(self):
        e = ActionEvidence(action="click", target_description="login button")
        assert e.action == "click"
        assert e.surface == "browser"
        assert e.succeeded is False

    def test_full(self):
        e = ActionEvidence(
            action="fill",
            target_description="email input",
            surface="desktop",
            domain="example.com",
            selector="input[type='email']",
            uia_name="Email",
            visual_fingerprint="abcd1234",
            bbox_normalized=(0.1, 0.2, 0.3, 0.05),
            nearby_text=["Password", "Submit"],
            ocr_text="Email",
            successful_tier="selector",
            succeeded=True,
            duration_ms=50.0,
        )
        assert e.selector == "input[type='email']"
        assert e.bbox_normalized == (0.1, 0.2, 0.3, 0.05)
        assert len(e.nearby_text) == 2


# ---------------------------------------------------------------------------
# AnchorMatch
# ---------------------------------------------------------------------------


class TestAnchorMatch:
    def test_creation(self):
        m = AnchorMatch(
            target_id="abc123",
            anchor_kind=AnchorKind.SELECTOR,
            anchor_value="button.login",
            confidence=0.95,
        )
        assert m.healed is False
        assert m.strategy is None

    def test_healed_match(self):
        m = AnchorMatch(
            target_id="abc123",
            anchor_kind=AnchorKind.UIA_NAME,
            anchor_value="Login",
            confidence=0.85,
            strategy=HealStrategy.AX_ROLE_TEXT,
            healed=True,
        )
        assert m.healed is True
        assert m.strategy == HealStrategy.AX_ROLE_TEXT


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_surface_kinds(self):
        assert SurfaceKind.BROWSER.value == "browser"
        assert SurfaceKind.DESKTOP.value == "desktop"

    def test_anchor_kinds(self):
        assert len(AnchorKind) >= 8

    def test_heal_strategies(self):
        assert len(HealStrategy) >= 4
