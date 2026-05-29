"""Action memory learning evidence — policy-bound selector healing.

Action memory is NOT authoritative user memory. It is capability learning
evidence that must be reviewable and policy-bound.

Low-risk selector healing may be auto-accepted by policy.
User preference inference should become reviewable learning unless
policy allows direct acceptance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Learning evidence types
# ---------------------------------------------------------------------------

class LearningCategory(StrEnum):
    """Categories of learning evidence from action memory."""
    SELECTOR_HEALING = "selector_healing"       # Low risk: healed a broken selector
    ANCHOR_DISCOVERY = "anchor_discovery"        # Found a new stable anchor
    PATTERN_INFERENCE = "pattern_inference"      # Inferred a user preference
    WORKFLOW_OPTIMIZATION = "workflow_optimization"  # Optimized a repeated workflow
    FAILURE_PATTERN = "failure_pattern"          # Recorded a failure pattern


class ReviewStatus(StrEnum):
    """Review status for learning evidence."""
    PENDING = "pending"
    AUTO_ACCEPTED = "auto_accepted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class LearningEvidence:
    """A single piece of action memory learning, reviewable by policy."""
    evidence_id: str = ""
    category: LearningCategory = LearningCategory.SELECTOR_HEALING
    domain: str = ""
    surface: str = ""
    intent: str = ""
    anchor_value: str = ""
    confidence: float = 0.0
    hit_count: int = 0
    review_status: ReviewStatus = ReviewStatus.PENDING
    auto_acceptable: bool = False
    policy_decision_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "category": str(self.category),
            "domain": self.domain,
            "surface": self.surface,
            "intent": self.intent,
            "anchor_value": self.anchor_value,
            "confidence": self.confidence,
            "hit_count": self.hit_count,
            "review_status": str(self.review_status),
            "auto_acceptable": self.auto_acceptable,
            "policy_decision_id": self.policy_decision_id,
        }


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

# Categories that may be auto-accepted by policy (low risk)
AUTO_ACCEPTABLE_CATEGORIES = frozenset({
    LearningCategory.SELECTOR_HEALING,
    LearningCategory.ANCHOR_DISCOVERY,
})

# Categories that ALWAYS require review (higher risk)
REVIEW_REQUIRED_CATEGORIES = frozenset({
    LearningCategory.PATTERN_INFERENCE,
    LearningCategory.WORKFLOW_OPTIMIZATION,
})


def classify_evidence(category: LearningCategory) -> bool:
    """Determine if a learning evidence item is auto-acceptable."""
    return category in AUTO_ACCEPTABLE_CATEGORIES


def apply_policy_to_evidence(
    evidence: LearningEvidence,
    *,
    policy_allows_auto_accept: bool = True,
) -> LearningEvidence:
    """Apply policy to a learning evidence item.

    If policy allows auto-accept and the category is low-risk,
    mark as auto_accepted. Otherwise, leave as pending for review.
    """
    evidence.auto_acceptable = classify_evidence(evidence.category)

    if evidence.auto_acceptable and policy_allows_auto_accept:
        evidence.review_status = ReviewStatus.AUTO_ACCEPTED
        logger.debug(
            "Auto-accepted learning evidence: %s [%s]",
            evidence.evidence_id, evidence.category,
        )
    else:
        evidence.review_status = ReviewStatus.PENDING
        logger.debug(
            "Learning evidence pending review: %s [%s]",
            evidence.evidence_id, evidence.category,
        )

    return evidence
