"""Adapter truthfulness tests — Batch 5.

Verifies that adapter methods report their capabilities honestly:

1. **Linux no-op methods** (``type_text``, ``key_press``, ``scroll``) must
   return ``ok=False`` with ``ErrorCategory.UNSUPPORTED`` when no injection
   backend is wired — not ``ok=True`` with fake success data.

2. **Factory macOS gate** — the adapter factory must not silently select the
   experimental macOS adapter; it requires explicit ``DESKTOP_AGENT_MACOS=1``
   opt-in.

3. **Dry-run still works** — the unsupported methods must still succeed in
   ``dry_run=True`` mode for previewing.

4. **ErrorCategory.UNSUPPORTED** exists in the error taxonomy.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.results.types import ErrorCategory

# ---------------------------------------------------------------------------
# 1. Linux adapter — unsupported input methods must fail honestly
# ---------------------------------------------------------------------------

class TestLinuxInputTruthfulness:
    """Linux type_text/key_press/scroll must not return fake success."""

    @pytest.fixture
    def adapter(self):
        """Create a LinuxAdapter, patching away the pyatspi import check."""
        with patch.dict("sys.modules", {"pyatspi": MagicMock()}):
            from deskaoy.adapters.linux import LinuxAdapter
            return LinuxAdapter()

    @pytest.mark.asyncio
    async def test_type_text_returns_unsupported(self, adapter):
        result = await adapter.type_text("hello")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_fill_returns_unsupported(self, adapter):
        result = await adapter.fill("field", "hello")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_fill_does_not_click_before_failing(self, adapter):
        """fill() must NOT perform a real click before returning unsupported.

        Previously fill() called click() then type_text(), so a real side
        effect occurred before the unsupported failure. Now fill() must fail
        before any side effect.
        """
        adapter.click = MagicMock()
        await adapter.fill("field", "hello")
        adapter.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_fill_dry_run_still_works(self, adapter):
        result = await adapter.fill("field", "hello", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_key_press_returns_unsupported(self, adapter):
        result = await adapter.key_press("Return")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_scroll_returns_unsupported(self, adapter):
        result = await adapter.scroll("down")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_type_text_dry_run_still_works(self, adapter):
        """dry_run must still succeed for previewing."""
        result = await adapter.type_text("hello", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_key_press_dry_run_still_works(self, adapter):
        result = await adapter.key_press("Return", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_scroll_dry_run_still_works(self, adapter):
        result = await adapter.scroll("down", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True


# ---------------------------------------------------------------------------
# 2. Factory — macOS requires explicit opt-in
# ---------------------------------------------------------------------------

class TestFactoryMacOSGate:

    def test_macos_factory_requires_opt_in(self):
        """Without DESKTOP_AGENT_MACOS=1, the factory must not silently
        select the experimental macOS adapter."""
        with patch.object(sys, "platform", "darwin"), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DESKTOP_AGENT_MACOS", None)
            with pytest.raises(ImportError, match="experimental"):
                from deskaoy.adapters.environment import Environment
                Environment.create_adapter()

    def test_macos_factory_allows_opt_in(self):
        """With DESKTOP_AGENT_MACOS=1, the factory should proceed past the
        experimental gate. It may still fail if pyobjc isn't installed, but
        the error should be about pyobjc, not about experimental status."""
        with patch.object(sys, "platform", "darwin"), patch.dict(os.environ, {"DESKTOP_AGENT_MACOS": "1"}):
            try:
                from deskaoy.adapters.environment import Environment
                Environment.create_adapter()
            except ImportError as exc:
                assert "experimental" not in str(exc).lower(), (
                    f"Expected pyobjc import error, got experimental gate: {exc}"
                )


# ---------------------------------------------------------------------------
# 3. ErrorCategory.UNSUPPORTED exists
# ---------------------------------------------------------------------------

class TestErrorTaxonomy:

    def test_unsupported_category_exists(self):
        assert ErrorCategory.UNSUPPORTED == "unsupported"
