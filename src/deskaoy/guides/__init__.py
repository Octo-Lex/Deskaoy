"""App Guide Registry — per-app JSON guides for desktop automation.

Loads JSON guide files that describe how to interact with specific applications.
Guides contain selectors, workflow hints, and safety rules per app.

Inspired by Clawd Cursor's guides/*.json pattern.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default guides directory
_BUILTIN_DIR = Path(__file__).parent / "guides"


@dataclass
class AppGuide:
    """Guide for interacting with a specific application."""
    name: str
    process_names: list[str] = field(default_factory=list)
    selectors: dict[str, str] = field(default_factory=dict)
    workflows: dict[str, list[dict]] = field(default_factory=dict)
    safety_notes: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_json(data: dict) -> AppGuide:
        return AppGuide(
            name=data.get("name", ""),
            process_names=data.get("process_names", []),
            selectors=data.get("selectors", {}),
            workflows=data.get("workflows", {}),
            safety_notes=data.get("safety_notes", []),
            tips=data.get("tips", []),
            version=data.get("version", ""),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def from_file(path: str | Path) -> AppGuide:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return AppGuide.from_json(data)

    def get_selector(self, element: str) -> str:
        """Get selector for an element, or empty string if unknown."""
        return self.selectors.get(element, "")

    def get_workflow(self, name: str) -> list[dict]:
        """Get workflow steps by name, or empty list if unknown."""
        return self.workflows.get(name, [])


class GuideRegistry:
    """Registry of per-app guides. Loads from directory on demand."""

    def __init__(self, guides_dir: str | Path | None = None) -> None:
        self._dir = Path(guides_dir) if guides_dir else _BUILTIN_DIR
        self._guides: dict[str, AppGuide] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load_from_directory(self._dir)

    def _load_from_directory(self, directory: Path) -> None:
        if not directory.exists():
            return
        for json_file in directory.glob("*.json"):
            try:
                guide = AppGuide.from_file(json_file)
                if guide.name:
                    self._guides[guide.name.lower()] = guide
                    # Also index by process names
                    for proc in guide.process_names:
                        self._guides[proc.lower()] = guide
            except Exception as exc:
                logger.warning("Failed to load guide %s: %s", json_file, exc)

    def get(self, app_name: str) -> AppGuide | None:
        """Get guide for an app by name or process name."""
        self._ensure_loaded()
        return self._guides.get(app_name.lower())

    def has_guide(self, app_name: str) -> bool:
        """Check if a guide exists for an app."""
        return self.get(app_name) is not None

    def list_guides(self) -> list[str]:
        """List all available guide names (unique)."""
        self._ensure_loaded()
        seen: set[str] = set()
        result: list[str] = []
        for guide in self._guides.values():
            if guide.name not in seen:
                seen.add(guide.name)
                result.append(guide.name)
        return sorted(result)

    def register(self, guide: AppGuide) -> None:
        """Register a guide programmatically."""
        self._loaded = True
        self._guides[guide.name.lower()] = guide
        for proc in guide.process_names:
            self._guides[proc.lower()] = guide
