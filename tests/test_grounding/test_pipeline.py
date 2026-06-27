"""Tests for GroundingPipeline orchestrator (all sub-components mocked)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

from deskaoy.cascade.types import VisionRequest, VisionResponse
from deskaoy.grounding.pipeline import GroundingPipeline
from deskaoy.grounding.types import (
    BBox,
    Detection,
    DetectionSource,
    ElementRole,
    FusedElement,
    GroundingResult,
)


def _png_bytes(w: int = 200, h: int = 200) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _fused(label="Button", role=ElementRole.BUTTON, conf=0.9, text=None):
    return FusedElement(
        bbox=BBox(10, 10, 100, 50),
        role=role,
        label=label,
        confidence=conf,
        source=DetectionSource.FUSED,
        text=text,
    )


class TestPipelineProperties:

    def test_name(self):
        p = GroundingPipeline()
        assert p.name == "grounding"

    def test_model_id(self):
        p = GroundingPipeline()
        assert p.model_id == "omniparser-v2"


class TestDetectAll:

    async def test_detect_all_with_mocks(self):
        mock_detector = MagicMock()
        mock_detector.available = True
        mock_detector.detect = AsyncMock(return_value=[
            Detection(BBox(10, 10, 100, 50), 0.8, label="button",
                      role=ElementRole.BUTTON, source=DetectionSource.VISUAL_YOLO),
        ])

        mock_ocr = MagicMock()
        mock_ocr.available = True
        mock_ocr.detect_text = AsyncMock(return_value=[
            Detection(BBox(10, 10, 100, 50), 0.9, label="Submit",
                      role=ElementRole.TEXT, source=DetectionSource.VISUAL_OCR, text="Submit"),
        ])

        mock_captioner = MagicMock()
        mock_captioner.available = True
        mock_captioner.caption_elements = AsyncMock(return_value=[
            _fused(label="Submit button"),
        ])

        p = GroundingPipeline(
            detector=mock_detector,
            ocr=mock_ocr,
            captioner=mock_captioner,
        )

        result = await p.detect_all(_png_bytes(), viewport_size=(1920, 1080))
        assert isinstance(result, GroundingResult)
        assert result.total >= 1
        assert result.duration_ms >= 0  # mocked calls are instant

    async def test_detect_all_empty_when_no_ml(self):
        p = GroundingPipeline()
        result = await p.detect_all(_png_bytes())
        # Without ML deps, should return empty (graceful degradation)
        assert result.total == 0
        assert result.screenshot_annotated is None

    async def test_source_counts(self):
        mock_detector = MagicMock()
        mock_detector.available = True
        mock_detector.detect = AsyncMock(return_value=[
            Detection(BBox(10, 10, 100, 50), 0.8, source=DetectionSource.VISUAL_YOLO),
        ])

        mock_ocr = MagicMock()
        mock_ocr.available = False
        mock_captioner = MagicMock()
        mock_captioner.available = False

        p = GroundingPipeline(
            detector=mock_detector,
            ocr=mock_ocr,
            captioner=mock_captioner,
        )

        result = await p.detect_all(_png_bytes())
        assert "visual_yolo" in result.source_counts

    async def test_detect_all_with_structural(self):
        mock_detector = MagicMock()
        mock_detector.available = False
        mock_ocr = MagicMock()
        mock_ocr.available = False
        mock_captioner = MagicMock()
        mock_captioner.available = False

        p = GroundingPipeline(
            detector=mock_detector,
            ocr=mock_ocr,
            captioner=mock_captioner,
        )

        structural = [
            Detection(BBox(0, 0, 100, 30), 0.9, label="Nav",
                      role=ElementRole.BUTTON, source=DetectionSource.STRUCTURAL),
        ]

        result = await p.detect_all(
            _png_bytes(),
            structural=structural,
            render_annotation=False,
        )
        assert result.total == 1
        assert result.elements[0].source == DetectionSource.STRUCTURAL


class TestLocate:

    async def test_locate_finds_text_match(self):
        mock_detector = MagicMock()
        mock_detector.available = False
        mock_ocr = MagicMock()
        mock_ocr.available = False
        mock_captioner = MagicMock()
        mock_captioner.available = False

        p = GroundingPipeline(
            detector=mock_detector,
            ocr=mock_ocr,
            captioner=mock_captioner,
        )

        # Patch detect_all to return known elements
        p.detect_all = AsyncMock(return_value=GroundingResult(
            elements=[_fused(label="Submit", conf=0.95)],
            viewport_size=(1920, 1080),
        ))

        request = VisionRequest(
            screenshot=_png_bytes(),
            element_description="Submit",
            page_url="",
            viewport_size=(1920, 1080),
        )

        response = await p.locate(request)
        assert isinstance(response, VisionResponse)
        assert response.found
        assert response.confidence == 0.95
        assert response.model == "grounding_pipeline"

    async def test_locate_not_found(self):
        mock_detector = MagicMock()
        mock_detector.available = False
        mock_ocr = MagicMock()
        mock_ocr.available = False
        mock_captioner = MagicMock()
        mock_captioner.available = False

        p = GroundingPipeline(
            detector=mock_detector,
            ocr=mock_ocr,
            captioner=mock_captioner,
        )

        p.detect_all = AsyncMock(return_value=GroundingResult(
            elements=[_fused(label="Cancel")],
            viewport_size=(1920, 1080),
        ))

        request = VisionRequest(
            screenshot=_png_bytes(),
            element_description="Submit",
            page_url="",
            viewport_size=(1920, 1080),
        )

        response = await p.locate(request)
        assert isinstance(response, VisionResponse)
        assert not response.found

    async def test_locate_empty_elements(self):
        mock_detector = MagicMock()
        mock_detector.available = False
        mock_ocr = MagicMock()
        mock_ocr.available = False
        mock_captioner = MagicMock()
        mock_captioner.available = False

        p = GroundingPipeline(
            detector=mock_detector,
            ocr=mock_ocr,
            captioner=mock_captioner,
        )

        p.detect_all = AsyncMock(return_value=GroundingResult(elements=[]))

        request = VisionRequest(
            screenshot=_png_bytes(),
            element_description="anything",
            page_url="",
            viewport_size=(1920, 1080),
        )

        response = await p.locate(request)
        assert not response.found

    async def test_locate_by_role_keyword(self):
        """Falls back to role matching when no text match."""
        mock_detector = MagicMock()
        mock_detector.available = False
        mock_ocr = MagicMock()
        mock_ocr.available = False
        mock_captioner = MagicMock()
        mock_captioner.available = False

        p = GroundingPipeline(
            detector=mock_detector,
            ocr=mock_ocr,
            captioner=mock_captioner,
        )

        p.detect_all = AsyncMock(return_value=GroundingResult(
            elements=[_fused(label="", role=ElementRole.BUTTON, conf=0.8)],
            viewport_size=(1920, 1080),
        ))

        request = VisionRequest(
            screenshot=_png_bytes(),
            element_description="click the button",
            page_url="",
            viewport_size=(1920, 1080),
        )

        response = await p.locate(request)
        assert response.found
