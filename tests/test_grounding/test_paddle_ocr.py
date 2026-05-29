"""Tests for PaddleOCR engine (mocked)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.grounding.types import DetectionSource, ElementRole
from deskaoy.grounding.paddle_ocr import PaddleOCREngine


def _png_bytes(w: int = 200, h: int = 200) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


class TestPaddleOCRAvailability:

    def test_available_reflects_paddle(self):
        ocr = PaddleOCREngine()
        assert isinstance(ocr.available, bool)


class TestDetectTextMocked:

    async def test_returns_empty_without_paddle(self):
        ocr = PaddleOCREngine()
        if ocr.available:
            pytest.skip("PaddleOCR installed — can't test fallback")
        result = await ocr.detect_text(_png_bytes())
        assert result == []

    async def test_parses_ocr_results(self):
        ocr = PaddleOCREngine()
        # Mock the PaddleOCR engine
        mock_ocr = MagicMock()
        mock_ocr.ocr.return_value = [[
            [
                [[10, 20], [100, 20], [100, 50], [10, 50]],  # 4-point polygon
                ["Hello World", 0.92],
            ],
            [
                [[10, 60], [80, 60], [80, 80], [10, 80]],
                ["Click", 0.85],
            ],
        ]]
        ocr._ocr = mock_ocr

        # Patch _HAS_PADDLE to True for this test
        with patch("deskaoy.grounding.paddle_ocr._HAS_PADDLE", True):
            result = await ocr.detect_text(_png_bytes())

        assert len(result) == 2
        assert result[0].text == "Hello World"
        assert result[0].confidence == pytest.approx(0.92)
        assert result[0].role == ElementRole.TEXT
        assert result[0].source == DetectionSource.VISUAL_OCR
        assert result[1].text == "Click"

    async def test_handles_empty_results(self):
        ocr = PaddleOCREngine()
        mock_ocr = MagicMock()
        mock_ocr.ocr.return_value = [[]]
        ocr._ocr = mock_ocr

        with patch("deskaoy.grounding.paddle_ocr._HAS_PADDLE", True):
            result = await ocr.detect_text(_png_bytes())
        assert result == []

    async def test_handles_none_results(self):
        ocr = PaddleOCREngine()
        mock_ocr = MagicMock()
        mock_ocr.ocr.return_value = None
        ocr._ocr = mock_ocr

        with patch("deskaoy.grounding.paddle_ocr._HAS_PADDLE", True):
            result = await ocr.detect_text(_png_bytes())
        assert result == []
