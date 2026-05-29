"""Grounding types — zero ML dependencies.

All types used by the visual grounding pipeline. Importable without
torch, ultralytics, paddleocr, or transformers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BBox:
    """Axis-aligned bounding box in pixel coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def iou(self, other: BBox) -> float:
        """Intersection over union with another bounding box."""
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = self.area + other.area - inter
        if union <= 0:
            return 0.0
        return inter / union

    def contains(self, other: BBox) -> bool:
        """True if `other` is fully inside this box."""
        return (
            self.x1 <= other.x1
            and self.y1 <= other.y1
            and self.x2 >= other.x2
            and self.y2 >= other.y2
        )

    def normalized(self, viewport_w: int, viewport_h: int) -> BBox:
        """Return bbox with coordinates normalized to [0, 1]."""
        return BBox(
            self.x1 / viewport_w,
            self.y1 / viewport_h,
            self.x2 / viewport_w,
            self.y2 / viewport_h,
        )

    def scaled(self, factor: float) -> BBox:
        """Scale all coordinates by a factor."""
        return BBox(
            self.x1 * factor, self.y1 * factor,
            self.x2 * factor, self.y2 * factor,
        )

    def clamp(self, max_w: float, max_h: float) -> BBox:
        """Clamp to image bounds."""
        return BBox(
            max(0.0, self.x1), max(0.0, self.y1),
            min(max_w, self.x2), min(max_h, self.y2),
        )


# ---------------------------------------------------------------------------
# Element classification
# ---------------------------------------------------------------------------

class ElementRole(StrEnum):
    """Functional role of a detected UI element."""
    BUTTON = "button"
    INPUT = "input"
    LINK = "link"
    ICON = "icon"
    TEXT = "text"
    IMAGE = "image"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DROPDOWN = "dropdown"
    TAB = "tab"
    SLIDER = "slider"
    CONTAINER = "container"
    MENU_ITEM = "menu_item"
    OTHER = "other"


class DetectionSource(StrEnum):
    """Where a detection came from."""
    STRUCTURAL = "structural"      # AX / UIA / accessibility tree
    VISUAL_YOLO = "visual_yolo"   # OmniParser YOLO detector
    VISUAL_OCR = "visual_ocr"     # PaddleOCR / pytesseract
    FUSED = "fused"               # After fusion merge


# ---------------------------------------------------------------------------
# Raw detections (per-source)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Detection:
    """A single detected element from one source."""

    bbox: BBox
    confidence: float
    label: str = ""
    role: ElementRole = ElementRole.OTHER
    source: DetectionSource = DetectionSource.VISUAL_YOLO
    text: str | None = None         # OCR text, if available
    metadata: dict[str, Any] | None = field(default=None, hash=False)


# ---------------------------------------------------------------------------
# Fused element (after multi-source merge)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FusedElement:
    """An element after fusing structural + visual + OCR detections."""

    bbox: BBox
    role: ElementRole
    label: str
    confidence: float
    source: DetectionSource = DetectionSource.FUSED
    sources: tuple[DetectionSource, ...] = ()  # all sources that contributed
    text: str | None = None
    anchor_id: str | None = None    # stable cross-frame ID
    metadata: dict[str, Any] | None = field(default=None, hash=False)

    @property
    def center(self) -> tuple[float, float]:
        return self.bbox.center


# ---------------------------------------------------------------------------
# Cross-frame tracking
# ---------------------------------------------------------------------------

@dataclass
class FrameDelta:
    """Difference between two consecutive frames of detected elements."""
    stable: list[FusedElement]      # same anchor in both frames
    appeared: list[FusedElement]    # new anchors
    disappeared: list[FusedElement] # missing anchors


AnchorMap = dict[str, FusedElement]   # anchor_id → element


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

@dataclass
class GroundingResult:
    """Full output of the grounding pipeline."""

    elements: list[FusedElement]
    screenshot_annotated: bytes | None = None   # SoM-rendered PNG
    duration_ms: float = 0.0
    source_counts: dict[str, int] = field(default_factory=dict)
    viewport_size: tuple[int, int] = (0, 0)

    @property
    def total(self) -> int:
        return len(self.elements)

    def find_by_text(self, text: str, *, case_sensitive: bool = False) -> list[FusedElement]:
        """Find elements whose label or text contains the query."""
        results: list[FusedElement] = []
        needle = text if case_sensitive else text.lower()
        for e in self.elements:
            haystack = (e.label or "")
            if e.text:
                haystack += " " + e.text
            if not case_sensitive:
                haystack = haystack.lower()
            if needle in haystack:
                results.append(e)
        return results

    def find_by_role(self, role: ElementRole) -> list[FusedElement]:
        return [e for e in self.elements if e.role == role]

    def best_match(self, description: str) -> FusedElement | None:
        """Return the single best-matching element for a description."""
        matches = self.find_by_text(description)
        if not matches:
            return None
        return max(matches, key=lambda e: e.confidence)
