"""OmniParser v2 YOLO detector — UI element detection.

Requires: ultralytics (optional). Falls back gracefully if not installed.
Uses tiled inference for screenshots > 640px.
"""

from __future__ import annotations

import logging
from io import BytesIO

from PIL import Image

from deskaoy.grounding.types import (
    BBox,
    Detection,
    DetectionSource,
    ElementRole,
)

logger = logging.getLogger(__name__)

_HAS_YOLO = False
try:
    from ultralytics import YOLO
    _HAS_YOLO = True
except ImportError:
    pass

# Tile size for high-res screenshots
_TILE_SIZE = 640
_TILE_OVERLAP = 0.5
_DEFAULT_CONFIDENCE = 0.25


class OmniParserDetector:
    """YOLO-based interactive element detection using OmniParser v2 weights."""

    def __init__(
        self,
        weights_path: str | None = None,
        *,
        confidence: float = _DEFAULT_CONFIDENCE,
    ) -> None:
        self._weights_path = weights_path
        self._confidence = confidence
        self._model: object | None = None

    @property
    def available(self) -> bool:
        return _HAS_YOLO

    def _ensure_model(self) -> None:
        """Lazy-load the YOLO model on first use."""
        if self._model is not None:
            return
        if not _HAS_YOLO:
            raise RuntimeError(
                "ultralytics not installed. Install with: "
                "pip install deskaoy[grounding]"
            )
        from ultralytics import YOLO
        wp = self._weights_path or "weights/icon_detect/model.pt"
        logger.info("Loading OmniParser YOLO weights from %s", wp)
        self._model = YOLO(wp, task="detect")

    async def detect(
        self,
        screenshot: bytes,
        *,
        confidence: float | None = None,
    ) -> list[Detection]:
        """Detect interactive elements in a screenshot.

        Uses tiled inference for images > 640px:
          - Split into tiles (640x640, 50% overlap)
          - Run YOLO on each tile
          - Offset coordinates back to full image
          - Merge overlapping detections with IoU dedup
        """
        if not _HAS_YOLO:
            logger.debug("YOLO not available — returning empty detections")
            return []

        self._ensure_model()
        conf = confidence or self._confidence

        img = Image.open(BytesIO(screenshot)).convert("RGB")
        w, h = img.size

        # For small images, run directly
        if w <= _TILE_SIZE and h <= _TILE_SIZE:
            return self._detect_single(img, conf)

        # Tiled inference for large images
        return self._detect_tiled(img, conf)

    def _detect_single(self, img: Image.Image, conf: float) -> list[Detection]:
        """Run detection on a single image."""
        results = self._model(img, conf=conf, verbose=False)
        return self._parse_results(results, offset_x=0, offset_y=0)

    def _detect_tiled(self, img: Image.Image, conf: float) -> list[Detection]:
        """Run tiled detection and merge results."""
        w, h = img.size
        stride = int(_TILE_SIZE * (1 - _TILE_OVERLAP))
        all_detections: list[Detection] = []

        for y in range(0, h, stride):
            for x in range(0, w, stride):
                # Crop tile
                tile = img.crop((
                    x, y,
                    min(x + _TILE_SIZE, w),
                    min(y + _TILE_SIZE, h),
                ))
                # Skip tiny tiles
                if tile.size[0] < 64 or tile.size[1] < 64:
                    continue
                results = self._model(tile, conf=conf, verbose=False)
                tile_dets = self._parse_results(results, offset_x=x, offset_y=y)
                all_detections.extend(tile_dets)

        # NMS merge across tiles
        return self._nms(all_detections, iou_threshold=0.4)

    def _parse_results(
        self,
        results: object,
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> list[Detection]:
        """Parse YOLO results into Detection objects."""
        detections: list[Detection] = []
        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                bbox = BBox(
                    x1=float(xyxy[0]) + offset_x,
                    y1=float(xyxy[1]) + offset_y,
                    x2=float(xyxy[2]) + offset_x,
                    y2=float(xyxy[3]) + offset_y,
                )
                confidence = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = r.names.get(cls_id, f"class_{cls_id}")
                detections.append(Detection(
                    bbox=bbox,
                    confidence=confidence,
                    label=label,
                    role=self._classify_role(label),
                    source=DetectionSource.VISUAL_YOLO,
                ))
        return detections

    @staticmethod
    def _classify_role(label: str) -> ElementRole:
        """Map YOLO class label to ElementRole."""
        label_lower = label.lower()
        mapping = {
            "button": ElementRole.BUTTON,
            "input": ElementRole.INPUT,
            "link": ElementRole.LINK,
            "icon": ElementRole.ICON,
            "checkbox": ElementRole.CHECKBOX,
            "radio": ElementRole.RADIO,
            "dropdown": ElementRole.DROPDOWN,
            "tab": ElementRole.TAB,
            "slider": ElementRole.SLIDER,
            "text": ElementRole.TEXT,
            "image": ElementRole.IMAGE,
        }
        for key, role in mapping.items():
            if key in label_lower:
                return role
        return ElementRole.OTHER

    @staticmethod
    def _nms(detections: list[Detection], iou_threshold: float) -> list[Detection]:
        """Non-maximum suppression."""
        if not detections:
            return []
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
