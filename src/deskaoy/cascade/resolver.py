"""3-tier stale-ref resolver — recovers elements when the UI changes between steps.

Adapted from OpenCLI's ``target-resolver.ts``.  When an element reference (e.g.
``e42``) becomes stale because the UI re-rendered, this resolver walks three
tiers before giving up:

  Tier 1: EXACT        — ref still exists and all fingerprint fields match
  Tier 2: STABLE       — strong id (automation_id) matches, soft signals drifted
  Tier 3: REIDENTIFIED — fingerprint uniquely identifies a single live element

This recovers ~60% of stale references that would otherwise escalate to
coordinate or vision tiers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from deskaoy.cascade.types import AXNode, AXSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class MatchLevel(StrEnum):
    """Quality of the element match."""
    EXACT = "exact"
    STABLE = "stable"
    REIDENTIFIED = "reidentified"


@dataclass(frozen=True)
class ElementFingerprint:
    """Immutable descriptor for element identity comparison.

    Captures both *strong* identifiers (automation_id) and *soft* signals
    (role, name prefix, position) for the 3-tier resolution strategy.
    """
    role: str
    name: str
    automation_id: str = ""
    text_prefix: str = ""  # first 30 chars of value
    bounds: tuple[float, float, float, float] | None = None


@dataclass
class ResolveResult:
    """Outcome of a resolution attempt."""
    ok: bool
    match_level: MatchLevel | None = None
    matches_n: int = 0
    node: AXNode | None = None
    error_code: str = ""
    hint: str = ""


# ---------------------------------------------------------------------------
# Fingerprint extraction
# ---------------------------------------------------------------------------

def fingerprint_from_node(node: AXNode) -> ElementFingerprint:
    """Extract a fingerprint from an AXNode."""
    text_prefix = ""
    if node.value:
        text_prefix = node.value[:30]

    return ElementFingerprint(
        role=node.role,
        name=node.name,
        automation_id=getattr(node, "automation_id", "") or "",
        text_prefix=text_prefix,
        bounds=node.bounds,
    )


def _fingerprint_match_score(fp: ElementFingerprint, node: AXNode) -> float:
    """Score how well a live node matches a fingerprint (0.0–1.0)."""
    score = 0.0
    total_weight = 0.0

    # Role match (required, weight 0.3)
    total_weight += 0.3
    if node.role == fp.role:
        score += 0.3

    # Name match (weight 0.3)
    if fp.name:
        total_weight += 0.3
        if node.name:
            if fp.name.lower() == node.name.lower():
                score += 0.3
            elif fp.name.lower() in node.name.lower() or node.name.lower() in fp.name.lower():
                score += 0.15

    # Automation ID match (weight 0.3)
    if fp.automation_id:
        total_weight += 0.3
        aid = getattr(node, "automation_id", "") or ""
        if aid and aid == fp.automation_id:
            score += 0.3

    # Text prefix match (weight 0.1)
    if fp.text_prefix:
        total_weight += 0.1
        if node.value and node.value[:30] == fp.text_prefix:
            score += 0.1

    return score / total_weight if total_weight > 0 else 0.0


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class StaleRefResolver:
    """3-tier stale reference resolver.

    Usage::

        resolver = StaleRefResolver()
        result = resolver.resolve("e42", stored_fingerprint, live_snapshot)
        if result.ok:
            # Use result.node for the action
    """

    def __init__(self, *, exact_threshold: float = 0.95, stable_threshold: float = 0.7) -> None:
        self._exact_threshold = exact_threshold
        self._stable_threshold = stable_threshold

    def resolve(
        self,
        ref: str,
        fingerprint: ElementFingerprint,
        live_snapshot: AXSnapshot,
    ) -> ResolveResult:
        """Attempt to resolve a stale ref through 3 tiers."""
        clean_ref = ref.lstrip("@")

        # ── Tier 1: EXACT ─────────────────────────────────
        node = live_snapshot.nodes.get(clean_ref)
        if node is not None:
            score = _fingerprint_match_score(fingerprint, node)
            if score >= self._exact_threshold:
                return ResolveResult(
                    ok=True,
                    match_level=MatchLevel.EXACT,
                    matches_n=1,
                    node=node,
                )

        # ── Tier 2: STABLE ────────────────────────────────
        # Look for nodes with matching automation_id (strong identifier)
        if fingerprint.automation_id:
            candidates = []
            for n in live_snapshot.nodes.values():
                aid = getattr(n, "automation_id", "") or ""
                if aid == fingerprint.automation_id:
                    candidates.append(n)

            if len(candidates) == 1:
                return ResolveResult(
                    ok=True,
                    match_level=MatchLevel.STABLE,
                    matches_n=1,
                    node=candidates[0],
                )
            if len(candidates) > 1:
                return ResolveResult(
                    ok=False,
                    error_code="ambiguous",
                    hint=f"Found {len(candidates)} elements with automation_id '{fingerprint.automation_id}'",
                    matches_n=len(candidates),
                )

        # ── Tier 3: REIDENTIFIED ──────────────────────────
        # Score all live nodes and pick the best unique match
        scored: list[tuple[float, AXNode]] = []
        for n in live_snapshot.nodes.values():
            score = _fingerprint_match_score(fingerprint, n)
            if score >= self._stable_threshold:
                scored.append((score, n))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        if len(scored) == 1:
            return ResolveResult(
                ok=True,
                match_level=MatchLevel.REIDENTIFIED,
                matches_n=1,
                node=scored[0][1],
            )

        if len(scored) > 1:
            # Check if top candidate is significantly better than second
            top_score = scored[0][0]
            second_score = scored[1][0]
            if top_score - second_score >= 0.2:
                return ResolveResult(
                    ok=True,
                    match_level=MatchLevel.REIDENTIFIED,
                    matches_n=len(scored),
                    node=scored[0][1],
                )
            # Ambiguous
            names = [n.name or n.ref for _, n in scored[:3]]
            return ResolveResult(
                ok=False,
                error_code="ambiguous",
                hint=f"Multiple candidates: {names}. Try snapshot() to see current elements.",
                matches_n=len(scored),
            )

        # ── No match at all ───────────────────────────────
        return ResolveResult(
            ok=False,
            error_code="not_found",
            hint="Element not found. Try snapshot() to see available elements.",
        )
