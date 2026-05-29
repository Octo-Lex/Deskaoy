"""Tests for AI-OS alignment bridges."""

from __future__ import annotations

import asyncio
import os
import tempfile
import pytest

from deskaoy.manifest import (
    CAPABILITY_MANIFEST,
    validate_manifest,
    REQUIRED_MANIFEST_KEYS,
)
from deskaoy.storage import StorageResolver
from deskaoy.policy import (
    PolicyBridge,
    PolicyDecision,
    PolicyEffect,
    Permission,
    permissions_for_action,
)
from deskaoy.trace_bridge import TraceBridge, ActionSpan
from deskaoy.result_mapper import map_action_result, AIOSResult, _redact_value
from deskaoy.recovery_bridge import RecoveryBridge, RecoveryEvent, RecoveryEventType
from deskaoy.results.types import ActionError, ActionResult, ErrorCategory, action_result


# ===================================================================
# 1. Capability Manifest
# ===================================================================

class TestManifest:

    def test_valid_manifest(self):
        errors = validate_manifest()
        assert errors == [], f"Manifest validation failed: {errors}"

    def test_capability_id_format(self):
        assert CAPABILITY_MANIFEST["capability_id"].startswith("aios.")

    def test_capability_type(self):
        assert CAPABILITY_MANIFEST["capability_type"] == "agent"

    def test_domains_include_desktop(self):
        assert "desktop_automation" in CAPABILITY_MANIFEST["domains"]

    def test_runtime_not_sandboxed(self):
        assert CAPABILITY_MANIFEST["runtime"]["sandbox"] is False

    def test_runtime_requires_user_session(self):
        assert CAPABILITY_MANIFEST["runtime"]["requires_local_user_session"] is True

    def test_storage_root_under_aios_home(self):
        assert CAPABILITY_MANIFEST["storage"]["production_root"].startswith("AIOS_HOME")

    def test_dry_run_support(self):
        assert CAPABILITY_MANIFEST["dry_run_support"] is True

    def test_stealth_separate(self):
        assert "stealth_browser" not in CAPABILITY_MANIFEST["permissions"]
        assert "stealth_browser" in CAPABILITY_MANIFEST["stealth_permissions"]

    def test_invalid_manifest_missing_keys(self):
        errors = validate_manifest({})
        assert len(errors) > 0
        assert "Missing required keys" in errors[0]

    def test_invalid_capability_id(self):
        m = dict(CAPABILITY_MANIFEST, capability_id="com.example.foo")
        errors = validate_manifest(m)
        assert any("capability_id must start with" in e for e in errors)


# ===================================================================
# 2. Storage Resolver
# ===================================================================

class TestStorageResolver:

    def test_dev_mode_default(self):
        storage = StorageResolver(dev_mode=True)
        assert storage.is_dev_mode is True
        assert storage.storage_mode == "development"

    def test_production_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageResolver(aios_home=tmp, dev_mode=False)
            assert storage.is_dev_mode is False
            assert storage.storage_mode == "production"
            assert str(storage.capability_root).startswith(tmp)

    def test_capability_root_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageResolver(aios_home=tmp, dev_mode=False)
            root = storage.capability_root
            assert "capabilities" in str(root)
            assert "aios.first_party.deskaoy" in str(root)

    def test_capability_root_dev(self):
        storage = StorageResolver(dev_mode=True)
        root = storage.capability_root
        assert ".deskaoy-dev" in str(root)

    def test_resolve_subarea_creates_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageResolver(aios_home=tmp, dev_mode=False)
            path = storage.resolve("action-memory")
            assert path.exists()
            assert path.is_dir()

    def test_resolve_invalid_subarea(self):
        storage = StorageResolver(dev_mode=True)
        with pytest.raises(ValueError, match="Unknown subarea"):
            storage.resolve("secret_stuff")

    def test_resolve_convenience_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageResolver(aios_home=tmp, dev_mode=False)
            assert storage.resolve_action_memory().exists()
            assert storage.resolve_checkpoints().exists()
            assert storage.resolve_artifacts().exists()
            assert storage.resolve_logs().exists()
            assert storage.resolve_temp().exists()


# ===================================================================
# 3. Policy Bridge
# ===================================================================

