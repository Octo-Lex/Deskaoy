"""Tests for version bump — TASK-04 (BATCH-33).

Verify version consistency after adding macOS adapter.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestVersionBump:
    """Verify version consistency (version-agnostic checks)."""

    def test_cli_version_format(self):
        from deskaoy.cli.version import VERSION
        parts = VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_pyproject_matches_cli(self):
        from deskaoy.cli.version import VERSION
        with open(_PROJECT_ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["version"] == VERSION

    def test_agent_matches_cli(self):
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent
        assert DesktopAgent.version == VERSION

    def test_all_three_match(self):
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent

        with open(_PROJECT_ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        assert VERSION == data["project"]["version"] == DesktopAgent.version

    def test_version_at_least_042(self):
        """Version must be at least 0.42.0 after BATCH-33."""
        from deskaoy.cli.version import VERSION
        from packaging.version import Version
        assert Version(VERSION) >= Version("1.1.0")
