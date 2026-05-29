"""Tests for Set-of-Mark renderer."""

from __future__ import annotations

import struct
from io import BytesIO

import pytest

from deskaoy.grounding.types import (
    BBox,
    DetectionSource,
    ElementRole,
    FusedElement,
)
from deskaoy.grounding.som_renderer import render_som


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _png_bytes(w: int = 200, h: int = 200) -> bytes:
    """Generate a minimal valid PNG."""
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _is_png(data: bytes) -> bool:
    """Check if bytes start with PNG magic number."""
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def _el(
    x1, y1, x2, y2,
    label="Button",
    source=DetectionSource.STRUCTURAL,
    role=ElementRole.BUTTON,
) -> FusedElement:
    return FusedElement(
        bbox=BBox(x1, y1, x2, y2),
        role=role,
        label=label,
        confidence=0.8,
        source=source,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestRenderSOM:

    def test_returns_valid_png(self):
        elements = [
            _el(10, 10, 100, 50, label="OK"),
        ]
        result = render_som(_png_bytes(), elements)
        assert _is_png(result)

    def test_empty_elements(self):
        result = render_som(_png_bytes(), [])
        assert _is_png(result)

    def test_multiple_elements(self):
        elements = [
            _el(10, 10, 100, 50, label="Button A"),
            _el(10, 60, 100, 100, label="Input B", source=DetectionSource.VISUAL_OCR),
            _el(110, 10, 200, 50, label="Icon C", source=DetectionSource.VISUAL_YOLO),
        ]
        result = render_som(_png_bytes(300, 150), elements)
        assert _is_png(result)

    def test_no_labels(self):
        elements = [_el(10, 10, 100, 50)]
        result = render_som(_png_bytes(), elements, show_labels=False, show_indices=True)
        assert _is_png(result)

    def test_no_indices(self):
        elements = [_el(10, 10, 100, 50, label="OK")]
        result = render_som(_png_bytes(), elements, show_labels=True, show_indices=False)
        assert _is_png(result)

    def test_label_truncation(self):
        long_label = "A" * 50
        elements = [_el(10, 10, 100, 50, label=long_label)]
        result = render_som(_png_bytes(), elements)
        assert _is_png(result)  # doesn't crash on long labels

    def test_fused_source(self):
        elements = [
            _el(10, 10, 100, 50, label="Merged", source=DetectionSource.FUSED),
        ]
        result = render_som(_png_bytes(), elements)
        assert _is_png(result)

    def test_box_at_top_edge(self):
        """Element at y=0 should still render label without going negative."""
        elements = [_el(10, 0, 100, 20, label="Top")]
        result = render_som(_png_bytes(), elements)
        assert _is_png(result)

    def test_custom_line_width(self):
        elements = [_el(10, 10, 100, 50)]
        result = render_som(_png_bytes(), elements, line_width=4)
        assert _is_png(result)