class TestPolicyBridge:

    @pytest.mark.asyncio
    async def test_dev_mode_allows_all(self):
        bridge = PolicyBridge(dev_mode=True)
        decision = await bridge.preflight("click")
        assert decision.effect == PolicyEffect.ALLOW

    @pytest.mark.asyncio
    async def test_deny_without_service_in_prod(self):
        bridge = PolicyBridge(dev_mode=False)
        decision = await bridge.preflight("click")
        assert decision.effect == PolicyEffect.DENY

    @pytest.mark.asyncio
    async def test_connected_delegates_to_service(self):
        async def mock_preflight(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.ALLOW, reason="mock allow")

        bridge = PolicyBridge(preflight_fn=mock_preflight, dev_mode=False)
        decision = await bridge.preflight("click")
        assert decision.effect == PolicyEffect.ALLOW

    @pytest.mark.asyncio
    async def test_deny_from_service(self):
        async def mock_preflight(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.DENY, reason="blocked")

        bridge = PolicyBridge(preflight_fn=mock_preflight, dev_mode=False)
        decision = await bridge.preflight("click")
        assert decision.effect == PolicyEffect.DENY

    @pytest.mark.asyncio
    async def test_ask_effect(self):
        async def mock_preflight(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.ASK, reason="needs approval")

        bridge = PolicyBridge(preflight_fn=mock_preflight, dev_mode=False)
        decision = await bridge.preflight("click")
        assert decision.effect == PolicyEffect.ASK

    @pytest.mark.asyncio
    async def test_dry_run_only_effect(self):
        async def mock_preflight(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.ALLOW_DRY_RUN_ONLY)

        bridge = PolicyBridge(preflight_fn=mock_preflight, dev_mode=False)
        decision = await bridge.preflight("click")
        assert decision.effect == PolicyEffect.ALLOW_DRY_RUN_ONLY

    @pytest.mark.asyncio
    async def test_stealth_denied_by_default(self):
        bridge = PolicyBridge(dev_mode=True)
        decision = await bridge.check_stealth_policy()
        assert decision.effect == PolicyEffect.DENY

    def test_permissions_for_click(self):
        perms = permissions_for_action("click")
        assert Permission.MOUSE_INPUT in perms

    def test_permissions_for_screenshot(self):
        perms = permissions_for_action("screenshot")
        assert Permission.SCREEN_CAPTURE in perms

    def test_permissions_for_unknown_action(self):
        perms = permissions_for_action("nonexistent")
        assert perms == []

    @pytest.mark.asyncio
    async def test_preflight_error_defaults_to_deny(self):
        async def bad_preflight(perms, ctx):
            raise RuntimeError("service down")

        bridge = PolicyBridge(preflight_fn=bad_preflight, dev_mode=False)
        decision = await bridge.preflight("click")
        assert decision.effect == PolicyEffect.DENY

    def test_is_connected(self):
        async def fn(p, c): pass
        bridge_connected = PolicyBridge(preflight_fn=fn)
        bridge_dev = PolicyBridge(dev_mode=True)
        assert bridge_connected.is_connected is True
        assert bridge_dev.is_connected is False


# ===================================================================
# 4. Trace Bridge
# ===================================================================

class TestTraceBridge:

    @pytest.mark.asyncio
    async def test_diagnostic_mode_stores_locally(self):
        bridge = TraceBridge()
        span = ActionSpan(action="click", duration_ms=50.0)
        await bridge.emit(span)
        assert len(bridge.diagnostic_spans) == 1
        assert bridge.diagnostic_spans[0].action == "click"

    @pytest.mark.asyncio
    async def test_connected_delegates(self):
        emitted = []
        async def mock_emit(span):
            emitted.append(span)

        bridge = TraceBridge(emit_fn=mock_emit)
        span = ActionSpan(action="click", ok=True)
        await bridge.emit(span)
        assert len(emitted) == 1

    def test_span_to_dict(self):
        span = ActionSpan(
            trace_id="t1", span_id="s1", action="click",
            duration_ms=100, confidence=0.95, ok=True,
        )
        d = span.to_dict()
        assert d["trace_id"] == "t1"
        assert d["action"] == "click"
        assert d["ok"] is True

    def test_clear_diagnostics(self):
        bridge = TraceBridge()
        bridge._diagnostic_spans.append(ActionSpan())
        bridge.clear_diagnostics()
        assert len(bridge.diagnostic_spans) == 0


# ===================================================================
# 5. Result Mapper
# ===================================================================

