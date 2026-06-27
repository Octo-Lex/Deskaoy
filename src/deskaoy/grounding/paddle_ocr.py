"""PaddleOCR engine — text detection with bounding boxes.

Requires: paddleocr (optional). Falls back to existing pytesseract OCR.
"""

from __future__ import annotations

import logging
from io import BytesIO

from deskaoy.grounding.types import (
    BBox,
    Detection,
    DetectionSource,
    ElementRole,
)

logger = logging.getLogger(__name__)

_HAS_PADDLE = False
try:
    from paddleocr import PaddleOCR  # noqa: F401
    _HAS_PADDLE = True
except ImportError:
    pass


class PaddleOCREngine:
    """Text extraction via PaddleOCR with bounding boxes."""

    def __init__(self, *, lang: str = "en", use_gpu: bool = False) -> None:
        self._lang = lang
        self._use_gpu = use_gpu
        self._ocr: object | None = None

    @property
    def available(self) -> bool:
        return _HAS_PADDLE

    def _ensure_engine(self) -> None:
        """Lazy-load PaddleOCR on first use (~2s init)."""
        if self._ocr is not None:
            return
        if not _HAS_PADDLE:
            raise RuntimeError(
                "paddleocr not installed. Install with: "
                "pip install deskaoy[grounding]"
            )
        from paddleocr import PaddleOCR
        logger.info("Initializing PaddleOCR (lang=%s, gpu=%s)", self._lang, self._use_gpu)
        self._ocr = PaddleOCR(
            lang=self._lang,
            use_gpu=self._use_gpu,
            show_log=False,
        )

    async def detect_text(self, screenshot: bytes) -> list[Detection]:
        """Extract text bounding boxes from a screenshot."""
        if not _HAS_PADDLE:
            logger.debug("PaddleOCR not available — returning empty detections")
            return []

        self._ensure_engine()

        # Save to temp file for PaddleOCR (it needs a file path)
        import os
        import tempfile

        from PIL import Image

        img = Image.open(BytesIO(screenshot)).convert("RGB")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img.save(tmp, format="PNG")
            tmp_path = tmp.name

        try:
            results = self._ocr.ocr(tmp_path, cls=False)
        finally:
            os.unlink(tmp_path)

        if not results or not results[0]:
            return []

        detections: list[Detection] = []
        for line in results[0]:
            box_points = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            text = line[1][0]
            confidence = line[1][1]

            # Convert 4-point polygon to axis-aligned bbox
            xs = [p[0] for p in box_points]
            ys = [p[1] for p in box_points]
            bbox = BBox(
                x1=min(xs), y1=min(ys),
                x2=max(xs), y2=max(ys),
            )

            detections.append(Detection(
                bbox=bbox,
                confidence=float(confidence),
                label=text,
                role=ElementRole.TEXT,
                source=DetectionSource.VISUAL_OCR,
                text=text,
            ))

        return detections
