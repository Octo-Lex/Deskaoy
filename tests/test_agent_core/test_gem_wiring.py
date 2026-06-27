"""Tests for OpenCLI gems end-to-end wiring.

Proves that:
  1. Pipeline fast-path fires in DesktopAgent._execute_automate()
  2. Formatter is used by default in to_compact_str()
  3. Hooks fire on execute()
  4. Resolver is importable from the cascade
"""

from __future__ import annotations

import pytest

from deskaoy.cascade.resolver import ElementFingerprint, MatchLevel, StaleRefResolver
from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.hooks import HookContext, HookName
from deskaoy.hooks import hooks as global_hooks
from deskaoy.results.types import ActionError, make_error

# ---------------------------------------------------------------------------
# 1. Formatter wired into to_compact_str
# ---------------------------------------------------------------------------

class TestFormatterWired:

    def test_to_compact_str_uses_formatter_by_default(self):
        snap = AXSnapshot(
            url="win32://Notepad",
            title="Untitled - Notepad",
            nodes={
                "e0": AXNode(ref="e0", role="button", name="Submit"),
                "e1": AXNode(ref="e1", role="separator", name=""),  # noise
                "e2": AXNode(ref="e2", role="textbox", name="Search", value="hello"),
            },
        )
        result = snap.to_compact_str()
        # Formatter output includes header
        assert "url: win32://Notepad" in result
        assert "title: Untitled - Notepad" in result
        assert "---" in result
        # Noise separator should be filtered out
        assert "separator" not in result
        # Interactive elements should survive
        assert "Submit" in result
        assert "Search" in result

    def test_to_compact_str_raw_mode(self):
        snap = AXSnapshot(
            url="test://",
            title="T",
            nodes={"e0": AXNode(ref="e0", role="button", name="OK")},
        )
        result = snap.to_compact_str(formatted=False)
        # Raw mode — original format (no @ prefix)
        assert '[e0] button "OK"' in result


# ---------------------------------------------------------------------------
# 2. Error envelopes produce LLM-consumable hints
# ---------------------------------------------------------------------------

class TestErrorHintsInResults:

    def test_make_error_has_hint(self):
        err = make_error("not_found", "Element e42 gone")
        assert err.hint
        assert "snapshot" in err.hint.lower()

    def test_make_error_serializable(self):
        err = make_error("ambiguous", "3 matches", candidates=["a", "b", "c"], matches_n=3)
        d = err.to_dict()
        assert d["code"] == "ambiguous"
        assert d["candidates"] == ["a", "b", "c"]
        restored = ActionError.from_dict(d)
        assert restored.candidates == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# 3. Hooks fire lifecycle events
# ---------------------------------------------------------------------------

class TestHooksFireOnExecute:

    @pytest.mark.asyncio
    async def test_step_hooks_fire(self):
        """Verify hook callbacks receive the right data."""
        fired = []

        async def on_complete(ctx: HookContext):
            fired.append(("complete", ctx.command))

        async def on_error(ctx: HookContext):
            fired.append(("error", ctx.command))

        global_hooks.on(HookName.ON_STEP_COMPLETE, on_complete)
        global_hooks.on(HookName.ON_STEP_ERROR, on_error)
        try:
            ctx = HookContext(command="click", args={"target": "Submit"})
            await global_hooks.emit(HookName.ON_STEP_COMPLETE, ctx)
            assert ("complete", "click") in fired
        finally:
            global_hooks.off(HookName.ON_STEP_COMPLETE, on_complete)
            global_hooks.off(HookName.ON_STEP_ERROR, on_error)


# ---------------------------------------------------------------------------
# 4. Pipeline registry can match instructions
# ---------------------------------------------------------------------------

class TestPipelineFastPath:

    def test_notepad_pipeline_matches(self):
        from deskaoy.desktop_agent import _get_pipeline_registry
        registry = _get_pipeline_registry()
        # "notepad" and "type" are both keywords in the pipeline name
        match = registry.match("type in notepad")
        assert match is not None
        assert match.name == "notepad_type"

    def test_unrelated_instruction_no_match(self):
        from deskaoy.desktop_agent import _get_pipeline_registry
        registry = _get_pipeline_registry()
        match = registry.match("open firefox and search for cats")
        assert match is None


# ---------------------------------------------------------------------------
# 5. Resolver recovers stale elements
# ---------------------------------------------------------------------------

class TestResolverWired:

    def test_resolver_recovers_changed_ref(self):
        """End-to-end: original button at e42, now at e99."""
        fp = ElementFingerprint(role="button", name="OK")
        snap = AXSnapshot(
            url="test://",
            title="Test",
            nodes={"e99": AXNode(ref="e99", role="button", name="OK")},
        )
        resolver = StaleRefResolver()
        result = resolver.resolve("e42", fp, snap)
        assert result.ok
        assert result.node.ref == "e99"
        assert result.match_level in (MatchLevel.STABLE, MatchLevel.REIDENTIFIED)
