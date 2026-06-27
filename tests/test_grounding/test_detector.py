"""Tests for YOLO detector — tiled inference logic (mocked)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.grounding.detector import OmniParserDetector
from deskaoy.grounding.types import BBox, Detection, DetectionSource, ElementRole


def _png_bytes(w: int = 200, h: int = 200) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


class TestOmniParserDetectorAvailability:

    def test_available_reflects_yolo(self):
        det = OmniParserDetector()
        # ultralytics may or may not be installed
        assert isinstance(det.available, bool)


class TestClassifyRole:

    def test_button(self):
        assert OmniParserDetector._classify_role("button") == ElementRole.BUTTON

    def test_input(self):
        assert OmniParserDetector._classify_role("input field") == ElementRole.INPUT

    def test_unknown(self):
        assert OmniParserDetector._classify_role("mystery widget") == ElementRole.OTHER

    def test_case_insensitive(self):
        assert OmniParserDetector._classify_role("BUTTON") == ElementRole.BUTTON


class TestNMS:

    def test_empty(self):
        assert OmniParserDetector._nms([], 0.5) == []

    def test_no_overlap(self):
        dets = [
            Detection(BBox(0, 0, 50, 50), 0.9, source=DetectionSource.VISUAL_YOLO),
            Detection(BBox(100, 100, 150, 150), 0.8, source=DetectionSource.VISUAL_YOLO),
        ]
        result = OmniParserDetector._nms(dets, 0.5)
        assert len(result) == 2

    def test_overlapping_removes_low_conf(self):
        dets = [
            Detection(BBox(0, 0, 100, 100), 0.9, source=DetectionSource.VISUAL_YOLO),
            Detection(BBox(10, 10, 90, 90), 0.5, source=DetectionSource.VISUAL_YOLO),
        ]
        result = OmniParserDetector._nms(dets, 0.4)
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_preserves_order_by_confidence(self):
        dets = [
            Detection(BBox(0, 0, 50, 50), 0.5, source=DetectionSource.VISUAL_YOLO),
            Detection(BBox(100, 0, 150, 50), 0.9, source=DetectionSource.VISUAL_YOLO),
        ]
        result = OmniParserDetector._nms(dets, 0.5)
        assert len(result) == 2
        assert result[0].confidence == 0.9  # sorted desc


class TestDetectMocked:
    """Tests with mocked YOLO model (no ML deps needed)."""

    async def test_detect_returns_empty_without_yolo(self):
        det = OmniParserDetector()
        if det.available:
            pytest.skip("YOLO installed — can't test fallback")
        result = await det.detect(_png_bytes())
        assert result == []

    async def test_detect_single_image(self):
        det = OmniParserDetector()
        # Mock the model
        mock_result = MagicMock()
        mock_result.boxes = MagicMock()
        box = MagicMock()
        box.xyxy = MagicMock()
        box.xyxy.__getitem__ = lambda s, i: MagicMock(
            cpu=lambda: MagicMock(
                numpy=lambda: [10.0, 20.0, 100.0, 50.0]
            )
        )
        box.conf = [0.85]
        box.cls = [0]
        mock_result.boxes = [box]
        mock_result.names = {0: "button"}

        det._model = MagicMock(return_value=[mock_result])

        with patch("deskaoy.grounding.detector._HAS_YOLO", True):
            result = await det.detect(_png_bytes(200, 200))
        assert len(result) == 1
        assert result[0].label == "button"
        assert result[0].role == ElementRole.BUTTON
        assert result[0].bbox.x1 == 10.0

    async def test_detect_tiled_large_image(self):
        det = OmniParserDetector()
        mock_result = MagicMock()
        mock_result.boxes = []  # no detections in tiles
        mock_result.names = {}
        det._model = MagicMock(return_value=[mock_result])

        with patch("deskaoy.grounding.detector._HAS_YOLO", True):
            result = await det.detect(_png_bytes(1200, 900))
        # Model called multiple times for tiles
        assert det._model.call_count > 1
        assert result == []
