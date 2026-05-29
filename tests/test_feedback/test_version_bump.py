"""Tests for version bump consistency — BATCH-31.

Validates version consistency across all three single-source files:
  1. src/deskaoy/cli/version.py
  2. src/deskaoy/desktop_agent.py
  3. pyproject.toml
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestVersionBump039:
    """Version must be consistent across all single-source files."""

    def test_cli_version_is_consistent(self) -> None:
        """cli/version.py VERSION constant is valid semver."""
        from deskaoy.cli.version import VERSION
        parts = VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_desktop_agent_version_matches_cli(self) -> None:
        """DesktopAgent.version matches cli/version.py."""
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent
        assert DesktopAgent.version == VERSION

    def test_pyproject_version_matches_cli(self) -> None:
        """pyproject.toml project.version matches cli/version.py."""
        from deskaoy.cli.version import VERSION
        pyproject_path = _PROJECT_ROOT / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["version"] == VERSION

    def test_all_three_versions_match(self) -> None:
        """All three version sources must be identical."""
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent

        da_ver = DesktopAgent.version
        pyproject_path = _PROJECT_ROOT / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        pyproject_ver = data["project"]["version"]

        assert VERSION == da_ver == pyproject_ver

    def test_version_is_valid_semver(self) -> None:
        """Version is a valid semver string."""
        from deskaoy.cli.version import VERSION
        parts = VERSION.split(".")
        assert len(parts) == 3
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        assert major >= 0
        assert minor >= 0
        assert patch >= 0
