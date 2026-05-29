"""Tests for Security Hardening (BATCH-12)."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock

from deskaoy.safety.key_blocklist import is_blocked_key
from deskaoy.safety.health import HealthCheck


class TestKeyBlocklistWired:
    """Verify key blocklist is wired into WindowsAdapter."""

    def test_blocked_key_returns_security_error(self):
        """Blocked key combo returns ActionResult with SECURITY error."""
        from deskaoy.adapters.windows import WindowsAdapter
        from deskaoy.results.types import ActionError, ErrorCategory

        adapter = WindowsAdapter(hwnd=1)
        adapter._win32gui = MagicMock()
        adapter._win32api = MagicMock()
        adapter._win32con = MagicMock()
        adapter._pyautogui = MagicMock()

        # Alt+F4 with modifier bitmask 1 (Alt)
        result = asyncio.run(adapter.key_press("f4", modifiers=1))
        assert result.ok is False
        assert result.error is not None
        assert result.error.category == ErrorCategory.SECURITY

    def test_normal_key_passes_through(self):
        """Normal key combo passes through without security error."""
        from deskaoy.adapters.windows import WindowsAdapter

        adapter = WindowsAdapter(hwnd=1)
        adapter._win32gui = MagicMock()
        adapter._win32gui.IsWindow.return_value = True
        adapter._win32api = MagicMock()
        adapter._win32con = MagicMock()
        adapter._pyautogui = MagicMock()

        result = asyncio.run(adapter.key_press("a"))
        assert result.ok is True
        adapter._pyautogui.press.assert_called_once_with("a")


class TestSecurityHealthChecks:
    """Verify security modules appear in health checks."""

    def test_key_blocklist_health_check(self):
        """Key blocklist shows up in health check."""
        agent = MagicMock()
        agent._surface = None
        agent._llm = None
        agent._policy_bridge = None
        agent._storage_resolver = None
        agent._recovery_bridge = None

        checker = HealthCheck(agent)
        status = asyncio.run(checker.check())
        assert "key_blocklist" in status.checks
        assert status.checks["key_blocklist"] is True

    def test_sensitive_apps_health_check(self):
        """Sensitive apps shows up in health check."""
        agent = MagicMock()
        agent._surface = None
        agent._llm = None
        agent._policy_bridge = None
        agent._storage_resolver = None
        agent._recovery_bridge = None

        checker = HealthCheck(agent)
        status = asyncio.run(checker.check())
        assert "sensitive_apps" in status.checks
        assert status.checks["sensitive_apps"] is True


class TestInputValidation:
    """Verify input validation for user-provided strings."""

    def test_key_press_empty_key_handled(self):
        """Empty key doesn't crash."""
        from deskaoy.adapters.windows import WindowsAdapter

        adapter = WindowsAdapter(hwnd=1)
        adapter._win32gui = MagicMock()
        adapter._win32gui.IsWindow.return_value = True
        adapter._win32api = MagicMock()
        adapter._win32con = MagicMock()
        adapter._pyautogui = MagicMock()

        result = asyncio.run(adapter.key_press(""))
        # Empty key is not blocked — just processed normally
        assert isinstance(result.ok, bool)

    def test_key_press_with_all_modifiers(self):
        """All modifiers at once still checked."""
        from deskaoy.adapters.windows import WindowsAdapter

        adapter = WindowsAdapter(hwnd=1)
        adapter._win32gui = MagicMock()
        adapter._win32api = MagicMock()
        adapter._win32con = MagicMock()
        adapter._pyautogui = MagicMock()

        # Ctrl+Alt+Del (modifiers 2+1=3, key "delete")
        result = asyncio.run(adapter.key_press("delete", modifiers=3))
        assert result.ok is False  # Should be blocked
