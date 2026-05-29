"""Tests for macOS health check — TASK-03 (BATCH-33).

Verifies that the macOS adapter health check returns:
  - N/A when not on macOS
  - True when on macOS with pyobjc
  - False when on macOS without pyobjc
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.safety.health import HealthCheck


class _StubAgent:
    """Minimal agent stub."""
    def __init__(self):
        self._surface = None
        self._llm = None
        self._policy_bridge = None
        self._storage_resolver = None
        self._recovery_bridge = None


class TestMacOSHealthCheck:
    """macOS adapter health check (BATCH-33)."""

    @pytest.mark.asyncio
    async def test_macos_check_na_on_windows(self):
        """On Windows, macos_adapter check returns N/A."""
        with patch.object(sys, 'platform', 'win32'):
            hc = HealthCheck(_StubAgent())
            result = await hc.check()
            assert result.checks["macos_adapter"] is None
            assert "not macOS" in result.details["macos_adapter"]

    @pytest.mark.asyncio
    async def test_macos_check_na_on_linux(self):
        """On Linux, macos_adapter check returns N/A."""
        with patch.object(sys, 'platform', 'linux'):
            hc = HealthCheck(_StubAgent())
            result = await hc.check()
            assert result.checks["macos_adapter"] is None

    @pytest.mark.asyncio
    async def test_macos_check_pass_with_pyobjc(self):
        """On macOS with pyobjc installed, check returns True."""
        macos_modules = {
            'ApplicationServices': MagicMock(),
            'Quartz': MagicMock(),
        }
        with patch.dict('sys.modules', macos_modules):
            with patch.object(sys, 'platform', 'darwin'):
                hc = HealthCheck(_StubAgent())
                result = await hc.check()
                assert result.checks["macos_adapter"] is True
                assert "available" in result.details["macos_adapter"]

    @pytest.mark.asyncio
    async def test_macos_check_fail_without_pyobjc(self):
        """On macOS without pyobjc, check returns False."""
        # Remove pyobjc modules so import fails
        with patch.dict('sys.modules', {}, clear=False):
            with patch.object(sys, 'platform', 'darwin'):
                # Ensure ApplicationServices and Quartz are not importable
                sys.modules.pop('ApplicationServices', None)
                sys.modules.pop('Quartz', None)
                hc = HealthCheck(_StubAgent())
                result = await hc.check()
                assert result.checks["macos_adapter"] is False
                assert "pyobjc" in result.details["macos_adapter"].lower()

    @pytest.mark.asyncio
    async def test_macos_check_does_not_break_overall_health(self):
        """macOS N/A check should not make overall health unhealthy."""
        with patch.object(sys, 'platform', 'win32'):
            hc = HealthCheck(_StubAgent())
            result = await hc.check()
            assert result.checks["macos_adapter"] is None
            assert result.healthy is True
