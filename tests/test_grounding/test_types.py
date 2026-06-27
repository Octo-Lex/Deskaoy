"""Tests for grounding types — BBox, Detection, FusedElement, GroundingResult."""

from __future__ import annotations

import pytest

from deskaoy.grounding.types import (
    BBox,
    Detection,
    DetectionSource,
    ElementRole,
    FrameDelta,
    FusedElement,
    GroundingResult,
)

# ---------------------------------------------------------------------------
# BBox
# ---------------------------------------------------------------------------

class TestBBox:

    def test_width_height(self):
        b = BBox(10, 20, 110, 70)
        assert b.width == 100
        assert b.height == 50

    def test_area(self):
        b = BBox(0, 0, 100, 50)
        assert b.area == 5000

    def test_area_zero_size(self):
        assert BBox(10, 10, 10, 10).area == 0
        assert BBox(10, 10, 5, 5).area == 0  # inverted

    def test_center(self):
        b = BBox(0, 0, 100, 50)
        assert b.center == (50, 25)

    def test_iou_perfect_overlap(self):
        a = BBox(0, 0, 100, 100)
        assert a.iou(a) == pytest.approx(1.0)

    def test_iou_half_overlap(self):
        a = BBox(0, 0, 100, 100)
        b = BBox(50, 0, 150, 100)
        # intersection = 50*100 = 5000, union = 10000+10000-5000 = 15000
        assert a.iou(b) == pytest.approx(5000 / 15000)

    def test_iou_no_overlap(self):
        a = BBox(0, 0, 50, 50)
        b = BBox(100, 100, 200, 200)
        assert a.iou(b) == 0.0

    def test_iou_contained(self):
        outer = BBox(0, 0, 100, 100)
        inner = BBox(25, 25, 75, 75)
        # intersection = 50*50 = 2500, union = 10000+2500-2500 = 10000
        assert outer.iou(inner) == pytest.approx(2500 / 10000)

    def test_iou_symmetric(self):
        a = BBox(0, 0, 100, 50)
        b = BBox(30, 10, 80, 60)
        assert a.iou(b) == pytest.approx(b.iou(a))

    def test_contains(self):
        outer = BBox(0, 0, 100, 100)
        inner = BBox(10, 10, 90, 90)
        assert outer.contains(inner)
        assert not inner.contains(outer)

    def test_contains_edge_touch(self):
        outer = BBox(0, 0, 100, 100)
        edge = BBox(0, 0, 100, 100)
        assert outer.contains(edge)

    def test_normalized(self):
        b = BBox(100, 200, 300, 400)
        n = b.normalized(1000, 1000)
        assert n.x1 == pytest.approx(0.1)
        assert n.y2 == pytest.approx(0.4)

    def test_scaled(self):
        b = BBox(10, 20, 30, 40)
        s = b.scaled(2.0)
        assert s.x1 == 20 and s.x2 == 60

    def test_clamp(self):
        b = BBox(-10, -5, 1100, 900)
        c = b.clamp(1000, 800)
        assert c.x1 == 0 and c.y1 == 0
        assert c.x2 == 1000 and c.y2 == 800


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

class TestDetection:

    def test_defaults(self):
        d = Detection(bbox=BBox(0, 0, 10, 10), confidence=0.8)
        assert d.label == ""
        assert d.role == ElementRole.OTHER
        assert d.source == DetectionSource.VISUAL_YOLO
        assert d.text is None

    def test_with_text(self):
        d = Detection(
            bbox=BBox(0, 0, 50, 20),
            confidence=0.9,
            text="Submit",
            source=DetectionSource.VISUAL_OCR,
        )
        assert d.text == "Submit"


# ---------------------------------------------------------------------------
# FusedElement
# ---------------------------------------------------------------------------

class TestFusedElement:

    def test_center_delegates(self):
        el = FusedElement(
            bbox=BBox(0, 0, 100, 50),
            role=ElementRole.BUTTON,
            label="OK",
            confidence=0.9,
        )
        assert el.center == (50, 25)

    def test_sources_tuple(self):
        el = FusedElement(
            bbox=BBox(0, 0, 10, 10),
            role=ElementRole.ICON,
            label="close",
            confidence=0.7,
            sources=(DetectionSource.VISUAL_YOLO, DetectionSource.VISUAL_OCR),
        )
        assert len(el.sources) == 2


# ---------------------------------------------------------------------------
# GroundingResult
# ---------------------------------------------------------------------------

class TestGroundingResult:

    def _make_result(self) -> GroundingResult:
        elements = [
            FusedElement(BBox(0, 0, 50, 20), ElementRole.BUTTON, "Submit", 0.9),
            FusedElement(BBox(0, 30, 50, 50), ElementRole.INPUT, "Email", 0.8),
            FusedElement(BBox(0, 60, 80, 80), ElementRole.TEXT, "Hello World", 0.7, text="Hello World"),
        ]
        return GroundingResult(elements=elements, viewport_size=(1920, 1080))

    def test_total(self):
        r = self._make_result()
        assert r.total == 3

    def test_find_by_text(self):
        r = self._make_result()
        matches = r.find_by_text("submit")
        assert len(matches) == 1
        assert matches[0].label == "Submit"

    def test_find_by_text_case_insensitive(self):
        r = self._make_result()
        assert len(r.find_by_text("SUBMIT")) == 1

    def test_find_by_text_case_sensitive(self):
        r = self._make_result()
        assert len(r.find_by_text("Submit", case_sensitive=True)) == 1
        assert len(r.find_by_text("submit", case_sensitive=True)) == 0

    def test_find_by_text_in_text_field(self):
        r = self._make_result()
        matches = r.find_by_text("hello")
        assert len(matches) == 1  # matches the text field

    def test_find_by_role(self):
        r = self._make_result()
        buttons = r.find_by_role(ElementRole.BUTTON)
        assert len(buttons) == 1

    def test_best_match(self):
        r = self._make_result()
        m = r.best_match("submit")
        assert m is not None
        assert m.label == "Submit"

    def test_best_match_none(self):
        r = self._make_result()
        assert r.best_match("nonexistent") is None

    def test_best_match_picks_highest_confidence(self):
        r = GroundingResult(elements=[
            FusedElement(BBox(0, 0, 50, 20), ElementRole.BUTTON, "Submit form", 0.5),
            FusedElement(BBox(0, 30, 50, 50), ElementRole.BUTTON, "Submit order", 0.9),
        ])
        m = r.best_match("submit")
        assert m is not None
        assert m.confidence == 0.9


# ---------------------------------------------------------------------------
# FrameDelta
# ---------------------------------------------------------------------------

class TestFrameDelta:

    def test_empty(self):
        d = FrameDelta(stable=[], appeared=[], disappeared=[])
        assert len(d.stable) == 0


# ---------------------------------------------------------------------------
# ElementRole / DetectionSource
# ---------------------------------------------------------------------------

class TestEnums:

    def test_element_roles(self):
        assert ElementRole.BUTTON.value == "button"
        assert ElementRole.OTHER.value == "other"

    def test_detection_sources(self):
        assert DetectionSource.STRUCTURAL.value == "structural"
        assert DetectionSource.FUSED.value == "fused"
