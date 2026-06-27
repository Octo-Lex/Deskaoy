"""Tests for version bump and integration (BATCH-31, TASK-04)."""
from __future__ import annotations

import tomllib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestVersionBump:
    """Verify version consistency (version-agnostic checks)."""

    def test_cli_version(self):
        from deskaoy.cli.version import VERSION
        parts = VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_pyproject_version(self):
        from deskaoy.cli.version import VERSION
        with open(_PROJECT_ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["version"] == VERSION

    def test_agent_version(self):
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent
        assert DesktopAgent.version == VERSION

    def test_versions_match(self):
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent

        with open(_PROJECT_ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        cli_ver = VERSION
        pyproject_ver = data["project"]["version"]
        agent_ver = DesktopAgent.version

        assert cli_ver == pyproject_ver == agent_ver
