"""Visual grounding pipeline — local UI element detection, captioning, and fusion.

Replaces cloud VLM calls for Tier-3 element location with:
  - OmniParser v2 (YOLO detection)
  - Florence-2 (icon captioning)
  - PaddleOCR (text extraction)
  - Fusion engine (multi-source merge)

All ML dependencies (torch, ultralytics, transformers, paddleocr) are optional.
Importing this package takes <100ms without them.
"""

from deskaoy.grounding.types import (
    AnchorMap,
    BBox,
    Detection,
    DetectionSource,
    ElementRole,
    FrameDelta,
    FusedElement,
    GroundingResult,
)

__all__ = [
    "AnchorMap",
    "BBox",
    "Detection",
    "DetectionSource",
    "ElementRole",
    "FrameDelta",
    "FusedElement",
    "GroundingResult",
]
