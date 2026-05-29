"""Cascade engine — surface-agnostic UI interaction layer.

Exports core types and protocols. Snapshot types are imported directly
from their submodules for explicit dependency tracking.
"""

from deskaoy.cascade.snapshot_store import SnapshotStore
from deskaoy.cascade.snapshot_types import (
    SnapshotElement,
    SnapshotInfo,
    SnapshotRecord,
    StaleResult,
)
from deskaoy.cascade.types import (
    AXNode,
    AXSnapshot,
    CascadeResult,
    CompoundInfo,
    Tier,
    TierAttempt,
    TierOutcome,
    VisionRequest,
    VisionResponse,
)

__all__ = [
    # Core cascade types
    "AXNode",
    "AXSnapshot",
    "CascadeResult",
    "CompoundInfo",
    "Tier",
    "TierAttempt",
    "TierOutcome",
    "VisionRequest",
    "VisionResponse",
    # Snapshot types (BATCH-24)
    "SnapshotElement",
    "SnapshotInfo",
    "SnapshotRecord",
    "StaleResult",
    "SnapshotStore",
]
