"""Fusion engine — merge structural + visual + OCR detections.

Priority: structural-as-truth
  - AX/UIA elements are authoritative (they come from the OS)
  - YOLO boxes that overlap AX elements are deduped (AX wins)
  - OCR text boxes deduped against both AX and YOLO
  - Remaining YOLO-only boxes = elements the accessibility tree missed
  - OCR text is assigned as labels to nearby non-text detections
"""

from __future__ import annotations

import logging

from deskaoy.grounding.types import (
    BBox,
    Detection,
    DetectionSource,
    ElementRole,
    FusedElement,
)

logger = logging.getLogger(__name__)

# Confidence assigned to structural (AX/UIA) sources — they're authoritative.
_STRUCTURAL_CONF = 0.95

# Minimum IoU overlap to consider two detections the same element.
_DEFAULT_IOU_THRESHOLD = 0.4


class FusionEngine:
    """Merge detections from multiple sources with structural priority."""

    def __init__(self, *, iou_threshold: float = _DEFAULT_IOU_THRESHOLD) -> None:
        self._iou_threshold = iou_threshold

    def fuse(
        self,
        structural: list[Detection] | None = None,
        visual: list[Detection] | None = None,
        text: list[Detection] | None = None,
    ) -> list[FusedElement]:
        """Fuse structural, visual (YOLO), and text (OCR) detections.

        Returns deduplicated, labeled FusedElements.
        """
        structural = structural or []
        visual = visual or []
        text = text or []

        # Phase 1: Convert structural detections to fused elements (authoritative)
        fused: list[FusedElement] = []
        occupied: list[BBox] = []  # bboxes already claimed

        for d in structural:
            el = FusedElement(
                bbox=d.bbox,
                role=d.role,
                label=d.label or d.text or "",
                confidence=max(d.confidence, _STRUCTURAL_CONF),
                source=DetectionSource.STRUCTURAL,
                sources=(DetectionSource.STRUCTURAL,),
                text=d.text,
            )
            fused.append(el)
            occupied.append(d.bbox)

        # Phase 2: Add visual detections that don't overlap structural
        visual_unmatched: list[Detection] = []
        for d in visual:
            if self._overlaps_any(d.bbox, occupied):
                # Overlaps a structural element — skip (structural wins)
                continue
            visual_unmatched.append(d)

        # Phase 3: NMS among unmatched visual detections
        visual_nms = self._nms(visual_unmatched, self._iou_threshold)

        # Phase 4: Try to assign OCR text labels to visual detections
        text_remaining: list[Detection] = list(text)
        for vd in visual_nms:
            label = vd.label
            assigned_text: str | None = None

            # Find overlapping OCR text
            for i, td in enumerate(text_remaining):
                if vd.bbox.iou(td.bbox) >= self._iou_threshold:
                    assigned_text = td.text
                    label = td.text or label
                    text_remaining.pop(i)
                    break
                # Also check if OCR text is inside the visual bbox
                if vd.bbox.contains(td.bbox) and td.text:
                    assigned_text = td.text
                    label = td.text
                    text_remaining.pop(i)
                    break

            sources = (DetectionSource.VISUAL_YOLO,)
            if assigned_text is not None:
                sources = (DetectionSource.VISUAL_YOLO, DetectionSource.VISUAL_OCR)

            el = FusedElement(
                bbox=vd.bbox,
                role=vd.role,
                label=label or "",
                confidence=vd.confidence,
                source=DetectionSource.VISUAL_YOLO,
                sources=sources,
                text=assigned_text,
            )
            fused.append(el)
            occupied.append(vd.bbox)

        # Phase 5: Add remaining OCR-only detections (text not claimed by visual)
        for td in text_remaining:
            # Skip if overlaps an existing element
            if self._overlaps_any(td.bbox, occupied):
                continue
            el = FusedElement(
                bbox=td.bbox,
                role=ElementRole.TEXT,
                label=td.text or td.label or "",
                confidence=td.confidence,
                source=DetectionSource.VISUAL_OCR,
                sources=(DetectionSource.VISUAL_OCR,),
                text=td.text,
            )
            fused.append(el)
            occupied.append(td.bbox)

        logger.debug(
            "Fusion: %d structural + %d visual + %d text → %d fused",
            len(structural), len(visual), len(text), len(fused),
        )
        return fused

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _overlaps_any(self, bbox: BBox, claimed: list[BBox]) -> bool:
        """True if bbox overlaps any claimed bbox above IoU threshold."""
        return any(bbox.iou(c) >= self._iou_threshold for c in claimed)

    @staticmethod
    def _nms(detections: list[Detection], iou_threshold: float) -> list[Detection]:
        """Non-maximum suppression — remove overlapping low-confidence detections."""
        if not detections:
            return []

        # Sort by confidence descending
        sorted_d = sorted(detections, key=lambda d: d.confidence, reverse=True)
        kept: list[Detection] = []

        for d in sorted_d:
            suppress = False
            for k in kept:
                if d.bbox.iou(k.bbox) >= iou_threshold:
                    suppress = True
                    break
            if not suppress:
                kept.append(d)

        return kept
