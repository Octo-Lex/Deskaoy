"""GroundingPipeline — orchestrator that wires detector + OCR + fusion + captioner.

Implements the VisionProvider protocol so it can be a drop-in replacement
for cloud VLM providers in the cascade.

Usage:
    pipeline = GroundingPipeline()
    result = await pipeline.detect_all(screenshot_bytes)
    # result.elements → list[FusedElement]
    # result.screenshot_annotated → SoM-rendered PNG bytes

Or as a VisionProvider:
    response = await pipeline.locate(vision_request)
    # response → VisionResponse with coords + confidence
"""

from __future__ import annotations

import logging
import time

from deskaoy.cascade.types import VisionRequest, VisionResponse
from deskaoy.grounding.captioner import FlorenceCaptioner
from deskaoy.grounding.detector import OmniParserDetector
from deskaoy.grounding.fusion import FusionEngine
from deskaoy.grounding.paddle_ocr import PaddleOCREngine
from deskaoy.grounding.som_renderer import render_som
from deskaoy.grounding.types import (
    Detection,
    ElementRole,
    GroundingResult,
)

logger = logging.getLogger(__name__)


class GroundingPipeline:
    """Full visual grounding pipeline: detect → OCR → fuse → caption.

    Works with or without ML dependencies:
      - With deps: runs YOLO + PaddleOCR + Florence-2
      - Without deps: returns empty results (degrades gracefully)
    """

    def __init__(
        self,
        *,
        detector: OmniParserDetector | None = None,
        ocr: PaddleOCREngine | None = None,
        captioner: FlorenceCaptioner | None = None,
        fusion: FusionEngine | None = None,
    ) -> None:
        self._detector = detector or OmniParserDetector()
        self._ocr = ocr or PaddleOCREngine()
        self._captioner = captioner or FlorenceCaptioner()
        self._fusion = fusion or FusionEngine()

    @property
    def name(self) -> str:
        return "grounding"

    @property
    def model_id(self) -> str:
        return "omniparser-v2"

    @property
    def available(self) -> bool:
        """True if at least one ML component is available."""
        return self._detector.available or self._ocr.available

    # ------------------------------------------------------------------
    # VisionProvider protocol
    # ------------------------------------------------------------------

    async def locate(self, request: VisionRequest) -> VisionResponse:
        """VisionProvider.locate — find an element matching the description."""
        result = await self.detect_all(
            request.screenshot,
            viewport_size=request.viewport_size,
        )

        if not result.elements:
            return VisionResponse(found=False)

        # Find best match
        match = result.best_match(request.element_description)
        if match is None:
            # No text match — try matching by role keywords in the description
            desc_lower = request.element_description.lower()
            role_map = {
                "button": ElementRole.BUTTON,
                "input": ElementRole.INPUT,
                "link": ElementRole.LINK,
                "icon": ElementRole.ICON,
                "checkbox": ElementRole.CHECKBOX,
                "dropdown": ElementRole.DROPDOWN,
                "tab": ElementRole.TAB,
            }
            for keyword, role in role_map.items():
                if keyword in desc_lower:
                    role_matches = result.find_by_role(role)
                    if role_matches:
                        match = max(role_matches, key=lambda e: e.confidence)
                        break

        if match is None:
            return VisionResponse(found=False)

        cx, cy = match.center
        return VisionResponse(
            found=True,
            x=cx,
            y=cy,
            confidence=match.confidence,
            model="grounding_pipeline",
            raw_response=match.label,
        )

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    async def detect_all(
        self,
        screenshot: bytes,
        *,
        structural: list[Detection] | None = None,
        viewport_size: tuple[int, int] = (0, 0),
        render_annotation: bool = True,
    ) -> GroundingResult:
        """Run the full grounding pipeline on a screenshot.

        Args:
            screenshot: Raw PNG/JPEG bytes.
            structural: Pre-existing structural (AX/UIA) detections.
            viewport_size: (width, height) for anchor normalization.
            render_annotation: Render SoM annotation on screenshot.

        Returns:
            GroundingResult with all fused elements.
        """
        start = time.monotonic()

        # 1. YOLO detection
        visual_dets: list[Detection] = []
        if self._detector.available:
            try:
                visual_dets = await self._detector.detect(screenshot)
            except Exception as exc:
                logger.warning("YOLO detection failed: %s", exc)

        # 2. OCR text
        text_dets: list[Detection] = []
        if self._ocr.available:
            try:
                text_dets = await self._ocr.detect_text(screenshot)
            except Exception as exc:
                logger.warning("PaddleOCR failed: %s", exc)

        # 3. Fusion
        fused = self._fusion.fuse(
            structural=structural,
            visual=visual_dets,
            text=text_dets,
        )

        # 4. Caption non-text elements (if Florence-2 available)
        if self._captioner.available and fused:
            try:
                fused = await self._captioner.caption_elements(screenshot, fused)
            except Exception as exc:
                logger.warning("Florence-2 captioning failed: %s", exc)

        # 5. SoM rendering
        annotated: bytes | None = None
        if render_annotation and fused:
            try:
                annotated = render_som(screenshot, fused)
            except Exception as exc:
                logger.warning("SoM rendering failed: %s", exc)

        duration_ms = (time.monotonic() - start) * 1000

        # Source counts
        source_counts: dict[str, int] = {}
        for el in fused:
            src = el.source.value
            source_counts[src] = source_counts.get(src, 0) + 1

        logger.info(
            "Grounding pipeline: %d elements in %.0fms (sources: %s)",
            len(fused), duration_ms, source_counts,
        )

        return GroundingResult(
            elements=fused,
            screenshot_annotated=annotated,
            duration_ms=duration_ms,
            source_counts=source_counts,
            viewport_size=viewport_size,
        )
