"""Version bump tests — BATCH-35, TASK-04.

Tests verify:
  1. Version has been bumped from 0.42.0 (pre-BATCH-35 baseline)
  2. Version is consistent across all single-source files
  3. Development status reflects a mature release
"""
from __future__ import annotations

import tomllib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestVersionBump:
    """Version is consistent and bumped from baseline."""

    def test_version_bumped_from_baseline(self):
        """Version must be >= 0.49.0 (BATCH-35 target)."""
        from deskaoy.cli.version import VERSION
        major, minor, patch = (int(x) for x in VERSION.split("."))
        # 0.49.0 or 1.0.0 both satisfy >= 0.49.0
        assert (major, minor, patch) >= (0, 49, 0), (
            f"Version {VERSION} is below BATCH-35 target 0.49.0"
        )

    def test_version_consistency_across_files(self):
        """All single-source files agree on the same version."""
        import deskaoy
        from deskaoy.cli.version import VERSION as cli_ver
        from deskaoy.desktop_agent import DesktopAgent

        with open(_PROJECT_ROOT / "pyproject.toml", "rb") as f:
            pyproject_ver = tomllib.load(f)["project"]["version"]

        da_ver = DesktopAgent.version
        init_ver = deskaoy.__version__

        assert cli_ver == pyproject_ver == da_ver == init_ver, (
            f"Version mismatch: cli={cli_ver}, pyproject={pyproject_ver}, "
            f"agent={da_ver}, init={init_ver}"
        )

    def test_development_status_is_mature(self):
        """Development status is at least Beta (not Alpha)."""
        with open(_PROJECT_ROOT / "pyproject.toml", "rb") as f:
            config = tomllib.load(f)
        classifiers = config["project"]["classifiers"]
        dev_statuses = [c for c in classifiers if "Development Status" in c]
        assert len(dev_statuses) >= 1, f"No Development Status classifier found: {classifiers}"
        # Must be Beta (4) or Production/Stable (5), not Alpha (3)
        assert "3 - Alpha" not in dev_statuses[0], (
            f"Development status should be >= Beta, got: {dev_statuses[0]}"
        )

    def test_cli_version_matches_desktop_agent(self):
        """CLI and DesktopAgent versions match."""
        from deskaoy.cli.version import VERSION
        from deskaoy.desktop_agent import DesktopAgent
        assert DesktopAgent.version == VERSION

    def test_init_version_matches_cli(self):
        """deskaoy.__version__ matches CLI version."""
        import deskaoy
        from deskaoy.cli.version import VERSION
        assert deskaoy.__version__ == VERSION
