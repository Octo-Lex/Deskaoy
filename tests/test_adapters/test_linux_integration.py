"""Tests for BATCH-34 version bump and integration (TASK-03).

Verifies:
- Version is consistent across all sources
- LinuxAdapter integrates with adapter factory
- LinuxAdapter is discoverable via SurfaceAdapter protocol
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deskaoy.cascade.protocol import SurfaceAdapter

# ---------------------------------------------------------------------------
# TASK-03 Tests: Version Bump + Integration (9 tests)
# ---------------------------------------------------------------------------


class TestVersionBump:
    """Version consistency across all sources."""

    def test_version_constant(self):
        from deskaoy.cli.version import VERSION
        # Just verify it's valid semver
        parts = VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_pyproject_version(self):
        """Read pyproject.toml directly and verify version matches CLI."""
        from deskaoy.cli.version import VERSION
        with open("pyproject.toml", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("version"):
                    assert VERSION in line
                    return
        pytest.fail("version not found in pyproject.toml")

    def test_desktop_agent_version(self):
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent
        agent = DesktopAgent.__new__(DesktopAgent)
        assert agent.version == VERSION

    def test_version_all_sources_match(self):
        """All three version sources are consistent."""
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent.__new__(DesktopAgent)
        config_ver = agent.version

        with open("pyproject.toml", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("version"):
                    pyproject_ver = line.split('"')[1]
                    break

        assert VERSION == pyproject_ver == config_ver


class TestLinuxAdapterIntegration:
    """LinuxAdapter integrates with the rest of the system."""

    def _linux_modules(self):
        gi = MagicMock()
        gi_repo = MagicMock()
        atspi = MagicMock()
        gi.repository = gi_repo
        gi_repo.Atspi = atspi
        return {
            "gi": gi,
            "gi.repository": gi_repo,
            "gi.repository.Atspi": atspi,
        }

    def test_linux_adapter_is_surface_adapter(self):
        """LinuxAdapter is a proper SurfaceAdapter subclass."""
        with patch.dict("sys.modules", self._linux_modules()):
            from deskaoy.adapters.linux import LinuxAdapter
            adapter = LinuxAdapter()
            assert isinstance(adapter, SurfaceAdapter)

    def test_factory_creates_linux_adapter(self):
        """create_adapter returns LinuxAdapter on Linux."""
        with patch("platform.system", return_value="Linux"):
            with patch.dict("sys.modules", self._linux_modules()):
                from deskaoy.adapters import create_adapter
                adapter = create_adapter()
                assert type(adapter).__name__ == "LinuxAdapter"

    def test_linux_adapter_has_all_required_methods(self):
        """LinuxAdapter implements all abstract SurfaceAdapter methods."""
        with patch.dict("sys.modules", self._linux_modules()):
            from deskaoy.adapters.linux import LinuxAdapter
            adapter = LinuxAdapter()

            # Check all abstract methods are implemented
            assert hasattr(adapter, "click")
            assert hasattr(adapter, "fill")
            assert hasattr(adapter, "screenshot")
            assert hasattr(adapter, "snapshot")
            assert hasattr(adapter, "evaluate")
            assert hasattr(adapter, "key_press")
            assert hasattr(adapter, "scroll")
            assert hasattr(adapter, "type_text")
            assert hasattr(adapter, "current_url")
            assert hasattr(adapter, "current_title")

    def test_linux_adapter_no_crash_on_import(self):
        """Importing LinuxAdapter does not crash on Windows (lazy import)."""
        # This test runs on Windows CI — must not crash
        from deskaoy.adapters.linux import LinuxAdapter
        adapter = LinuxAdapter()
        assert adapter._atspi is None  # Not imported until used
