"""observation_ocr — multi-backend OCR for the Desktop Observation Pipeline.

Provides text extraction from screenshots and AX trees through multiple
OCR backends. The ``builtin`` backend always works (zero deps) by reading
AX tree name/value properties.

HB-01: Builtin backend always available regardless of installed packages.

Usage::

    from deskaoy.observation_ocr import get_ocr_backend, list_available_engines

    engines = list_available_engines()
    backend = get_ocr_backend("builtin")
    results = await backend.extract_text(screenshot_bytes)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class OCRBackend(ABC):
    """Abstract base for OCR backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier (e.g. 'builtin', 'paddleocr')."""
        ...

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether this backend's dependencies are installed."""
        ...

    @abstractmethod
    async def extract_text(self, image_bytes: bytes) -> list[dict]:
        """Run OCR on image bytes, return list of text-region dicts.

        Each dict has keys:
          - text: str (extracted text)
          - bounds: dict with x, y, width, height (may be None)
          - confidence: float 0-1 (may be 0.0 for builtin)
          - source: str (backend name)
        """
        ...

    def merge_with_ax(
        self,
        ax_elements: list[Any],
        ocr_results: list[dict],
    ) -> list[dict]:
        """Merge OCR text into AX elements.

        For each OCR result, tries to find a matching AX element by
        name similarity or bounds overlap. Unmatched OCR results are
        appended as standalone text elements.

        Returns a combined list of element dicts.
        """
        fused: list[dict] = []

        # Convert AX elements to dicts
        for elem in ax_elements:
            elem_dict: dict[str, Any] = {}
            name = getattr(elem, "name", None) or ""
            value = getattr(elem, "value", None) or ""
            bounds = getattr(elem, "bounds", None)
            control_type = getattr(elem, "control_type", "") or getattr(elem, "role", "")

            elem_dict["name"] = name
            elem_dict["value"] = value
            elem_dict["role"] = control_type
            if bounds:
                left, top, w, h = bounds
                elem_dict["bounds"] = {"x": left, "y": top, "width": w, "height": h}

            # Check if any OCR result matches this element's name
            for ocr in ocr_results:
                ocr_text = ocr.get("text", "")
                if name and ocr_text and (
                    ocr_text.lower() in name.lower()
                    or name.lower() in ocr_text.lower()
                ):
                    elem_dict["ocr_text"] = ocr_text
                    elem_dict["ocr_confidence"] = ocr.get("confidence", 0.0)
                    break

            fused.append(elem_dict)

        # Append unmatched OCR results
        for ocr in ocr_results:
            ocr_text = ocr.get("text", "")
            matched = any(
                ocr_text and (
                    ocr_text.lower() in (e.get("name", "") or "").lower()
                    or (e.get("name", "") or "").lower() in ocr_text.lower()
                )
                for e in fused
                if e.get("name")
            )
            if not matched and ocr_text:
                new_elem: dict[str, Any] = {
                    "role": "text",
                    "text": ocr_text,
                    "confidence": ocr.get("confidence", 0.0),
                    "source": ocr.get("source", "ocr"),
                }
                if ocr.get("bounds"):
                    new_elem["bounds"] = ocr["bounds"]
                fused.append(new_elem)

        return fused


# ---------------------------------------------------------------------------
# Builtin backend (always available)
# ---------------------------------------------------------------------------

class BuiltinOCRBackend(OCRBackend):
    """Builtin OCR: extracts text from AX tree name/value properties.

    Works with zero external dependencies. This is not a real OCR engine
    — it reads structured accessibility data instead of pixels.
    """

    @property
    def name(self) -> str:
        return "builtin"

    @property
    def available(self) -> bool:
        return True  # Always available

    async def extract_text(self, image_bytes: bytes) -> list[dict]:
        """Builtin OCR cannot extract from images — returns empty.

        Use merge_with_ax() instead for the builtin workflow.
        """
        return []


# ---------------------------------------------------------------------------
# PaddleOCR backend (optional)
# ---------------------------------------------------------------------------

class PaddleOCRBackend(OCRBackend):
    """PaddleOCR-based text extraction (optional dependency)."""

    @property
    def name(self) -> str:
        return "paddleocr"

    @property
    def available(self) -> bool:
        try:
            from deskaoy.grounding.paddle_ocr import PaddleOCREngine  # noqa: F401
            return True
        except ImportError:
            return False

    async def extract_text(self, image_bytes: bytes) -> list[dict]:
        if not self.available:
            return []
        try:
            from deskaoy.grounding.paddle_ocr import PaddleOCREngine
            engine = PaddleOCREngine()
            if not engine.available:
                return []
            detections = await engine.detect_text(image_bytes)
            results: list[dict] = []
            for det in detections:
                bbox = det.bbox
                results.append({
                    "text": det.text or det.label,
                    "bounds": {
                        "x": bbox.x1,
                        "y": bbox.y1,
                        "width": bbox.width,
                        "height": bbox.height,
                    } if bbox else None,
                    "confidence": det.confidence,
                    "source": "paddleocr",
                })
            return results
        except Exception as exc:
            logger.warning("PaddleOCR extraction failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Tesseract backend (optional)
# ---------------------------------------------------------------------------

class TesseractOCRBackend(OCRBackend):
    """Tesseract-based text extraction (optional dependency)."""

    @property
    def name(self) -> str:
        return "tesseract"

    @property
    def available(self) -> bool:
        try:
            from deskaoy.vision.ocr import OCRGrounding  # noqa: F401
            return True
        except ImportError:
            return False

    async def extract_text(self, image_bytes: bytes) -> list[dict]:
        if not self.available:
            return []
        try:
            from deskaoy.vision.ocr import OCRGrounding
            engine = OCRGrounding()
            words = engine.extract_words(image_bytes)
            results: list[dict] = []
            for w in words:
                results.append({
                    "text": w.text,
                    "bounds": {
                        "x": w.x,
                        "y": w.y,
                        "width": w.width,
                        "height": w.height,
                    },
                    "confidence": w.confidence,
                    "source": "tesseract",
                })
            return results
        except Exception as exc:
            logger.warning("Tesseract extraction failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BACKENDS: dict[str, type[OCRBackend]] = {
    "builtin": BuiltinOCRBackend,
    "paddleocr": PaddleOCRBackend,
    "tesseract": TesseractOCRBackend,
}


def get_ocr_backend(name: str) -> OCRBackend | None:
    """Get an OCR backend by name.

    Returns the backend instance, or None if the name is unknown.
    Check ``backend.available`` before using.
    """
    cls = _BACKENDS.get(name)
    if cls is None:
        return None
    return cls()


def list_available_engines() -> list[dict[str, Any]]:
    """List all OCR backends with their availability status."""
    result: list[dict[str, Any]] = []
    for name, cls in _BACKENDS.items():
        backend = cls()
        result.append({
            "name": name,
            "available": backend.available,
        })
    return result
