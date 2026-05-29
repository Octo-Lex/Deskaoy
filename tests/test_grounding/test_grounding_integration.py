"""Integration tests for visual grounding pipeline — requires ML weights.

Run with: pytest tests/ -m grounding
Skip with: pytest tests/ -m "not grounding"

These tests verify the full grounding pipeline works end-to-end with
real YOLO/Florence-2/PaddleOCR models. They are gated behind the
`grounding` marker and skipped if weights are not available.
"""

from __future__ import annotations

import asyncio
import os
from io import BytesIO
from pathlib import Path

import pytest

from deskaoy.grounding.types import FusedElement, GroundingResult
from deskaoy.grounding.pipeline import GroundingPipeline
from deskaoy.grounding.detector import OmniParserDetector
from deskaoy.grounding.fusion import FusionEngine
from deskaoy.grounding.anchor import compute_anchor, build_anchor_map
from deskaoy.grounding.som_renderer import render_som

# Check if ML deps are available
pytestmark = pytest.mark.grounding

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _make_test_screenshot(w: int = 800, h: int = 600) -> bytes:
    """Generate a test screenshot with some UI-like elements."""
    if not HAS_PIL:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), (240, 240, 240))
    draw = ImageDraw.Draw(img)

    # Draw some button-like rectangles
    for i, (x, y, text) in enumerate([
        (50, 50, "Submit"),
        (200, 50, "Cancel"),
        (350, 50, "Settings"),
        (50, 150, "Login"),
    ]):
        draw.rectangle([x, y, x + 100, y + 35], fill=(66, 133, 244), outline=(0, 0, 0))
        draw.text((x + 10, y + 8), text, fill=(255, 255, 255))

    # Draw an input field
    draw.rectangle([50, 250, 350, 285], fill=(255, 255, 255), outline=(128, 128, 128))
    draw.text((60, 258), "Enter email...", fill=(180, 180, 180))

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fusion + Anchor (no ML deps)
# ---------------------------------------------------------------------------

class TestFusionIntegration:
    """Fusion engine works with real detection-like data."""

    def test_fuse_three_sources(self):
        from deskaoy.grounding.types import BBox, Detection, DetectionSource, ElementRole

        fusion = FusionEngine()
        result = fusion.fuse(
            structural=[
                Detection(BBox(50, 50, 150, 85), 0.95, "Submit", ElementRole.BUTTON, DetectionSource.STRUCTURAL),
            ],
            visual=[
                Detection(BBox(52, 52, 148, 83), 0.7, "button", ElementRole.BUTTON, DetectionSource.VISUAL_YOLO),
                Detection(BBox(200, 50, 300, 85), 0.8, "button", ElementRole.BUTTON, DetectionSource.VISUAL_YOLO),
            ],
            text=[
                Detection(BBox(55, 55, 120, 80), 0.9, "Submit", ElementRole.TEXT, DetectionSource.VISUAL_OCR, text="Submit"),
                Detection(BBox(202, 55, 265, 80), 0.85, "Cancel", ElementRole.TEXT, DetectionSource.VISUAL_OCR, text="Cancel"),
            ],
        )
        # Structural Submit wins over visual+OCR overlap
        # Visual Cancel gets OCR text assigned
        # Should have at least 2 elements
        assert len(result) >= 2

        # Find the Submit element — should be structural
        submit_els = [e for e in result if "submit" in (e.label or "").lower() or (e.text or "").lower() == "submit"]
        assert len(submit_els) >= 1

    def test_anchor_stability(self):
        from deskaoy.grounding.types import BBox, DetectionSource, ElementRole

        elements = [
            FusedElement(BBox(50, 50, 150, 85), ElementRole.BUTTON, "Submit", 0.9),
            FusedElement(BBox(200, 50, 300, 85), ElementRole.BUTTON, "Cancel", 0.8),
        ]
        amap = build_anchor_map(elements, 800, 600)
        assert len(amap) == 2

        # Same elements in next frame
        amap2 = build_anchor_map(elements, 800, 600)
        assert set(amap.keys()) == set(amap2.keys())


