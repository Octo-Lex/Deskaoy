"""Tests for anchor computation and cross-frame tracking."""

from __future__ import annotations

from deskaoy.grounding.anchor import build_anchor_map, compute_anchor
from deskaoy.grounding.tracker import track_frames
from deskaoy.grounding.types import (
    BBox,
    DetectionSource,
    ElementRole,
    FusedElement,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _el(
    x1: float, y1: float, x2: float, y2: float,
    *,
    label: str = "OK",
    role: ElementRole = ElementRole.BUTTON,
    source: DetectionSource = DetectionSource.FUSED,
    anchor_id: str | None = None,
) -> FusedElement:
    return FusedElement(
        bbox=BBox(x1, y1, x2, y2),
        role=role,
        label=label,
        confidence=0.8,
        source=source,
        anchor_id=anchor_id,
    )


# ---------------------------------------------------------------------------
# Anchor computation
# ---------------------------------------------------------------------------

class TestComputeAnchor:

    def test_deterministic(self):
        el = _el(0, 0, 100, 50, label="Submit")
        a = compute_anchor(el, 1920, 1080)
        b = compute_anchor(el, 1920, 1080)
        assert a == b

    def test_same_role_label_position_same_anchor(self):
        el1 = _el(100, 200, 200, 250, label="OK")
        el2 = _el(100, 200, 200, 250, label="OK")
        assert compute_anchor(el1, 1920, 1080) == compute_anchor(el2, 1920, 1080)

    def test_different_role_different_anchor(self):
        el1 = _el(100, 200, 200, 250, label="OK", role=ElementRole.BUTTON)
        el2 = _el(100, 200, 200, 250, label="OK", role=ElementRole.INPUT)
        assert compute_anchor(el1, 1920, 1080) != compute_anchor(el2, 1920, 1080)

    def test_different_label_different_anchor(self):
        el1 = _el(100, 200, 200, 250, label="OK")
        el2 = _el(100, 200, 200, 250, label="Cancel")
        assert compute_anchor(el1, 1920, 1080) != compute_anchor(el2, 1920, 1080)

    def test_different_position_different_anchor(self):
        el1 = _el(100, 200, 200, 250, label="OK")
        el2 = _el(300, 400, 400, 450, label="OK")
        assert compute_anchor(el1, 1920, 1080) != compute_anchor(el2, 1920, 1080)

    def test_minor_position_shift_same_anchor(self):
        """Positions quantized to 20px grid — sub-grid shift should not change anchor."""
        el1 = _el(100, 200, 200, 250, label="OK")
        el2 = _el(101, 201, 201, 251, label="OK")  # 1px shift
        assert compute_anchor(el1, 1920, 1080) == compute_anchor(el2, 1920, 1080)

    def test_major_position_shift_different_anchor(self):
        el1 = _el(100, 200, 200, 250, label="OK")
        el2 = _el(150, 250, 250, 300, label="OK")  # 50px shift
        assert compute_anchor(el1, 1920, 1080) != compute_anchor(el2, 1920, 1080)

    def test_case_insensitive_label(self):
        el1 = _el(100, 200, 200, 250, label="Submit")
        el2 = _el(100, 200, 200, 250, label="submit")
        assert compute_anchor(el1, 1920, 1080) == compute_anchor(el2, 1920, 1080)


# ---------------------------------------------------------------------------
# Anchor map
# ---------------------------------------------------------------------------

class TestBuildAnchorMap:

    def test_builds_map(self):
        elements = [
            _el(0, 0, 50, 20, label="A"),
            _el(100, 100, 150, 120, label="B"),
        ]
        amap = build_anchor_map(elements, 1920, 1080)
        assert len(amap) == 2
        for el in amap.values():
            assert el.anchor_id is not None

    def test_duplicate_anchor_first_wins(self):
        elements = [
            _el(0, 0, 50, 20, label="X"),
            _el(0, 0, 50, 20, label="X"),  # same anchor
        ]
        amap = build_anchor_map(elements, 1920, 1080)
        assert len(amap) == 1

    def test_empty(self):
        assert build_anchor_map([], 1920, 1080) == {}


# ---------------------------------------------------------------------------
# Cross-frame tracking
# ---------------------------------------------------------------------------

class TestTrackFrames:

    def test_all_stable(self):
        prev = [_el(0, 0, 100, 50, label="OK")]
        curr = [_el(0, 0, 100, 50, label="OK")]
        delta = track_frames(prev, curr, 1920, 1080)
        assert len(delta.stable) == 1
        assert len(delta.appeared) == 0
        assert len(delta.disappeared) == 0

    def test_appeared(self):
        prev = [_el(0, 0, 100, 50, label="OK")]
        curr = [
            _el(0, 0, 100, 50, label="OK"),
            _el(200, 200, 300, 250, label="New"),
        ]
        delta = track_frames(prev, curr, 1920, 1080)
        assert len(delta.stable) == 1
        assert len(delta.appeared) == 1
        assert len(delta.disappeared) == 0

    def test_disappeared(self):
        prev = [
            _el(0, 0, 100, 50, label="OK"),
            _el(200, 200, 300, 250, label="Gone"),
        ]
        curr = [_el(0, 0, 100, 50, label="OK")]
        delta = track_frames(prev, curr, 1920, 1080)
        assert len(delta.stable) == 1
        assert len(delta.appeared) == 0
        assert len(delta.disappeared) == 1

    def test_complete_turnover(self):
        prev = [_el(0, 0, 100, 50, label="Old")]
        curr = [_el(500, 500, 600, 550, label="New")]
        delta = track_frames(prev, curr, 1920, 1080)
        assert len(delta.stable) == 0
        assert len(delta.appeared) == 1
        assert len(delta.disappeared) == 1

    def test_empty_frames(self):
        delta = track_frames([], [], 1920, 1080)
        assert len(delta.stable) == 0
        assert len(delta.appeared) == 0
        assert len(delta.disappeared) == 0

    def test_minor_shift_still_stable(self):
        prev = [_el(100, 200, 200, 250, label="OK")]
        curr = [_el(103, 203, 203, 253, label="OK")]  # 3px shift
        delta = track_frames(prev, curr, 1920, 1080)
        assert len(delta.stable) == 1
