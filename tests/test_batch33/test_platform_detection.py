"""Tests for platform detection — TASK-02 (BATCH-33).

Tests Environment.is_macos, Environment.is_windows, and
Environment.create_adapter factory.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("GITHUB_ACTIONS") == "true" and sys.platform == "win32",
    reason="macOS adapter mock tests crash on GitHub Actions Windows runners "
           "(thread/signal incompatibility when sys.platform is patched to darwin)",
)

from deskaoy.adapters.environment import Environment, LocalDesktop


class TestPlatformDetection:
    """Environment.is_macos and is_windows detect the current OS."""

    def test_is_macos_returns_bool(self):
        env = LocalDesktop()
        assert isinstance(env.is_macos, bool)

    def test_is_windows_returns_bool(self):
        env = LocalDesktop()
        assert isinstance(env.is_windows, bool)

    def test_is_macos_false_on_windows(self):
        """On Windows CI, is_macos should be False."""
        env = LocalDesktop()
        if sys.platform == "win32":
            assert env.is_macos is False

    def test_is_windows_true_on_windows(self):
        """On Windows CI, is_windows should be True."""
        env = LocalDesktop()
        if sys.platform == "win32":
            assert env.is_windows is True

    def test_mutual_exclusion(self):
        """On any single platform, at most one of mac/win is True."""
        env = LocalDesktop()
        assert not (env.is_macos and env.is_windows)


class TestCreateAdapterFactory:
    """create_adapter() returns the right adapter for the platform."""

    def test_create_adapter_macos(self):
        """On macOS with pyobjc and opt-in, returns MacOSAdapter."""
        macos_modules = {
            'ApplicationServices': MagicMock(),
            'CoreGraphics': MagicMock(),
            'Quartz': MagicMock(),
        }
        with patch.dict('sys.modules', macos_modules), patch('sys.platform', 'darwin'):
            with patch.dict(os.environ, {"DESKTOP_AGENT_MACOS": "1"}):
                adapter = Environment.create_adapter(pid=100)
                assert adapter is not None
                assert hasattr(adapter, 'click')
                assert hasattr(adapter, 'screenshot')

    def test_create_adapter_macos_missing_pyobjc_raises_on_use(self):
        """MacOSAdapter can be created but methods fail without pyobjc."""
        with patch('sys.platform', 'darwin'):
            with patch.dict(os.environ, {"DESKTOP_AGENT_MACOS": "1"}):
                adapter = Environment.create_adapter(pid=100)
                with pytest.raises(ImportError, match="requires macOS|requires pyobjc"):
                    asyncio.run(adapter.screenshot())

    def test_create_adapter_unsupported_platform(self):
        """FreeBSD should raise ImportError."""
        with patch('sys.platform', 'freebsd'):
            with pytest.raises(ImportError, match="No surface adapter"):
                Environment.create_adapter()

    @pytest.mark.skipif(sys.platform != "win32", reason="Uses hwnd= which is Windows-only")
    def test_create_adapter_returns_surface_adapter(self):
        """Factory always returns a SurfaceAdapter subclass."""
        adapter = Environment.create_adapter(hwnd=1)
        from deskaoy.cascade.protocol import SurfaceAdapter
        assert isinstance(adapter, SurfaceAdapter)

    def test_create_adapter_passes_kwargs(self):
        """Factory passes kwargs to adapter constructor."""
        macos_modules = {
            'ApplicationServices': MagicMock(),
            'CoreGraphics': MagicMock(),
            'Quartz': MagicMock(),
        }
        with patch.dict('sys.modules', macos_modules), patch('sys.platform', 'darwin'):
            with patch.dict(os.environ, {"DESKTOP_AGENT_MACOS": "1"}):
                adapter = Environment.create_adapter(pid=42, bundle_id="com.test")
                assert adapter._pid == 42
                assert adapter._bundle_id == "com.test"


class TestLazyImport:
    """MacOSAdapter module can be imported on any platform (HB-03)."""

    def test_import_does_not_crash_on_windows(self):
        """Importing the module on Windows must not raise."""
        from deskaoy.adapters.macos import MacOSAdapter
        assert MacOSAdapter is not None

    def test_ensure_imports_rejects_windows(self):
        """Calling _ensure_imports on Windows raises ImportError."""
        from deskaoy.adapters.macos import MacOSAdapter
        adapter = MacOSAdapter(pid=1)
        with pytest.raises(ImportError, match="requires macOS"):
            adapter._ensure_imports()

    def test_ensure_imports_caches(self):
        """_ensure_imports caches the _imported flag."""
        macos_modules = {
            'ApplicationServices': MagicMock(),
            'CoreGraphics': MagicMock(),
            'Quartz': MagicMock(),
        }
        with patch.dict('sys.modules', macos_modules), patch('sys.platform', 'darwin'):
            from deskaoy.adapters.macos import MacOSAdapter
            adapter = MacOSAdapter(pid=1)
            adapter._ensure_imports()
            assert adapter._imported is True
            adapter._ensure_imports()
            assert adapter._imported is True
