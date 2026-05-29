"""DesktopObservation — standardized observation from the desktop environment.

Adopted from OSWorld's ``_get_obs()`` observation format. Provides a
consistent interface for benchmarks, logging, and LLM context building.

Also contains ObservationConfig and ObservationResult for the unified
Desktop Observation Pipeline (BATCH-27).

No external deps — pure stdlib.
"""

from __future__ import annotations

import base64
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DesktopObservation:
    """Standardized observation from the desktop environment.

    Adopted from OSWorld's observation format. Provides a consistent
    interface for benchmarks, logging, and LLM context building.

    Fields:
        screenshot: Raw PNG/JPEG bytes of the screen capture.
        accessibility_tree: Parsed accessibility tree (list of dicts or dict).
        active_window: Title of the currently focused window.
        focused_element: Description of the element with focus.
        instruction: The user instruction being executed.
        step_count: How many steps have been executed so far.
        timestamp: When this observation was captured.
        extra: Additional metadata (free-form dict).
    """

    screenshot: bytes | None = None
    accessibility_tree: Any | None = None  # dict | list
    active_window: str = ""
    focused_element: str = ""
    instruction: str = ""
    step_count: int = 0
    timestamp: float = field(default_factory=time.time)
    extra: dict = field(default_factory=dict)

    def to_context_string(self) -> str:
        """Format as a human-readable string for LLM context.

        Includes window title, focused element, instruction, and
        a summary of the accessibility tree (not the full dump).
        """
        parts: list[str] = []

        if self.active_window:
            parts.append(f"Window: {self.active_window}")
        if self.focused_element:
            parts.append(f"Focus: {self.focused_element}")
        if self.instruction:
            parts.append(f"Instruction: {self.instruction}")

        parts.append(f"Step: {self.step_count}")

        if self.accessibility_tree is not None:
            if isinstance(self.accessibility_tree, (list, dict)):
                tree_len = len(self.accessibility_tree)
            else:
                tree_len = 0
            parts.append(f"Accessibility tree: {tree_len} nodes")

        has_screenshot = self.screenshot is not None and len(self.screenshot) > 0
        parts.append(f"Screenshot: {'yes' if has_screenshot else 'no'}")

        return "\n".join(parts)

    def to_dict(self) -> dict:
        """Serialize to dict. Screenshot is base64-encoded if present."""
        result: dict[str, Any] = {
            "active_window": self.active_window,
            "focused_element": self.focused_element,
            "instruction": self.instruction,
            "step_count": self.step_count,
            "timestamp": self.timestamp,
        }

        if self.screenshot is not None:
            result["screenshot_b64"] = base64.b64encode(self.screenshot).decode("ascii")
            result["screenshot_bytes"] = len(self.screenshot)
        else:
            result["screenshot_b64"] = None
            result["screenshot_bytes"] = 0

        if self.accessibility_tree is not None:
            result["accessibility_tree"] = self.accessibility_tree
        else:
            result["accessibility_tree"] = None

        if self.extra:
            result["extra"] = dict(self.extra)

        return result

    @classmethod
    def from_observation_result(
        cls,
        result: ObservationResult,
    ) -> DesktopObservation:
        """Construct from an ObservationResult (BATCH-27 pipeline output).

        Convenience bridge so downstream code expecting DesktopObservation
        can consume pipeline results without adaptation.
        """
        return cls(
            screenshot=result.annotated_screenshot or result.observation.screenshot,
            accessibility_tree=result.observation.accessibility_tree,
            active_window=result.observation.active_window,
            focused_element=result.observation.focused_element,
            extra={
                "element_count": result.element_count,
                "elapsed_ms": result.elapsed_ms,
                "steps_completed": result.steps_completed,
                "snapshot_id": result.snapshot_id,
            },
        )

    @classmethod
    def from_action_result(
        cls,
        result: Any,
        instruction: str = "",
        step_count: int = 0,
    ) -> DesktopObservation:
        """Construct from an ActionResult.

        Extracts screenshot, accessibility tree, and window info from
        the result's ``data`` dict.
        """
        data = getattr(result, "data", None) or {}
        if not isinstance(data, dict):
            data = {"raw": str(data)}

        screenshot = None
        raw_screenshot = data.get("screenshot")
        if isinstance(raw_screenshot, bytes):
            screenshot = raw_screenshot
        elif isinstance(raw_screenshot, str):
            # Try base64 decode
            with contextlib.suppress(Exception):
                screenshot = base64.b64decode(raw_screenshot)

        tree = data.get("accessibility_tree") or data.get("ax_snapshot")

        active_window = ""
        if isinstance(data.get("window_title"), str):
            active_window = data["window_title"]
        elif isinstance(data.get("title"), str):
            active_window = data["title"]

        focused_element = ""
        if isinstance(data.get("focused_element"), str):
            focused_element = data["focused_element"]

        return cls(
            screenshot=screenshot,
            accessibility_tree=tree,
            active_window=active_window,
            focused_element=focused_element,
            instruction=instruction,
            step_count=step_count,
            extra={k: v for k, v in data.items()
                   if k not in ("screenshot", "accessibility_tree", "ax_snapshot",
                                "window_title", "title", "focused_element")},
        )


