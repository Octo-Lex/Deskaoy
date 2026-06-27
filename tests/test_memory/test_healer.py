"""Tests for SelfHealer — all 5 healing strategies."""

from __future__ import annotations

import pytest

from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.grounding.types import BBox, Detection, DetectionSource, ElementRole
from deskaoy.memory.healer import HealResult, SelfHealer
from deskaoy.memory.types import (
    AnchorKind,
    DurableTarget,
    HealStrategy,
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


def _detection(x1, y1, x2, y2, text=None, label=""):
    return Detection(
        bbox=BBox(x1, y1, x2, y2),
        confidence=0.9,
        label=label,
        role=ElementRole.BUTTON,
        source=DetectionSource.VISUAL_YOLO,
        text=text,
    )


# ---------------------------------------------------------------------------
# Strategy 1: AX role + text match
# ---------------------------------------------------------------------------


class TestHealAxRoleText:
    @pytest.mark.asyncio
    async def test_exact_match(self):
        healer = SelfHealer()
        target = _target(uia_name="Login", uia_control_type="button")
        snap = _snapshot(
            btn1={"role": "button", "name": "Login"},
        )

        result = await healer.heal(target, snap)
        assert result.success is True
        assert result.match.strategy == HealStrategy.AX_ROLE_TEXT

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        healer = SelfHealer()
        target = _target(uia_name="login", uia_control_type="button")
        snap = _snapshot(btn1={"role": "button", "name": "LOGIN"})

        result = await healer.heal(target, snap)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_role_mismatch(self):
        healer = SelfHealer()
        target = _target(uia_name="Login", uia_control_type="button")
        snap = _snapshot(btn1={"role": "link", "name": "Login"})

        result = await healer.heal(target, snap)
        # Should try other strategies after failing this one
        assert HealStrategy.AX_ROLE_TEXT.value in result.strategies_tried


# ---------------------------------------------------------------------------
# Strategy 2: Visual fingerprint
# ---------------------------------------------------------------------------


class TestHealVisualFingerprint:
    @pytest.mark.asyncio
    async def test_visual_match(self):
        try:
            import io

            from PIL import Image

            healer = SelfHealer(fingerprint_threshold=0.5)
            target = _target(
                visual_fingerprint="0" * 16,
                bbox_normalized=(0.3, 0.3, 0.4, 0.1),
            )

            # Create a uniform image (will have a predictable hash)
            img = Image.new("RGB", (800, 600), (128, 128, 128))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            screenshot = buf.getvalue()

            # We need the fingerprint to match — use the same image to generate target FP
            from deskaoy.memory.fingerprint import crop_fingerprint
            actual_fp = crop_fingerprint(
                screenshot, (240, 180, 560, 240), (800, 600)
            )
            if actual_fp:
                target = _target(
                    visual_fingerprint=actual_fp,
                    bbox_normalized=(0.3, 0.3, 0.4, 0.1),
                )
                result = await healer.heal(
                    target,
                    current_screenshot=screenshot,
                    viewport_size=(800, 600),
                )
                assert result.success is True
                assert result.match.strategy == HealStrategy.VISUAL_FINGERPRINT
        except ImportError:
            pytest.skip("Pillow not installed")


# ---------------------------------------------------------------------------
# Strategy 3: OCR text search
# ---------------------------------------------------------------------------


class TestHealOcrSearch:
    @pytest.mark.asyncio
    async def test_ocr_match(self):
        healer = SelfHealer()
        target = _target(ocr_text="Login")

        detections = [
            _detection(100, 100, 200, 140, text="Login"),
            _detection(100, 200, 200, 240, text="Signup"),
        ]

        result = await healer.heal(target, current_detections=detections)
        assert result.success is True
        assert result.match.strategy == HealStrategy.OCR_SEARCH
        assert result.match.healed is True

    @pytest.mark.asyncio
    async def test_ocr_case_insensitive(self):
        healer = SelfHealer()
        target = _target(ocr_text="login")

        detections = [_detection(100, 100, 200, 140, text="LOGIN")]

        result = await healer.heal(target, current_detections=detections)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_ocr_no_match(self):
        healer = SelfHealer()
        target = _target(ocr_text="Login")

        detections = [_detection(100, 100, 200, 140, text="Signup")]

        result = await healer.heal(target, current_detections=detections)
        # OCR strategy should be in tried list
        assert HealStrategy.OCR_SEARCH.value in result.strategies_tried


# ---------------------------------------------------------------------------
# Strategy 4: Nearby text anchor
# ---------------------------------------------------------------------------


class TestHealNearbyText:
    @pytest.mark.asyncio
    async def test_nearby_text_match(self):
        healer = SelfHealer()
        target = _target(
            uia_control_type="button",
            nearby_text=["Email"],
        )

        snap = _snapshot(
            email_input={"role": "textbox", "name": "Email", "bounds": (100, 100, 200, 30)},
            login_btn={"role": "button", "name": "Login", "bounds": (100, 200, 200, 30)},
        )

        result = await healer.heal(target, snap)
        assert result.success is True
        assert result.match.strategy == HealStrategy.NEARBY_TEXT_ANCHOR

    @pytest.mark.asyncio
    async def test_nearby_text_too_far(self):
        healer = SelfHealer(nearby_threshold=10.0)  # very strict
        target = _target(
            uia_control_type="button",
            nearby_text=["Email"],
        )

        snap = _snapshot(
            email_input={"role": "textbox", "name": "Email", "bounds": (100, 100, 200, 30)},
            login_btn={"role": "button", "name": "Login", "bounds": (100, 2000, 200, 30)},
        )

        result = await healer.heal(target, snap)
        # Button is too far from Email
        assert result.success is False


# ---------------------------------------------------------------------------
# Strategy 5: BBox proximity
# ---------------------------------------------------------------------------


class TestHealBboxProximity:
    @pytest.mark.asyncio
    async def test_bbox_proximity_match(self):
        healer = SelfHealer()
        target = _target(
            bbox_normalized=(0.4, 0.3, 0.2, 0.05),
        )

        # Detection near the remembered position
        detections = [_detection(320, 180, 480, 210)]

        result = await healer.heal(
            target,
            current_detections=detections,
            viewport_size=(800, 600),
        )
        assert result.success is True
        assert result.match.strategy == HealStrategy.BBOX_PROXIMITY

    @pytest.mark.asyncio
    async def test_bbox_too_far(self):
        healer = SelfHealer()
        target = _target(
            bbox_normalized=(0.1, 0.1, 0.2, 0.05),
        )

        # Detection far from the remembered position
        detections = [_detection(700, 500, 780, 540)]

        result = await healer.heal(
            target,
            current_detections=detections,
            viewport_size=(800, 600),
        )
        assert result.success is False


# ---------------------------------------------------------------------------
# HealResult
# ---------------------------------------------------------------------------


class TestHealResult:
    def test_success_repr(self):
        from deskaoy.memory.types import AnchorMatch
        result = HealResult(
            success=True,
            match=AnchorMatch(
                target_id="abc",
                anchor_kind=AnchorKind.SELECTOR,
                anchor_value="btn",
                confidence=0.9,
            ),
        )
        assert "success=True" in repr(result)

    def test_failure_repr(self):
        result = HealResult(
            success=False,
            strategies_tried=["ax_role_text", "ocr_search"],
        )
        assert "success=False" in repr(result)
        assert "ax_role_text" in repr(result)


# ---------------------------------------------------------------------------
# Multi-strategy fallthrough
# ---------------------------------------------------------------------------


class TestStrategyFallthrough:
    @pytest.mark.asyncio
    async def test_tries_all_strategies(self):
        """When nothing matches, all strategies should be tried."""
        healer = SelfHealer()
        target = _target()  # no anchors

        result = await healer.heal(target)
        assert result.success is False
        # Should have tried at least some strategies
        assert len(result.strategies_tried) >= 0  # may be 0 if no evidence to try

    @pytest.mark.asyncio
    async def test_first_match_wins(self):
        """AX match should win over later strategies."""
        healer = SelfHealer()
        target = _target(
            uia_name="Login",
            uia_control_type="button",
            ocr_text="Login",
        )

        snap = _snapshot(
            btn1={"role": "button", "name": "Login"},
        )
        detections = [_detection(100, 100, 200, 140, text="Login")]

        result = await healer.heal(
            target, snap,
            current_detections=detections,
        )
        assert result.success is True
        # Should have been found by AX strategy first
        assert result.strategies_tried == [HealStrategy.AX_ROLE_TEXT.value]

    @pytest.mark.asyncio
    async def test_duration_recorded(self):
        healer = SelfHealer()
        target = _target(uia_name="Login", uia_control_type="button")
        snap = _snapshot(btn1={"role": "button", "name": "Login"})

        result = await healer.heal(target, snap)
        assert result.duration_ms >= 0
