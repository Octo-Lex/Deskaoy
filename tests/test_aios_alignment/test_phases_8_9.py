"""Tests for AI-OS realignment phases 8–9: action memory learning + stealth separation."""

from __future__ import annotations

import pytest

from deskaoy.grounding.artifacts import (
    KNOWN_ARTIFACTS,
    ModelArtifact,
    get_artifact,
    register_artifact,
)
from deskaoy.memory.learning import (
    AUTO_ACCEPTABLE_CATEGORIES,
    REVIEW_REQUIRED_CATEGORIES,
    LearningCategory,
    LearningEvidence,
    ReviewStatus,
    apply_policy_to_evidence,
    classify_evidence,
)
from deskaoy.stealth_gate import (
    StealthGate,
    default_stealth_gate,
)

# ===================================================================
# Phase 8: Action Memory as Learning Evidence
# ===================================================================

class TestLearningEvidence:

    def test_selector_healing_auto_acceptable(self):
        assert classify_evidence(LearningCategory.SELECTOR_HEALING) is True

    def test_anchor_discovery_auto_acceptable(self):
        assert classify_evidence(LearningCategory.ANCHOR_DISCOVERY) is True

    def test_pattern_inference_not_auto_acceptable(self):
        assert classify_evidence(LearningCategory.PATTERN_INFERENCE) is False

    def test_workflow_optimization_not_auto_acceptable(self):
        assert classify_evidence(LearningCategory.WORKFLOW_OPTIMIZATION) is False

    def test_apply_policy_auto_accept(self):
        evidence = LearningEvidence(
            category=LearningCategory.SELECTOR_HEALING,
            domain="example.com",
            confidence=0.9,
        )
        result = apply_policy_to_evidence(evidence, policy_allows_auto_accept=True)
        assert result.review_status == ReviewStatus.AUTO_ACCEPTED
        assert result.auto_acceptable is True

    def test_apply_policy_blocked_auto_accept(self):
        evidence = LearningEvidence(
            category=LearningCategory.SELECTOR_HEALING,
            domain="example.com",
        )
        result = apply_policy_to_evidence(evidence, policy_allows_auto_accept=False)
        assert result.review_status == ReviewStatus.PENDING

    def test_apply_policy_pattern_inference_always_pending(self):
        evidence = LearningEvidence(
            category=LearningCategory.PATTERN_INFERENCE,
        )
        result = apply_policy_to_evidence(evidence, policy_allows_auto_accept=True)
        assert result.review_status == ReviewStatus.PENDING
        assert result.auto_acceptable is False

    def test_evidence_to_dict(self):
        evidence = LearningEvidence(
            evidence_id="ev123",
            category=LearningCategory.ANCHOR_DISCOVERY,
            domain="example.com",
            confidence=0.85,
        )
        d = evidence.to_dict()
        assert d["category"] == "anchor_discovery"
        assert d["confidence"] == 0.85

    def test_auto_acceptable_categories_set(self):
        assert LearningCategory.SELECTOR_HEALING in AUTO_ACCEPTABLE_CATEGORIES
        assert LearningCategory.ANCHOR_DISCOVERY in AUTO_ACCEPTABLE_CATEGORIES

    def test_review_required_categories_set(self):
        assert LearningCategory.PATTERN_INFERENCE in REVIEW_REQUIRED_CATEGORIES
        assert LearningCategory.WORKFLOW_OPTIMIZATION in REVIEW_REQUIRED_CATEGORIES


# ===================================================================
# Phase 9: Stealth Separation
# ===================================================================

class TestStealthGate:

    def test_default_stealth_disabled(self):
        gate = StealthGate()
        assert gate.is_enabled is False

    def test_module_default_disabled(self):
        assert default_stealth_gate.is_enabled is False

    @pytest.mark.asyncio
    async def test_disabled_gate_blocks(self):
        gate = StealthGate(enabled=False)
        decision = await gate.check_policy()
        assert decision.allowed is False
        assert "disabled by default" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_enabled_gate_allows(self):
        gate = StealthGate(enabled=True)
        decision = await gate.check_policy()
        assert decision.allowed is True
        assert decision.requires_disclosure is True

    def test_enable_explicit(self):
        gate = StealthGate(enabled=False)
        gate.enable(reason="dev override")
        assert gate.is_enabled is True

    def test_disable(self):
        gate = StealthGate(enabled=True)
        gate.disable()
        assert gate.is_enabled is False

    @pytest.mark.asyncio
    async def test_policy_bridge_deny(self):
        from deskaoy.policy import PolicyBridge, PolicyDecision, PolicyEffect
        async def deny_stealth(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.DENY, reason="blocked")
        bridge = PolicyBridge(preflight_fn=deny_stealth, dev_mode=False)
        gate = StealthGate(enabled=False, policy_bridge=bridge)
        decision = await gate.check_policy()
        assert decision.allowed is False

    @pytest.mark.asyncio
    async def test_policy_bridge_allow(self):
        from deskaoy.policy import PolicyBridge, PolicyDecision, PolicyEffect
        async def allow_stealth(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.ALLOW, reason="ok")
        bridge = PolicyBridge(preflight_fn=allow_stealth, dev_mode=False)
        gate = StealthGate(enabled=False, policy_bridge=bridge)
        decision = await gate.check_policy()
        assert decision.allowed is True
        assert decision.requires_receipt is True


# ===================================================================
# Phase 9: Model Artifact Metadata
# ===================================================================

class TestModelArtifacts:

    def test_known_artifacts_populated(self):
        assert len(KNOWN_ARTIFACTS) >= 3

    def test_omniparser_artifact(self):
        art = get_artifact("omniparser_v2_detector")
        assert art is not None
        assert art.license == "MIT"
        assert "ultralytics" in art.runtime_requirements

    def test_florence_artifact(self):
        art = get_artifact("florence2_captioner")
        assert art is not None
        assert "transformers" in art.runtime_requirements

    def test_paddleocr_artifact(self):
        art = get_artifact("paddleocr")
        assert art is not None
        assert art.license == "Apache-2.0"

    def test_unknown_artifact(self):
        assert get_artifact("nonexistent_model") is None

    def test_register_artifact(self):
        new_art = ModelArtifact(
            model_id="test_model",
            version="1.0",
            license="MIT",
        )
        register_artifact(new_art)
        assert get_artifact("test_model") is not None

    def test_artifact_to_dict(self):
        art = get_artifact("omniparser_v2_detector")
        d = art.to_dict()
        assert "model_id" in d
        assert "license" in d
        assert "runtime_requirements" in d
        assert "signature_status" in d