class TestResultMapper:

    def test_map_success(self):
        result = action_result(ok=True)
        mapped = map_action_result(result)
        assert mapped.ok is True
        assert mapped.status == "success"

    def test_map_failure(self):
        err = ActionError(category=ErrorCategory.SELECTOR_NOT_FOUND, message="not found", code="not_found", hint="snapshot")
        result = action_result(ok=False, error=err)
        mapped = map_action_result(result)
        assert mapped.ok is False
        assert mapped.status == "failure"
        assert mapped.error_code == "not_found"

    def test_map_dry_run_never_claims_success(self):
        result = action_result(ok=True)
        mapped = map_action_result(result, dry_run=True)
        assert mapped.ok is False  # Never claim completion for dry runs
        assert mapped.status == "dry_run"

    def test_map_confidence_from_data(self):
        result = action_result(ok=True, data={"visual_confidence": 0.92})
        mapped = map_action_result(result)
        assert mapped.confidence == 0.92

    def test_map_preserves_trace_id(self):
        result = action_result(ok=True)
        mapped = map_action_result(result, trace_id="t123", span_id="s456")
        assert mapped.trace_id == "t123"
        assert mapped.span_id == "s456"

    def test_redact_sensitive(self):
        assert _redact_value("password=secret123") == "***REDACTED***"
        assert _redact_value("Bearer abc123") == "***REDACTED***"
        assert _redact_value("normal text") == "normal text"

    def test_redact_truncates_long(self):
        long_val = "x" * 300
        redacted = _redact_value(long_val)
        assert len(redacted) < 300

    def test_to_dict(self):
        result = action_result(ok=True)
        mapped = map_action_result(result)
        d = mapped.to_dict()
        assert "ok" in d
        assert "status" in d
        assert "dry_run" in d


# ===================================================================
# 6. Recovery Bridge
# ===================================================================

class TestRecoveryBridge:

    @pytest.mark.asyncio
    async def test_can_retry_under_limit(self):
        bridge = RecoveryBridge(max_attempts=3)
        assert bridge.can_retry("click") is True
        bridge.record_attempt("click")
        assert bridge.can_retry("click") is True

    @pytest.mark.asyncio
    async def test_cannot_retry_over_limit(self):
        bridge = RecoveryBridge(max_attempts=2)
        bridge.record_attempt("click")
        bridge.record_attempt("click")
        assert bridge.can_retry("click") is False

    @pytest.mark.asyncio
    async def test_emit_retry_event(self):
        bridge = RecoveryBridge()
        await bridge.emit_retry("click", "Submit", attempt=1, success=False)
        assert len(bridge.events) == 1
        assert bridge.events[0].event_type == RecoveryEventType.RETRY

    @pytest.mark.asyncio
    async def test_emit_recovery_success(self):
        bridge = RecoveryBridge()
        await bridge.emit_retry("click", "Submit", attempt=1, success=True)
        assert bridge.events[0].event_type == RecoveryEventType.RECOVERY

    @pytest.mark.asyncio
    async def test_emit_failure_evidence(self):
        bridge = RecoveryBridge()
        await bridge.emit_failure_evidence("click", "Submit", "All retries failed", attempt_count=3)
        assert bridge.events[0].event_type == RecoveryEventType.FAILURE_EVIDENCE

    @pytest.mark.asyncio
    async def test_connected_delegates(self):
        emitted = []
        async def mock_fn(event):
            emitted.append(event)

        bridge = RecoveryBridge(emit_fn=mock_fn)
        await bridge.emit_retry("click", "X", attempt=1)
        assert len(emitted) == 1

    @pytest.mark.asyncio
    async def test_policy_can_set_max_attempts(self):
        bridge = RecoveryBridge(max_attempts=3)
        bridge.max_attempts = 5  # AI-OS policy override
        assert bridge.max_attempts == 5

    def test_clear(self):
        bridge = RecoveryBridge()
        bridge._events.append(RecoveryEvent(event_type=RecoveryEventType.RETRY))
        bridge._attempt_counts["click"] = 3
        bridge.clear()
        assert len(bridge.events) == 0
        assert bridge._attempt_counts == {}

    def test_event_to_dict(self):
        event = RecoveryEvent(
            event_type=RecoveryEventType.RETRY,
            action="click",
            attempt_number=2,
            max_attempts=3,
        )
        d = event.to_dict()
        assert d["event_type"] == "retry"
        assert d["action"] == "click"
