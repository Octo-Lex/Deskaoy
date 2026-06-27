"""Set-of-Mark renderer — annotate screenshots with labeled bounding boxes.

Color coding:
  - Green  = structural (AX/UIA)
  - Blue   = OCR text
  - Orange = visual-only (YOLO, no structural match)
  - Purple = fused (multi-source)

Each box gets an index number + truncated label.
"""

from __future__ import annotations

import logging
from io import BytesIO

from deskaoy.grounding.types import (
    DetectionSource,
    FusedElement,
)

logger = logging.getLogger(__name__)

# Source → RGB color
_SOURCE_COLORS: dict[DetectionSource, tuple[int, int, int]] = {
    DetectionSource.STRUCTURAL: (46, 204, 113),    # green
    DetectionSource.VISUAL_OCR: (52, 152, 219),    # blue
    DetectionSource.VISUAL_YOLO: (243, 156, 18),   # orange
    DetectionSource.FUSED: (155, 89, 182),          # purple
}

# Label constants
_BOX_LINE_WIDTH = 2
_LABEL_FONT_SIZE = 12
_MAX_LABEL_LEN = 20
_MARGIN = 2


def render_som(
    screenshot: bytes,
    elements: list[FusedElement],
    *,
    show_labels: bool = True,
    show_indices: bool = True,
    line_width: int = _BOX_LINE_WIDTH,
    font_size: int = _LABEL_FONT_SIZE,
) -> bytes:
    """Render Set-of-Mark annotation on a screenshot.

    Args:
        screenshot: Raw PNG/JPEG bytes.
        elements: Detected elements to annotate.
        show_labels: Draw role/label text.
        show_indices: Draw index numbers.
        line_width: Box border thickness.
        font_size: Label text size.

    Returns:
        Annotated PNG bytes.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow not available — returning unannotated screenshot")
        return screenshot

    img = Image.open(BytesIO(screenshot)).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Try to get a reasonable font
    font = _get_font(font_size)

    for idx, el in enumerate(elements):
        color = _SOURCE_COLORS.get(el.source, (200, 200, 200))

        # Draw bounding box
        x1, y1, x2, y2 = el.bbox.x1, el.bbox.y1, el.bbox.x2, el.bbox.y2
        draw.rectangle([x1, y1, x2, y2], outline=color, width=line_width)

        if not show_labels and not show_indices:
            continue

        # Build label text
        parts: list[str] = []
        if show_indices:
            parts.append(f"#{idx}")
        if show_labels and el.label:
            truncated = el.label[:_MAX_LABEL_LEN]
            if len(el.label) > _MAX_LABEL_LEN:
                truncated += "…"
            parts.append(truncated)
        elif show_labels:
            parts.append(el.role.value)

        label_text = " ".join(parts)

        # Draw label background + text (above the box)
        text_bbox = draw.textbbox((0, 0), label_text, font=font)
        tw = text_bbox[2] - text_bbox[0]
        th = text_bbox[3] - text_bbox[1]
        lx = x1
        ly = max(0, y1 - th - 2 * _MARGIN)

        draw.rectangle(
            [lx, ly, lx + tw + 2 * _MARGIN, ly + th + 2 * _MARGIN],
            fill=(0, 0, 0, 180),
        )
        draw.text(
            (lx + _MARGIN, ly + _MARGIN),
            label_text,
            fill="white",
            font=font,
        )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _get_font(size: int) -> object:
    """Get a PIL font, falling back to default if necessary."""
    from PIL import ImageFont  # noqa: F401

    # Try common system fonts
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue

    # Default bitmap font
    return ImageFont.load_default()
