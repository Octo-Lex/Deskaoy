"""ActionMemory — persistent store of durable target identities.

Storage hierarchy:
  - Hot: in-memory LRU cache (fast lookup)
  - Warm: per-domain JSON files (persistent across sessions)

The key insight: target_id is derived from (intent, surface, domain),
not from selectors which break. This means "click login button on example.com"
always maps to the same memory entry regardless of DOM changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from deskaoy.cascade.types import AXSnapshot
from deskaoy.memory.healer import HealResult, SelfHealer
from deskaoy.memory.matching import rank_anchors, score_target
from deskaoy.memory.types import (
    ActionEvidence,
    AnchorKind,
    AnchorMatch,
    DurableTarget,
    TierRecord,
    compute_target_id,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class MemoryConfig:
    """Configuration for ActionMemory."""

    def __init__(
        self,
        *,
        store_dir: Path | None = None,
        max_entries_per_domain: int = 500,
        recall_confidence_threshold: float = 0.5,
        heal_on_failure: bool = True,
        policy_allows_auto_accept: bool = True,
    ) -> None:
        # Use AIOS_HOME storage when available, fallback to standalone
        if store_dir is not None:
            self.store_dir = store_dir
        else:
            try:
                from deskaoy.storage import StorageResolver
                self.store_dir = StorageResolver().resolve_action_memory()
            except Exception:
                self.store_dir = Path.home() / ".deskaoy" / "action-memory"
        self.max_entries_per_domain = max_entries_per_domain
        self.recall_confidence_threshold = recall_confidence_threshold
        self.heal_on_failure = heal_on_failure
        self.policy_allows_auto_accept = policy_allows_auto_accept


# ---------------------------------------------------------------------------
# ActionMemory — the main store
# ---------------------------------------------------------------------------


class ActionMemory:
    """Persistent action memory with self-healing retrieval.

    Usage:
        memory = ActionMemory()

        # Record after action
        await memory.record(evidence)

        # Recall before action
        target = await memory.recall("click login", "browser", "example.com")

        # Self-heal when selector breaks
        result = await memory.heal(target, snapshot)
    """

    def __init__(
        self,
        config: MemoryConfig | None = None,
        healer: SelfHealer | None = None,
    ) -> None:
        self._config = config or MemoryConfig()
        self._healer = healer or SelfHealer()

        # Hot cache: domain -> OrderedDict[target_id, DurableTarget]
        self._domains: dict[str, OrderedDict[str, DurableTarget]] = {}

        # Stats
        self._hits = 0
        self._misses = 0
        self._heal_attempts = 0
        self._heal_successes = 0

    # =====================================================================
    # WRITE PATH — record evidence after action
    # =====================================================================

    async def record(self, evidence: ActionEvidence) -> DurableTarget:
        """Record action evidence and return the updated DurableTarget.

        Creates a new target if this is the first time, or merges with
        the existing target if we've seen this (intent, surface, domain) before.
        """
        domain = evidence.domain or "unknown"
        target_id = compute_target_id(evidence.target_description, evidence.surface, domain)

        domain_cache = self._domains.setdefault(domain, OrderedDict())
        target = domain_cache.get(target_id)

        if target is None:
            target = self._create_target(target_id, evidence, domain)
            domain_cache[target_id] = target
            self._evict_if_needed(domain)
            logger.debug(
                "Created new target %s for intent '%s' on %s",
                target_id[:8], evidence.target_description, domain,
            )
        else:
            self._merge_evidence(target, evidence)
            domain_cache.move_to_end(target_id)

        target.last_used = time.monotonic()
        target.touch_count = getattr(target, "touch_count", 0) + 1

        # Async persist (non-blocking)
        await self.persist(domain)

        return target

    # =====================================================================
    # READ PATH — recall before action
    # =====================================================================

    async def recall(
        self,
        intent: str,
        surface: str,
        domain: str,
    ) -> DurableTarget | None:
        """Look up a previously-seen target by intent, surface, domain.

        Returns None if no target exists or if confidence is below threshold.
        """
        target_id = compute_target_id(intent, surface, domain)
        domain_cache = self._domains.get(domain)
        if domain_cache is None:
            # Try loading from disk
            await self.load(domain)
            domain_cache = self._domains.get(domain)

        if domain_cache is None:
            self._misses += 1
            return None

        target = domain_cache.get(target_id)
        if target is None:
            self._misses += 1
            return None

        score = score_target(target)
        if score < self._config.recall_confidence_threshold:
            self._misses += 1
            logger.debug(
                "Target %s found but below threshold (%.2f < %.2f)",
                target_id[:8], score, self._config.recall_confidence_threshold,
            )
            return None

        self._hits += 1
        target.last_used = time.monotonic()
        domain_cache.move_to_end(target_id)
        return target

    async def recall_by_context(
        self,
        intent: str,
        url: str,
    ) -> list[DurableTarget]:
        """Find all targets matching an intent on a given URL domain.

        Useful when the exact domain key isn't known.
        """
        results: list[DurableTarget] = []
        target_id = compute_target_id(intent, "browser", url)

        for domain_cache in self._domains.values():
            target = domain_cache.get(target_id)
            if target and score_target(target) >= self._config.recall_confidence_threshold:
                results.append(target)

        results.sort(key=lambda t: score_target(t), reverse=True)
        return results

    async def get_anchors(
        self,
        intent: str,
        surface: str,
        domain: str,
    ) -> list[AnchorMatch]:
        """Get ranked anchor list for a target.

        Returns empty list if target not found or below threshold.
        """
        target = await self.recall(intent, surface, domain)
        if target is None:
            return []
        return rank_anchors(target)

    # =====================================================================
    # HEAL PATH — self-healing
    # =====================================================================

    async def heal(
        self,
        target: DurableTarget,
        snapshot: AXSnapshot | None = None,
        *,
        current_screenshot: bytes | None = None,
        current_detections: list | None = None,
        viewport_size: tuple[int, int] = (0, 0),
    ) -> HealResult:
        """Attempt to heal a broken anchor.

        If healing succeeds, the target's anchors are updated in memory.
        """
        self._heal_attempts += 1

        result = await self._healer.heal(
            target,
            snapshot,
            current_screenshot=current_screenshot,
            current_detections=current_detections,
            viewport_size=viewport_size,
        )

        if result.success and result.match:
            self._heal_successes += 1

            # Phase 8: emit learning evidence
            try:
                from deskaoy.memory.learning import (
                    LearningCategory,
                    LearningEvidence,
                    apply_policy_to_evidence,
                )
                evidence = apply_policy_to_evidence(
                    LearningEvidence(
                        category=LearningCategory.SELECTOR_HEALING,
                        domain=target.domain or "unknown",
                        intent=target.intent_fingerprint[:30] if target.intent_fingerprint else "",
                        anchor_value=result.match.anchor_value or "",
                        confidence=result.match.confidence,
                    ),
                    policy_allows_auto_accept=getattr(
                        self._config, "policy_allows_auto_accept", True
                    ),
                )
                logger.debug(
                    "Learning evidence: %s [%s] → %s",
                    evidence.evidence_id[:8] if evidence.evidence_id else "",
                    evidence.category,
                    evidence.review_status,
                )
            except Exception:
                pass  # Non-fatal: learning evidence is supplementary

            self._update_target_after_heal(target, result.match)
            await self.persist(target.domain)

        return result

    # =====================================================================
    # PERSISTENCE
    # =====================================================================

    async def persist(self, domain: str) -> None:
        """Persist a domain's targets to disk."""
        domain_cache = self._domains.get(domain)
        if domain_cache is None:
            return

        data = {
            tid: t.to_dict() for tid, t in domain_cache.items()
        }
        path = self._config.store_dir / f"{_safe_filename(domain)}.json"
        await asyncio.to_thread(self._write_json, path, data)

    async def load(self, domain: str) -> int:
        """Load a domain's targets from disk.

        Returns the number of targets loaded.
        """
        path = self._config.store_dir / f"{_safe_filename(domain)}.json"
        data = await asyncio.to_thread(self._read_json, path)
        if data is None:
            return 0

        domain_cache: OrderedDict[str, DurableTarget] = OrderedDict()
        for tid, target_dict in data.items():
            try:
                domain_cache[tid] = DurableTarget.from_dict(target_dict)
            except Exception:
                logger.warning("Skipping corrupt target %s for %s", tid[:8], domain)

        self._domains[domain] = domain_cache
        return len(domain_cache)

    async def load_all(self) -> int:
        """Load all domains from disk.

        Returns total number of targets loaded.
        """
        store_dir = self._config.store_dir
        if not store_dir.exists():
            return 0

        total = 0
        for path in store_dir.glob("*.json"):
            domain = path.stem
            total += await self.load(domain)
        return total

    # =====================================================================
    # STATS
    # =====================================================================

    @property
    def stats(self) -> dict[str, Any]:
        """Return usage statistics."""
        total_targets = sum(len(cache) for cache in self._domains.values())
        return {
            "total_targets": total_targets,
            "domains": list(self._domains.keys()),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / max(1, self._hits + self._misses),
            "heal_attempts": self._heal_attempts,
            "heal_successes": self._heal_successes,
            "heal_rate": self._heal_successes / max(1, self._heal_attempts),
        }

    def domain_stats(self, domain: str) -> dict[str, Any]:
        """Stats for a specific domain."""
        cache = self._domains.get(domain, OrderedDict())
        if not cache:
            return {"target_count": 0, "avg_confidence": 0.0}

        confidences = [score_target(t) for t in cache.values()]
        return {
            "target_count": len(cache),
            "avg_confidence": sum(confidences) / len(confidences),
            "best_target": max(confidences) if confidences else 0.0,
        }

    # =====================================================================
    # INTERNAL
    # =====================================================================

    def _create_target(
        self,
        target_id: str,
        evidence: ActionEvidence,
        domain: str,
    ) -> DurableTarget:
        """Create a new DurableTarget from evidence."""
        target = DurableTarget(
            target_id=target_id,
            intent=evidence.target_description,
            surface=evidence.surface,
            domain=domain,
            # Structural anchors
            selector=evidence.selector,
            uia_automation_id=evidence.uia_automation_id,
            uia_name=evidence.uia_name,
            uia_class=evidence.uia_class,
            uia_control_type=evidence.uia_control_type,
            # Visual anchors
            visual_fingerprint=evidence.visual_fingerprint,
            bbox_normalized=evidence.bbox_normalized,
            nearby_text=list(evidence.nearby_text),
            ocr_text=evidence.ocr_text,
            # Performance
            successful_tier=evidence.successful_tier,
            tier_history=list(evidence.tier_attempts),
            success_count=1 if evidence.succeeded else 0,
            fail_count=0 if evidence.succeeded else 1,
            confidence=1.0 if evidence.succeeded else 0.5,
            # Verification
            pre_action_hash=evidence.pre_action_hash,
            post_action_hash=evidence.post_action_hash,
        )

        # Compute AX path from node evidence
        if evidence.ax_node_ref:
            parts = []
            if evidence.ax_node_role:
                parts.append(evidence.ax_node_role)
            if evidence.ax_node_name:
                parts.append(evidence.ax_node_name)
            if evidence.ax_node_ref:
                parts.append(evidence.ax_node_ref)
            target.ax_path = "/".join(parts)

        return target

    def _merge_evidence(self, target: DurableTarget, evidence: ActionEvidence) -> None:
        """Merge new evidence into an existing target."""
        # Update anchors — only overwrite with non-None values
        if evidence.selector:
            target.selector = evidence.selector
        if evidence.uia_automation_id:
            target.uia_automation_id = evidence.uia_automation_id
        if evidence.uia_name:
            target.uia_name = evidence.uia_name
        if evidence.uia_class:
            target.uia_class = evidence.uia_class
        if evidence.uia_control_type:
            target.uia_control_type = evidence.uia_control_type
        if evidence.visual_fingerprint:
            target.visual_fingerprint = evidence.visual_fingerprint
        if evidence.bbox_normalized:
            target.bbox_normalized = evidence.bbox_normalized
        if evidence.ocr_text:
            target.ocr_text = evidence.ocr_text
        if evidence.pre_action_hash:
            target.pre_action_hash = evidence.pre_action_hash
        if evidence.post_action_hash:
            target.post_action_hash = evidence.post_action_hash

        # Update nearby text (merge, dedupe)
        for text in evidence.nearby_text:
            if text and text not in target.nearby_text:
                target.nearby_text.append(text)
                if len(target.nearby_text) > 10:  # cap at 10
                    target.nearby_text.pop(0)

        # Update performance tracking
        if evidence.succeeded:
            target.success_count += 1
            target.last_succeeded = time.time()
            target.confidence = min(1.0, target.confidence + 0.05)
        else:
            target.fail_count += 1
            target.confidence = max(0.1, target.confidence - 0.1)

        if evidence.successful_tier:
            target.successful_tier = evidence.successful_tier

        # Append tier records (cap at 50)
        target.tier_history.extend(evidence.tier_attempts)
        if len(target.tier_history) > 50:
            target.tier_history = target.tier_history[-50:]

        target.version += 1
        target.updated_at = time.time() if hasattr(target, "updated_at") else None

    def _update_target_after_heal(self, target: DurableTarget, match: AnchorMatch) -> None:
        """Update a target with healed anchor information."""
        # Add healed tier record
        record = TierRecord(
            tier="healed",
            outcome="healed",
            duration_ms=0.0,
            anchor_used=match.anchor_kind.value if isinstance(match.anchor_kind, AnchorKind) else str(match.anchor_kind),
        )
        target.tier_history.append(record)
        target.success_count += 1
        target.confidence = min(1.0, target.confidence + 0.1)
        target.last_succeeded = time.time()
        target.version += 1

    def _evict_if_needed(self, domain: str) -> None:
        """Evict lowest-confidence entries when domain exceeds max size."""
        domain_cache = self._domains.get(domain)
        if domain_cache is None:
            return
        while len(domain_cache) > self._config.max_entries_per_domain:
            # Remove oldest (LRU) entry
            evicted_key, _ = domain_cache.popitem(last=False)
            logger.debug("Evicted target %s for domain %s", evicted_key[:8], domain)

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read memory file %s: %s", path, e)
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_filename(domain: str) -> str:
    """Convert a domain to a safe filename."""
    return domain.replace("/", "_").replace("\\", "_").replace(":", "_")[:100]
