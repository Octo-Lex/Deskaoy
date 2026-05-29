"""Tests for Linux platform detection and adapter factory (BATCH-34 TASK-02).

Tests Environment.is_linux property and create_adapter factory with
mocked platform detection.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.adapters.environment import (
    Environment,
    EnvironmentInfo,
    EnvironmentState,
    LocalDesktop,
)


# ---------------------------------------------------------------------------
# TASK-02 Tests: Platform Detection (8 tests)
# ---------------------------------------------------------------------------


class TestEnvironmentIsLinux:
    """Environment.is_linux property tests."""

    def test_is_linux_true(self):
        with patch("deskaoy.adapters.environment.platform.system", return_value="Linux"):
            env = LocalDesktop()
            assert env.is_linux is True

    def test_is_linux_false_windows(self):
        with patch("deskaoy.adapters.environment.platform.system", return_value="Windows"):
            env = LocalDesktop()
            assert env.is_linux is False

    def test_is_linux_false_macos(self):
        with patch("deskaoy.adapters.environment.platform.system", return_value="Darwin"):
            env = LocalDesktop()
            assert env.is_linux is False


class TestEnvironmentIsWindows:
    """Environment.is_windows property tests."""

    def test_is_windows_true(self):
        with patch("deskaoy.adapters.environment.platform.system", return_value="Windows"):
            env = LocalDesktop()
            assert env.is_windows is True

    def test_is_windows_false_linux(self):
        with patch("deskaoy.adapters.environment.platform.system", return_value="Linux"):
            env = LocalDesktop()
            assert env.is_windows is False


class TestEnvironmentIsMacos:
    """Environment.is_macos property tests."""

    def test_is_macos_true(self):
        with patch("deskaoy.adapters.environment.platform.system", return_value="Darwin"):
            env = LocalDesktop()
            assert env.is_macos is True

    def test_is_macos_false(self):
        with patch("deskaoy.adapters.environment.platform.system", return_value="Linux"):
            env = LocalDesktop()
            assert env.is_macos is False


class TestCreateAdapterFactory:
    """create_adapter factory tests."""

    def test_factory_raises_on_linux_without_atspi(self):
        """Graceful error when AT-SPI2 is not available on Linux."""
        # Patch sys.platform to "linux" and make the LinuxAdapter import fail
        with patch("deskaoy.adapters.environment.sys.platform", "linux"):
            with patch.dict("sys.modules", {"deskaoy.adapters.linux": None}):
                with pytest.raises(ImportError, match="python3-atspi"):
                    Environment.create_adapter()
