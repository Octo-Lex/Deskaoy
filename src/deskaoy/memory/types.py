"""Action memory types — durable target identities, evidence, and healing records."""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SurfaceKind(StrEnum):
    BROWSER = "browser"
    DESKTOP = "desktop"
    TERMINAL = "terminal"


class AnchorKind(StrEnum):
    """Which anchor type was used to locate the element."""
    SELECTOR = "selector"
    AX_PATH = "ax_path"
    UIA_AUTOMATION_ID = "uia_automation_id"
    UIA_NAME = "uia_name"
    UIA_CLASS = "uia_class"
    VISUAL_FINGERPRINT = "visual_fingerprint"
    OCR_TEXT = "ocr_text"
    NEARBY_TEXT = "nearby_text"
    BBOX_NORMALIZED = "bbox_normalized"
    COORDINATE = "coordinate"


class HealStrategy(StrEnum):
    AX_ROLE_TEXT = "ax_role_text"
    VISUAL_FINGERPRINT = "visual_fingerprint"
    OCR_SEARCH = "ocr_search"
    NEARBY_TEXT_ANCHOR = "nearby_text_anchor"
    BBOX_PROXIMITY = "bbox_proximity"


# ---------------------------------------------------------------------------
# Tier record — one attempt
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TierRecord:
    """Record of a single tier attempt."""
    tier: str               # "selector", "accessibility", "vision", "coordinate"
    outcome: str            # "success", "failed", "healed"
    duration_ms: float
    anchor_used: str        # Which anchor succeeded
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Durable target — the persistent identity
# ---------------------------------------------------------------------------

@dataclass
class DurableTarget:
    """Everything we know about how to find and interact with a specific UI target.

    target_id is a stable hash of (intent, surface, domain) — keyed by *what*
    you're trying to do, not by *how* you found it (selectors break).
    """

    # Identity
    target_id: str
    intent: str                     # "click login button"
    surface: str                    # "browser", "desktop"
    domain: str                     # "example.com", "Calculator"

    # Structural anchors
    selector: str | None = None
    ax_path: str | None = None
    uia_automation_id: str | None = None
    uia_name: str | None = None
    uia_class: str | None = None
    uia_control_type: str | None = None

    # Visual anchors
    visual_fingerprint: str | None = None     # Perceptual hash hex string
    bbox_normalized: tuple[float, float, float, float] | None = None  # (x%, y%, w%, h%)
    nearby_text: list[str] = field(default_factory=list)
    ocr_text: str | None = None

    # Performance
    successful_tier: str | None = None
    tier_history: list[TierRecord] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    confidence: float = 1.0

    # Verification
    pre_action_hash: str | None = None
    post_action_hash: str | None = None

    # Metadata
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.monotonic)
    last_succeeded: float | None = None
    version: int = 1

    # -- Derived properties --

    @property
    def reliability(self) -> float:
        """0.0–1.0 score based on success/fail history."""
        total = self.success_count + self.fail_count
        if total == 0:
            return 0.5
        return self.success_count / total

    @property
    def is_stale(self) -> bool:
        """True if last 3 attempts all failed."""
        if len(self.tier_history) < 3:
            return False
        return all(r.outcome == "failed" for r in self.tier_history[-3:])

    @property
    def available_anchors(self) -> list[AnchorKind]:
        """List of anchor kinds that have values."""
        anchors: list[AnchorKind] = []
        if self.selector:
            anchors.append(AnchorKind.SELECTOR)
        if self.ax_path:
            anchors.append(AnchorKind.AX_PATH)
        if self.uia_automation_id:
            anchors.append(AnchorKind.UIA_AUTOMATION_ID)
        if self.uia_name:
            anchors.append(AnchorKind.UIA_NAME)
        if self.uia_class:
            anchors.append(AnchorKind.UIA_CLASS)
        if self.visual_fingerprint:
            anchors.append(AnchorKind.VISUAL_FINGERPRINT)
        if self.ocr_text:
            anchors.append(AnchorKind.OCR_TEXT)
        if self.nearby_text:
            anchors.append(AnchorKind.NEARBY_TEXT)
        if self.bbox_normalized:
            anchors.append(AnchorKind.BBOX_NORMALIZED)
        return anchors

    @property
    def best_anchor(self) -> AnchorKind | None:
        """Return the anchor from the most recent successful tier record."""
        for record in reversed(self.tier_history):
            if record.outcome in ("success", "healed"):
                try:
                    return AnchorKind(record.anchor_used)
                except ValueError:
                    return None
        # Fallback to first available anchor
        return self.available_anchors[0] if self.available_anchors else None

    # -- Serialization --

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tier_history"] = [asdict(r) for r in self.tier_history]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DurableTarget:
        data = dict(data)
        data["tier_history"] = [
            TierRecord(**r) if isinstance(r, dict) else r
            for r in data.get("tier_history", [])
        ]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Action evidence — captured during action execution
# ---------------------------------------------------------------------------

@dataclass
class ActionEvidence:
    """Everything captured during a single action attempt."""

    # What we tried
    action: str                      # "click", "fill", "type"
    target_description: str          # "login button"
    surface: str = "browser"
    domain: str = ""

    # Structural evidence
    selector: str | None = None
    ax_node_ref: str | None = None
    ax_node_role: str | None = None
    ax_node_name: str | None = None
    uia_automation_id: str | None = None
    uia_name: str | None = None
    uia_class: str | None = None
    uia_control_type: str | None = None

    # Visual evidence
    visual_fingerprint: str | None = None
    bbox: tuple[float, ...] | None = None
    bbox_normalized: tuple[float, float, float, float] | None = None
    nearby_text: list[str] = field(default_factory=list)
    ocr_text: str | None = None

    # Tier tracking
    successful_tier: str | None = None
    tier_attempts: list[TierRecord] = field(default_factory=list)

    # Verification
    pre_action_hash: str | None = None
    post_action_hash: str | None = None

    # Outcome
    succeeded: bool = False
    duration_ms: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Anchor match — result of a healing attempt
# ---------------------------------------------------------------------------

@dataclass
class AnchorMatch:
    """Result of looking up or healing an anchor."""
    target_id: str
    anchor_kind: AnchorKind
    anchor_value: str                       # The actual value to use
    confidence: float
    strategy: HealStrategy | None = None  # Set if this came from healing
    healed: bool = False                     # True if self-healing found this


# ---------------------------------------------------------------------------
# Helper — compute target_id
# ---------------------------------------------------------------------------

def compute_target_id(intent: str, surface: str, domain: str) -> str:
    """Stable hash from (intent, surface, domain).

    Normalizes the intent to reduce drift from minor phrasing differences.
    """
    normalized = intent.strip().lower()
    raw = f"{normalized}|{surface}|{domain}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
