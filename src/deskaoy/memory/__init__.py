"""Action memory — durable target identities with self-healing grounding.

For every UI action, learn a durable target identity so the agent
never solves the same problem twice.

Three paths:
  1. WRITE: record() — after action, store evidence as DurableTarget
  2. READ:  recall() — before action, retrieve best-known anchors
  3. HEAL:  heal()   — when selector breaks, recover via AX/vision/OCR

Storage: in-memory LRU cache + per-domain JSON files on disk.
"""

from deskaoy.memory.fact_extractor import FactExtractor
from deskaoy.memory.facts import Fact, FactStore, SoulAspect
from deskaoy.memory.fingerprint import (
    compute_visual_fingerprint,
    crop_fingerprint,
    fingerprint_distance,
)
from deskaoy.memory.healer import HealResult, SelfHealer
from deskaoy.memory.matching import match_ax_node, rank_anchors, score_target
from deskaoy.memory.store import ActionMemory, MemoryConfig
from deskaoy.memory.types import (
    ActionEvidence,
    AnchorKind,
    AnchorMatch,
    DurableTarget,
    HealStrategy,
    SurfaceKind,
    TierRecord,
    compute_target_id,
)

__all__ = [
    # Store
    "ActionMemory",
    "MemoryConfig",
    # Types
    "ActionEvidence",
    "AnchorKind",
    "AnchorMatch",
    "DurableTarget",
    "HealStrategy",
    "SurfaceKind",
    "TierRecord",
    "compute_target_id",
    # Matching
    "match_ax_node",
    "rank_anchors",
    "score_target",
    # Healing
    "HealResult",
    "SelfHealer",
    # Fingerprint
    "compute_visual_fingerprint",
    "crop_fingerprint",
    "fingerprint_distance",
    # Facts + Soul
    "Fact",
    "FactStore",
    "SoulAspect",
    "FactExtractor",
]
