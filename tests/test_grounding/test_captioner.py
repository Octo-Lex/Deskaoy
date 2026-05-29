"""Tests for Florence-2 captioner (mocked)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deskaoy.grounding.types import (
    BBox,
    DetectionSource,
    ElementRole,
    FusedElement,
)
from deskaoy.grounding.captioner import FlorenceCaptioner


def _png_bytes(w: int = 50, h: int = 30) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), (128, 128, 128)).save(buf, format="PNG")
    return buf.getvalue()


def _el(label="", role=ElementRole.ICON, text=None):
    return FusedElement(
        bbox=BBox(10, 10, 60, 40),
        role=role,
        label=label,
        confidence=0.7,
        source=DetectionSource.VISUAL_YOLO,
        text=text,
    )


class TestFlorenceAvailability:

    def test_available_reflects_transformers(self):
        cap = FlorenceCaptioner()
        assert isinstance(cap.available, bool)


class TestCaptionMocked:

    async def test_caption_returns_empty_without_transformers(self):
        cap = FlorenceCaptioner()
        if cap.available:
            pytest.skip("transformers installed")
        result = await cap.caption(_png_bytes())
        assert result == ""


class TestCaptionElementsMocked:

    async def test_skips_elements_with_labels(self):
        cap = FlorenceCaptioner()
        elements = [_el(label="Close", text="close")]
        result = await cap.caption_elements(_png_bytes(100, 100), elements)
        assert len(result) == 1
        assert result[0].label == "Close"

    async def test_captions_labelless_elements(self):
        cap = FlorenceCaptioner()
        elements = [_el(label="", role=ElementRole.ICON)]

        # Mock the caption method
        async def mock_caption(data):
            return "Close window button"

        with patch.object(cap, "caption", side_effect=mock_caption):
            with patch("deskaoy.grounding.captioner._HAS_TRANSFORMERS", True):
                result = await cap.caption_elements(_png_bytes(100, 100), elements)

        assert len(result) == 1
        assert result[0].label == "Close window button"

    async def test_skips_text_elements_with_text(self):
        cap = FlorenceCaptioner()
        elements = [_el(role=ElementRole.TEXT, text="Hello")]
        result = await cap.caption_elements(_png_bytes(100, 100), elements)
        assert len(result) == 1
        # Should not attempt caption — already has text
        assert result[0].text == "Hello"

    async def test_handles_empty_elements(self):
        cap = FlorenceCaptioner()
        result = await cap.caption_elements(_png_bytes(100, 100), [])
        assert result == []