# ---------------------------------------------------------------------------
# Observation Pipeline types (BATCH-27)
# ---------------------------------------------------------------------------

_VALID_PRESETS = frozenset({"quick", "standard", "full"})

# Preset → step overrides
_PRESET_CONFIGS: dict[str, dict[str, bool]] = {
    "quick": {
        "include_screenshot": True,
        "include_ax_tree": True,
        "include_ocr": False,
        "include_detection": False,
        "include_annotation": False,
    },
    "standard": {
        "include_screenshot": True,
        "include_ax_tree": True,
        "include_ocr": True,
        "include_detection": False,
        "include_annotation": False,
    },
    "full": {
        "include_screenshot": True,
        "include_ax_tree": True,
        "include_ocr": True,
        "include_detection": True,
        "include_annotation": True,
    },
}


@dataclass
class ObservationConfig:
    """Configuration for an observation pipeline run.

    Presets provide sensible defaults; individual flags override them.
    The pipeline uses the effective flags after applying preset + overrides.
    """

    preset: str = "standard"
    """Preset name: quick, standard, or full."""

    include_screenshot: bool = True
    include_ax_tree: bool = True
    include_ocr: bool = True
    include_detection: bool = False
    """ML-heavy element detection (GroundingPipeline). Off by default."""
    include_annotation: bool = False
    """SoM rendering on screenshot. Off by default."""
    save_snapshot: bool = False
    """Persist result to SnapshotStore."""
    target_window: str | None = None
    """Window title filter (substring match)."""
    ocr_engine: str = "builtin"
    """OCR backend: builtin (always), paddleocr, or tesseract."""
    max_elements: int = 500
    """Maximum AX tree elements."""

    def effective_flags(self) -> dict[str, bool]:
        """Return the effective flags after applying preset defaults.

        Explicit ``True`` values on the config override preset defaults.
        Preset only sets defaults for fields that are still at their
        class-level default *and* were not explicitly provided by the caller.
        """
        base = _PRESET_CONFIGS.get(self.preset, _PRESET_CONFIGS["standard"])
        return {
            "include_screenshot": self.include_screenshot,
            "include_ax_tree": self.include_ax_tree,
            "include_ocr": base.get("include_ocr", self.include_ocr),
            "include_detection": base.get("include_detection", self.include_detection),
            "include_annotation": base.get("include_annotation", self.include_annotation),
        }

    def validate(self) -> list[str]:
        """Validate config. Returns a list of error messages (empty if valid)."""
        errors: list[str] = []
        if self.preset not in _VALID_PRESETS:
            errors.append(f"Invalid preset: {self.preset!r} (expected one of {sorted(_VALID_PRESETS)})")
        if self.ocr_engine not in ("builtin", "paddleocr", "tesseract"):
            errors.append(f"Invalid ocr_engine: {self.ocr_engine!r}")
        if self.max_elements < 1:
            errors.append("max_elements must be >= 1")
        return errors

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "preset": self.preset,
            "include_screenshot": self.include_screenshot,
            "include_ax_tree": self.include_ax_tree,
            "include_ocr": self.include_ocr,
            "include_detection": self.include_detection,
            "include_annotation": self.include_annotation,
            "save_snapshot": self.save_snapshot,
            "target_window": self.target_window,
            "ocr_engine": self.ocr_engine,
            "max_elements": self.max_elements,
        }


@dataclass
class ObservationResult:
    """Rich result from an observation pipeline run.

    Contains the core DesktopObservation plus metadata about the
    pipeline execution: which steps ran, timing, and optional
    snapshot persistence.
    """

    observation: DesktopObservation
    elements: list = field(default_factory=list)
    """Detected / OCR'd elements as dicts."""
    element_count: int = 0
    elapsed_ms: float = 0.0
    steps_completed: list = field(default_factory=list)
    """Names of steps that ran."""
    steps_skipped: list = field(default_factory=list)
    """Names of steps that were skipped."""
    snapshot_id: str | None = None
    """ID if saved to SnapshotStore."""
    annotated_screenshot: bytes | None = None
    """SoM-rendered PNG bytes."""

    def to_dict(self) -> dict:
        """Serialize to dict."""
        result: dict[str, Any] = {
            "element_count": self.element_count,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "steps_completed": self.steps_completed,
            "steps_skipped": self.steps_skipped,
            "snapshot_id": self.snapshot_id,
            "observation": self.observation.to_dict(),
        }
        if self.annotated_screenshot is not None:
            result["has_annotated_screenshot"] = True
        else:
            result["has_annotated_screenshot"] = False
        return result