class TestSomRendererIntegration:
    """SoM renderer produces valid PNG from real-looking data."""

    def test_renders_test_screenshot(self):
        if not HAS_PIL:
            pytest.skip("Pillow not installed")

        from deskaoy.grounding.types import BBox, DetectionSource, ElementRole

        screenshot = _make_test_screenshot()
        elements = [
            FusedElement(BBox(50, 50, 150, 85), ElementRole.BUTTON, "Submit", 0.9, source=DetectionSource.STRUCTURAL),
            FusedElement(BBox(200, 50, 300, 85), ElementRole.BUTTON, "Cancel", 0.8, source=DetectionSource.VISUAL_YOLO),
            FusedElement(BBox(50, 250, 350, 285), ElementRole.INPUT, "email", 0.7, source=DetectionSource.VISUAL_OCR),
        ]
        result = render_som(screenshot, elements)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(result) > len(screenshot)  # annotated should be larger


# ---------------------------------------------------------------------------
# Pipeline (no ML deps — graceful degradation)
# ---------------------------------------------------------------------------

class TestPipelineGracefulDegradation:
    """Pipeline works even without ML weights (returns empty results)."""

    @pytest.mark.asyncio
    async def test_detect_all_without_ml(self):
        pipeline = GroundingPipeline()
        if pipeline.available:
            pytest.skip("ML deps installed — test verifies fallback behavior")
        result = await pipeline.detect_all(_make_test_screenshot())
        assert isinstance(result, GroundingResult)
        assert result.total == 0  # no detections without ML

    @pytest.mark.asyncio
    async def test_locate_without_ml(self):
        from deskaoy.cascade.types import VisionRequest
        pipeline = GroundingPipeline()
        if pipeline.available:
            pytest.skip("ML deps installed — test verifies fallback behavior")
        request = VisionRequest(
            screenshot=_make_test_screenshot(),
            element_description="Submit button",
            page_url="",
            viewport_size=(800, 600),
        )
        response = await pipeline.locate(request)
        assert response.found is False


# ---------------------------------------------------------------------------
# ML-weight tests (skipped if weights not available)
# ---------------------------------------------------------------------------

def _weights_available() -> bool:
    """Check if OmniParser v2 weights are cached."""
    cache_dir = Path.home() / ".cache" / "deskaoy" / "weights"
    return (cache_dir / "icon_detect" / "model.pt").exists()


class TestDetectorWithWeights:
    """YOLO detector with real weights."""

    @pytest.mark.asyncio
    async def test_detect_elements(self):
        if not _weights_available():
            pytest.skip("OmniParser v2 weights not downloaded")
        detector = OmniParserDetector()
        if not detector.available:
            pytest.skip("ultralytics not installed")
        result = await detector.detect(_make_test_screenshot())
        assert isinstance(result, list)
        # Even if no detections on synthetic image, should not crash
        for d in result:
            assert d.bbox.x2 > d.bbox.x1
            assert d.bbox.y2 > d.bbox.y1
            assert d.confidence > 0


class TestFullPipelineWithWeights:
    """Full pipeline with real ML weights."""

    @pytest.mark.asyncio
    async def test_pipeline_end_to_end(self):
        if not _weights_available():
            pytest.skip("OmniParser v2 weights not downloaded")
        pipeline = GroundingPipeline()
        if not pipeline.available:
            pytest.skip("ML dependencies not installed")

        result = await pipeline.detect_all(_make_test_screenshot(), viewport_size=(800, 600))
        assert isinstance(result, GroundingResult)
        assert result.duration_ms > 0
        assert isinstance(result.elements, list)
        # Should produce annotated screenshot
        if result.screenshot_annotated:
            assert result.screenshot_annotated[:8] == b"\x89PNG\r\n\x1a\n"
