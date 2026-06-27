"""Tests for fusion engine — IoU dedup, structural priority, NMS."""

from __future__ import annotations

from deskaoy.grounding.fusion import FusionEngine
from deskaoy.grounding.types import (
    BBox,
    Detection,
    DetectionSource,
    ElementRole,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _det(
    x1: float, y1: float, x2: float, y2: float,
    *,
    label: str = "",
    confidence: float = 0.8,
    source: DetectionSource = DetectionSource.VISUAL_YOLO,
    role: ElementRole = ElementRole.OTHER,
    text: str | None = None,
) -> Detection:
    return Detection(
        bbox=BBox(x1, y1, x2, y2),
        confidence=confidence,
        label=label,
        source=source,
        role=role,
        text=text,
    )


def _structural(x1, y1, x2, y2, label="", role=ElementRole.OTHER, text=None, conf=0.9):
    return _det(x1, y1, x2, y2, label=label, confidence=conf,
                source=DetectionSource.STRUCTURAL, role=role, text=text)


def _visual(x1, y1, x2, y2, label="", conf=0.7, role=ElementRole.OTHER):
    return _det(x1, y1, x2, y2, label=label, confidence=conf,
                source=DetectionSource.VISUAL_YOLO, role=role)


def _ocr(x1, y1, x2, y2, text, conf=0.85):
    return _det(x1, y1, x2, y2, label=text, confidence=conf,
                source=DetectionSource.VISUAL_OCR, text=text, role=ElementRole.TEXT)


# ---------------------------------------------------------------------------
# Structural priority
# ---------------------------------------------------------------------------

class TestStructuralPriority:

    async def test_structural_wins_over_visual(self):
        """When structural and visual overlap, structural wins."""
        engine = FusionEngine()
        result = engine.fuse(
            structural=[_structural(0, 0, 100, 50, "Button", ElementRole.BUTTON)],
            visual=[_visual(2, 2, 98, 48, "btn")],
        )
        assert len(result) == 1
        assert result[0].source == DetectionSource.STRUCTURAL
        assert result[0].label == "Button"

    async def test_structural_gets_high_confidence(self):
        engine = FusionEngine()
        result = engine.fuse(
            structural=[_structural(0, 0, 100, 50, "Link", conf=0.5)],
        )
        assert result[0].confidence >= 0.9  # boosted to _STRUCTURAL_CONF

    async def test_multiple_structural_no_dedup(self):
        engine = FusionEngine()
        result = engine.fuse(
            structural=[
                _structural(0, 0, 100, 50, "A"),
                _structural(0, 60, 100, 110, "B"),
            ],
        )
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Visual dedup
# ---------------------------------------------------------------------------

class TestVisualDedup:

    async def test_visual_no_overlap(self):
        engine = FusionEngine()
        result = engine.fuse(
            visual=[
                _visual(0, 0, 50, 50, "A"),
                _visual(100, 100, 150, 150, "B"),
            ],
        )
        assert len(result) == 2

    async def test_visual_nms_removes_low_confidence(self):
        engine = FusionEngine()
        result = engine.fuse(
            visual=[
                _visual(0, 0, 100, 100, "A", conf=0.9),
                _visual(5, 5, 95, 95, "B", conf=0.5),  # overlaps A
            ],
        )
        assert len(result) == 1
        assert result[0].label == "A"

    async def test_visual_not_deduped_when_structural_exists(self):
        engine = FusionEngine()
        result = engine.fuse(
            structural=[_structural(0, 0, 100, 50, "S")],
            visual=[_visual(2, 2, 98, 48, "V")],  # overlaps structural
        )
        # Only structural survives
        assert len(result) == 1
        assert result[0].source == DetectionSource.STRUCTURAL


# ---------------------------------------------------------------------------
# OCR text assignment
# ---------------------------------------------------------------------------

class TestOCRAssignment:

    async def test_ocr_text_assigned_to_visual(self):
        engine = FusionEngine()
        result = engine.fuse(
            visual=[_visual(0, 0, 100, 30)],
            text=[_ocr(2, 2, 98, 28, "Submit")],
        )
        assert len(result) == 1
        assert result[0].text == "Submit"
        assert DetectionSource.VISUAL_OCR in result[0].sources

    async def test_ocr_inside_visual_gets_assigned(self):
        engine = FusionEngine()
        result = engine.fuse(
            visual=[_visual(0, 0, 100, 30)],
            text=[_ocr(10, 5, 50, 25, "Click")],  # inside visual box
        )
        assert len(result) == 1
        assert result[0].text == "Click"

    async def test_ocr_only_not_overlapping_visual(self):
        engine = FusionEngine()
        result = engine.fuse(
            text=[_ocr(0, 0, 100, 30, "Hello")],
        )
        assert len(result) == 1
        assert result[0].role == ElementRole.TEXT
        assert result[0].text == "Hello"

    async def test_ocr_deduped_against_structural(self):
        engine = FusionEngine()
        result = engine.fuse(
            structural=[_structural(0, 0, 100, 30, "Label")],
            text=[_ocr(2, 2, 98, 28, "Label")],
        )
        # OCR overlaps structural — should not produce a second element
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    async def test_empty_inputs(self):
        engine = FusionEngine()
        assert engine.fuse() == []
        assert engine.fuse(structural=[], visual=[], text=[]) == []

    async def test_none_inputs(self):
        engine = FusionEngine()
        assert engine.fuse(structural=None, visual=None, text=None) == []

    async def test_zero_area_bbox(self):
        engine = FusionEngine()
        result = engine.fuse(
            visual=[_visual(50, 50, 50, 50, "zero")],
        )
        assert len(result) == 1  # zero-area still included

    async def test_custom_iou_threshold(self):
        engine = FusionEngine(iou_threshold=0.8)
        # 70% overlap — below 0.8 threshold, both survive
        result = engine.fuse(
            visual=[
                _visual(0, 0, 100, 100, "A", conf=0.9),
                _visual(30, 0, 130, 100, "B", conf=0.5),
            ],
        )
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Three-source fusion
# ---------------------------------------------------------------------------

class TestThreeSourceFusion:

    async def test_full_fusion(self):
        engine = FusionEngine()
        result = engine.fuse(
            structural=[_structural(0, 0, 100, 30, "Nav", ElementRole.BUTTON)],
            visual=[
                _visual(2, 2, 98, 28, "", conf=0.6),  # overlaps structural → deduped
                _visual(0, 50, 80, 80, "icon", conf=0.7),
            ],
            text=[
                _ocr(2, 2, 98, 28, "Nav"),  # overlaps structural → deduped
                _ocr(5, 55, 75, 75, "Search"),  # inside visual → assigned to it
                _ocr(200, 200, 300, 220, "Footer"),  # standalone OCR
            ],
        )
        # Expected: structural Nav + visual icon (with "Search" text) + OCR "Footer"
        assert len(result) == 3
        sources = [r.source for r in result]
        assert DetectionSource.STRUCTURAL in sources
        assert DetectionSource.VISUAL_YOLO in sources
        assert DetectionSource.VISUAL_OCR in sources
