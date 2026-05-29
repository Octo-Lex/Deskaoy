"""ObservationPipeline — unified desktop observation pipeline (BATCH-27).

A single composable chain: screenshot → AX tree → OCR → detect → fuse →
annotate → optional snapshot persistence. Shared across CLI, MCP, and REST.

HB-01: Every step is optional. Pipeline works with zero ML deps.
HB-04: ``quick`` preset completes in <5 s (screenshot + AX tree only).

Usage::

    from deskaoy.observation_pipeline import ObservationPipeline

    pipeline = ObservationPipeline(adapter=my_surface)
    result = await pipeline.observe(ObservationConfig(preset="standard"))
    print(result.element_count, result.steps_completed)

Or with shortcut methods::

    result = await pipeline.observe_quick()
    result = await pipeline.observe_standard()
    result = await pipeline.observe_full()
"""

from __future__ import annotations

import logging
from typing import Any

from deskaoy.observation import (
    _PRESET_CONFIGS,
    DesktopObservation,
    ObservationConfig,
    ObservationResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class ObservationPipeline:
    """Unified desktop observation pipeline.

    Composable steps executed in order based on the preset / config:
      1. capture   — screenshot via SurfaceAdapter
      2. ax_walk   — accessibility tree via UIAWalker
      3. ocr       — text extraction (builtin / paddleocr / tesseract)
      4. detect    — element detection via GroundingPipeline (optional)
      5. fuse      — combine AX + detection + OCR results
      6. annotate  — SoM rendering on screenshot (optional)
      7. snapshot  — persist to SnapshotStore (optional)

    Each step optionally enriches the shared ``state`` dict. Steps that
    cannot run (missing deps, disabled flags) are silently skipped.
    """

    def __init__(
        self,
        *,
        adapter: Any = None,
        walker: Any = None,
        grounding_pipeline: Any = None,
        snapshot_store: Any = None,
        ocr_backend: Any = None,
    ) -> None:
        # All dependencies are optional (HB-01)
        self._adapter = adapter
        self._walker = walker
        self._grounding_pipeline = grounding_pipeline
        self._snapshot_store = snapshot_store
        self._ocr_backend = ocr_backend

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def observe(self, config: ObservationConfig) -> ObservationResult:
        """Run the pipeline with the given configuration.

        Returns an ObservationResult with the populated DesktopObservation
        and metadata about which steps ran / were skipped.
        """
        errors = config.validate()
        if errors:
            raise ValueError(f"Invalid ObservationConfig: {'; '.join(errors)}")

        flags = config.effective_flags()
        state: dict[str, Any] = {
            "config": config,
            "flags": flags,
            "screenshot": None,
            "ax_elements": [],
            "ocr_results": [],
            "detection_results": None,
            "fused_elements": [],
            "annotated_screenshot": None,
            "snapshot_id": None,
            "active_window": "",
            "focused_element": "",
        }

        steps_completed: list[str] = []
        steps_skipped: list[str] = []

        # Ordered step execution
        step_map = [
            ("capture", flags["include_screenshot"], self._step_capture),
            ("ax_walk", flags["include_ax_tree"], self._step_ax_walk),
            ("ocr", flags["include_ocr"], self._step_ocr),
            ("detect", flags["include_detection"], self._step_detect),
            ("fuse", flags["include_ocr"] or flags["include_detection"], self._step_fuse),
            ("annotate", flags["include_annotation"], self._step_annotate),
            ("snapshot", config.save_snapshot, self._step_snapshot),
        ]

        for step_name, enabled, step_fn in step_map:
            if not enabled:
                steps_skipped.append(step_name)
                continue
            try:
                await step_fn(state)
                steps_completed.append(step_name)
            except Exception as exc:
                logger.warning("Step %s failed: %s", step_name, exc)
                steps_skipped.append(step_name)

        # Build observation
        obs = DesktopObservation(
            screenshot=state["screenshot"],
            accessibility_tree=[
                self._element_to_dict(e) for e in state["ax_elements"]
            ] if state["ax_elements"] else None,
            active_window=state.get("active_window", ""),
            focused_element=state.get("focused_element", ""),
            extra={
                "steps_completed": steps_completed,
                "steps_skipped": steps_skipped,
            },
        )

        # Build elements list from fused results (or AX if no fusion ran)
        elements = state["fused_elements"] or [
            self._element_to_dict(e) for e in state["ax_elements"]
        ]

        return ObservationResult(
            observation=obs,
            elements=elements,
            element_count=len(elements),
            elapsed_ms=0.0,  # Set below
            steps_completed=steps_completed,
            steps_skipped=steps_skipped,
            snapshot_id=state.get("snapshot_id"),
            annotated_screenshot=state.get("annotated_screenshot"),
        )

    async def observe_quick(self, **kwargs: Any) -> ObservationResult:
        """Shortcut: screenshot + AX tree only (fast preset)."""
        config = ObservationConfig(preset="quick", **kwargs)
        return await self.observe(config)

    async def observe_standard(self, **kwargs: Any) -> ObservationResult:
        """Shortcut: screenshot + AX + OCR."""
        config = ObservationConfig(preset="standard", **kwargs)
        return await self.observe(config)

    async def observe_full(self, **kwargs: Any) -> ObservationResult:
        """Shortcut: all steps enabled."""
        config = ObservationConfig(preset="full", **kwargs)
        return await self.observe(config)

    @staticmethod
    def list_presets() -> dict[str, dict[str, bool]]:
        """Return available presets and their effective configs."""
        return dict(_PRESET_CONFIGS)

    # ------------------------------------------------------------------
    # Pipeline Steps
    # ------------------------------------------------------------------

    async def _step_capture(self, state: dict) -> None:
        """Screenshot via SurfaceAdapter."""
        adapter = self._adapter
        if adapter is None:
            logger.debug("No SurfaceAdapter — skipping capture")
            return

        screenshot = await adapter.screenshot()
        state["screenshot"] = screenshot

        # Also try to get window title
        try:
            title = await adapter.current_title()
            state["active_window"] = title or ""
        except Exception:
            pass

    async def _step_ax_walk(self, state: dict) -> None:
        """Accessibility tree via UIAWalker."""
        walker = self._walker
        if walker is None:
            logger.debug("No UIAWalker — skipping AX walk")
            return

        config: ObservationConfig = state["config"]

        # Walk tree (synchronous method on UIAWalker)
        elements = walker.walk()
        state["ax_elements"] = elements[:config.max_elements]

        # Try to extract focused element
        try:
            focused = walker.get_focused_element()
            if focused is not None:
                state["focused_element"] = focused.name or focused.control_type
        except Exception:
            pass

    async def _step_ocr(self, state: dict) -> None:
        """Text extraction — builtin (AX names) or PaddleOCR/Tesseract.

        Builtin OCR walks AX elements and extracts name/value properties.
        This works with zero dependencies.
        """
        config: ObservationConfig = state["config"]
        engine = config.ocr_engine

        if engine == "builtin":
            # Builtin: extract text from AX tree elements
            ocr_results = self._builtin_ocr(state["ax_elements"])
            state["ocr_results"] = ocr_results
            return

        # External OCR backends — try the observation_ocr module
        try:
            from deskaoy.observation_ocr import get_ocr_backend
            backend = get_ocr_backend(engine)
            if backend is not None:
                screenshot = state.get("screenshot")
                if screenshot:
                    results = await backend.extract_text(screenshot)
                    state["ocr_results"] = results
                else:
                    # Fall back to builtin
                    state["ocr_results"] = self._builtin_ocr(state["ax_elements"])
            else:
                # Backend not available — fall back to builtin
                logger.info("OCR backend %s not available, using builtin", engine)
                state["ocr_results"] = self._builtin_ocr(state["ax_elements"])
        except ImportError:
            # observation_ocr module not available — builtin only
            state["ocr_results"] = self._builtin_ocr(state["ax_elements"])

    async def _step_detect(self, state: dict) -> None:
        """Element detection via GroundingPipeline (optional)."""
        pipeline = self._grounding_pipeline
        if pipeline is None:
            logger.debug("No GroundingPipeline — skipping detection")
            return

        screenshot = state.get("screenshot")
        if screenshot is None:
            logger.debug("No screenshot — skipping detection")
            return

        # Run detection
        result = await pipeline.detect_all(screenshot, render_annotation=False)
        state["detection_results"] = result

    async def _step_fuse(self, state: dict) -> None:
        """Combine AX + detection + OCR results into unified elements list."""
        ax_elements = state.get("ax_elements", [])
        ocr_results = state.get("ocr_results", [])
        detection_results = state.get("detection_results")

        fused: list[dict] = []

        # Start with AX elements as base
        for elem in ax_elements:
            elem_dict = self._element_to_dict(elem)
            fused.append(elem_dict)

        # Merge OCR text into matching AX elements (by proximity / name match)
        if ocr_results:
            self._merge_ocr_into_fused(fused, ocr_results)

        # If detection ran, merge detection results
        if detection_results is not None:
            det_elements = detection_results.elements if detection_results else []
            for de in det_elements:
                fused.append({
                    "role": de.role.value if hasattr(de.role, "value") else str(de.role),
                    "label": de.label,
                    "text": de.text,
                    "confidence": de.confidence,
                    "bbox": {
                        "x1": de.bbox.x1,
                        "y1": de.bbox.y1,
                        "x2": de.bbox.x2,
                        "y2": de.bbox.y2,
                    } if hasattr(de, "bbox") else None,
                    "source": "detection",
                })

        state["fused_elements"] = fused

    async def _step_annotate(self, state: dict) -> None:
        """SoM rendering on screenshot (optional)."""
        screenshot = state.get("screenshot")
        if screenshot is None:
            return

        # Try GroundingPipeline for annotation
        pipeline = self._grounding_pipeline
        if pipeline is not None:
            try:
                result = await pipeline.detect_all(screenshot, render_annotation=True)
                if result.screenshot_annotated:
                    state["annotated_screenshot"] = result.screenshot_annotated
            except Exception as exc:
                logger.warning("Annotation failed: %s", exc)

    async def _step_snapshot(self, state: dict) -> None:
        """Persist to SnapshotStore (optional)."""
        store = self._snapshot_store
        if store is None:
            logger.debug("No SnapshotStore — skipping snapshot persistence")
            return

        elements = state.get("fused_elements", [])
        if not elements:
            elements = [self._element_to_dict(e) for e in state.get("ax_elements", [])]

        # Convert elements to SnapshotStore format
        store_elements: list[dict] = []
        for elem in elements:
            if isinstance(elem, dict):
                store_elements.append(elem)
            else:
                store_elements.append(self._element_to_dict(elem))

        screenshot = state.get("screenshot")
        metadata = {
            "application": state.get("active_window", ""),
            "window_title": state.get("active_window", ""),
        }

        snapshot_id = await store.create(store_elements, screenshot, metadata=metadata)
        state["snapshot_id"] = snapshot_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _builtin_ocr(ax_elements: list) -> list[dict]:
        """Builtin OCR: extract text from AX tree name/value properties.

        Works with zero external dependencies. Returns list of text-region
        dicts with bounds from the AX element.
        """
        results: list[dict] = []
        for elem in ax_elements:
            name = getattr(elem, "name", None) or ""
            value = getattr(elem, "value", None) or ""
            bounds = getattr(elem, "bounds", None)

            texts = [t for t in (name, value) if t and t.strip()]
            if not texts:
                continue

            for text in texts:
                region: dict[str, Any] = {"text": text.strip()}
                if bounds:
                    left, top, w, h = bounds
                    region["bounds"] = {
                        "x": left, "y": top,
                        "width": w, "height": h,
                    }
                region["source"] = "builtin"
                results.append(region)

        return results

    @staticmethod
    def _element_to_dict(elem: Any) -> dict:
        """Convert an AX element to a serializable dict."""
        if isinstance(elem, dict):
            return elem

        result: dict[str, Any] = {}
        for attr in ("ref", "name", "control_type", "role", "value",
                      "is_interactive", "is_enabled", "is_visible"):
            val = getattr(elem, attr, None)
            if val is not None:
                if hasattr(val, "value"):
                    val = val.value  # Enum → str
                result[attr] = val

        bounds = getattr(elem, "bounds", None)
        if bounds:
            left, top, w, h = bounds
            result["bounds"] = {"x": left, "y": top, "width": w, "height": h}

        return result

    @staticmethod
    def _merge_ocr_into_fused(fused: list[dict], ocr_results: list[dict]) -> None:
        """Merge OCR text regions into fused elements by proximity matching.

        For each OCR result, try to find a matching AX element by name
        similarity or bounds overlap. If no match, append as a new element.
        """
        for ocr in ocr_results:
            ocr_text = ocr.get("text", "")
            ocr_bounds = ocr.get("bounds")

            # Try name match
            matched = False
            for elem in fused:
                elem_name = elem.get("name", "")
                if elem_name and ocr_text and (
                    ocr_text.lower() in elem_name.lower()
                    or elem_name.lower() in ocr_text.lower()
                ):
                    # Enrich with OCR text if not already present
                    if "ocr_text" not in elem:
                        elem["ocr_text"] = ocr_text
                    matched = True
                    break

            if not matched:
                # Append as standalone text element
                new_elem: dict[str, Any] = {
                    "role": "text",
                    "text": ocr_text,
                    "source": ocr.get("source", "ocr"),
                }
                if ocr_bounds:
                    new_elem["bounds"] = ocr_bounds
                fused.append(new_elem)
