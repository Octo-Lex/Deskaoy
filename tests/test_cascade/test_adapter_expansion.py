"""Tests for SurfaceAdapter expansion (BATCH-05 TASK-03)."""
from __future__ import annotations

import pytest

from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.results.types import ActionResult

# ---------------------------------------------------------------------------
# Protocol Tests — new non-abstract methods exist and have defaults
# ---------------------------------------------------------------------------

class TestSurfaceAdapterExpansion:
    """TEST-05-03-01 through TEST-05-03-06."""

    def test_has_read_clipboard(self):
        """TEST-05-03-01: SurfaceAdapter has read_clipboard method."""
        assert hasattr(SurfaceAdapter, "read_clipboard")
        assert callable(SurfaceAdapter.read_clipboard)

    def test_has_write_clipboard(self):
        """TEST-05-03-02: SurfaceAdapter has write_clipboard method."""
        assert hasattr(SurfaceAdapter, "write_clipboard")
        assert callable(SurfaceAdapter.write_clipboard)

    def test_has_open_app(self):
        """TEST-05-03-03: SurfaceAdapter has open_app method."""
        assert hasattr(SurfaceAdapter, "open_app")
        assert callable(SurfaceAdapter.open_app)

    def test_has_invoke_element(self):
        """TEST-05-03-04: SurfaceAdapter has invoke_element method."""
        assert hasattr(SurfaceAdapter, "invoke_element")
        assert callable(SurfaceAdapter.invoke_element)

    def test_has_set_window_state(self):
        """TEST-05-03-05: SurfaceAdapter has set_window_state method."""
        assert hasattr(SurfaceAdapter, "set_window_state")
        assert callable(SurfaceAdapter.set_window_state)

    def test_default_implementations_raise(self):
        """TEST-05-03-06: Default implementations raise NotImplementedError."""
        import asyncio

        # Create a minimal concrete adapter for testing
        class TestAdapter(SurfaceAdapter):
            async def click(self, target, **kwargs): return ActionResult(ok=True)
            async def fill(self, target, value, **kwargs): return ActionResult(ok=True)
            async def type_text(self, text, **kwargs): return ActionResult(ok=True)
            async def key_press(self, key, **kwargs): return ActionResult(ok=True)
            async def scroll(self, direction, **kwargs): return ActionResult(ok=True)
            async def screenshot(self): return b""
            async def snapshot(self): return {}
            async def evaluate(self, expression): return None
            async def current_title(self): return "test"
            def current_url(self): return ""

        adapter = TestAdapter()

        # read_clipboard should raise
        with pytest.raises(NotImplementedError):
            asyncio.run(adapter.read_clipboard())

        # write_clipboard should raise
        with pytest.raises(NotImplementedError):
            asyncio.run(adapter.write_clipboard("test"))

        # open_app should raise
        with pytest.raises(NotImplementedError):
            asyncio.run(adapter.open_app("test"))

        # set_window_state should return not-supported ActionResult
        result = asyncio.run(adapter.set_window_state("maximize"))
        assert isinstance(result, ActionResult)
        assert result.ok is False

        # get_focused_element should return None
        result = asyncio.run(adapter.get_focused_element())
        assert result is None

        # get_element_state should return empty dict
        result = asyncio.run(adapter.get_element_state("test"))
        assert result == {}

    def test_invoke_element_click_delegates(self):
        """invoke_element with 'click' action delegates to click()."""
        import asyncio

        class ClickAdapter(SurfaceAdapter):
            async def click(self, target, **kwargs):
                return ActionResult(ok=True, data={"clicked": target})
            async def fill(self, target, value, **kwargs): return ActionResult(ok=True)
            async def type_text(self, text, **kwargs): return ActionResult(ok=True)
            async def key_press(self, key, **kwargs): return ActionResult(ok=True)
            async def scroll(self, direction, **kwargs): return ActionResult(ok=True)
            async def screenshot(self): return b""
            async def snapshot(self): return {}
            async def evaluate(self, expression): return None
            async def current_title(self): return "test"
            def current_url(self): return ""

        adapter = ClickAdapter()
        result = asyncio.run(adapter.invoke_element("btn", action="click"))
        assert result.ok is True
        assert result.data["clicked"] == "btn"

    def test_invoke_element_unsupported_action(self):
        """invoke_element with unsupported action returns not-ok."""
        import asyncio

        class MinimalAdapter(SurfaceAdapter):
            async def click(self, target, **kwargs): return ActionResult(ok=True)
            async def fill(self, target, value, **kwargs): return ActionResult(ok=True)
            async def type_text(self, text, **kwargs): return ActionResult(ok=True)
            async def key_press(self, key, **kwargs): return ActionResult(ok=True)
            async def scroll(self, direction, **kwargs): return ActionResult(ok=True)
            async def screenshot(self): return b""
            async def snapshot(self): return {}
            async def evaluate(self, expression): return None
            async def current_title(self): return "test"
            def current_url(self): return ""

        adapter = MinimalAdapter()
        result = asyncio.run(adapter.invoke_element("btn", action="toggle"))
        assert result.ok is False

    def test_new_methods_are_non_abstract(self):
        """New methods are NOT abstract — backward compatible."""
        for method_name in ["read_clipboard", "write_clipboard", "open_app",
                           "invoke_element", "set_window_state",
                           "get_focused_element", "get_element_state"]:
            method = getattr(SurfaceAdapter, method_name)
            # If it were abstract, it would have __isabstractmethod__ = True
            assert not getattr(method, "__isabstractmethod__", False), \
                f"{method_name} should not be abstract"
