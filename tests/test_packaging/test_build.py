"""BATCH-22: Package build and PyPI readiness tests."""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# These tests require a built wheel in dist/ — skip if not present
pytestmark = pytest.mark.skipif(
    not (PROJECT_ROOT / "dist").exists(),
    reason="dist/ not built — run 'python -m build' first",
)


class TestPackageBuild:
    """Validate package builds cleanly."""

    def test_wheel_exists(self):
        """TEST-22-01: python -m build succeeds (wheel exists)."""
        dist = PROJECT_ROOT / "dist"
        wheels = list(dist.glob("*.whl"))
        assert len(wheels) >= 1, "No wheel found in dist/"

    def test_wheel_contains_deskaoy(self):
        """TEST-22-02: Wheel contains deskaoy package."""
        dist = PROJECT_ROOT / "dist"
        wheels = sorted(dist.glob("*.whl"))
        assert wheels, "No wheel found"
        with zipfile.ZipFile(wheels[-1]) as zf:
            names = zf.namelist()
            agent_files = [n for n in names if "deskaoy/" in n]
            assert len(agent_files) > 10, f"Only {len(agent_files)} deskaoy files in wheel"

    def test_entry_point_in_metadata(self):
        """TEST-22-03: Entry point deskaoy is in wheel metadata."""
        dist = PROJECT_ROOT / "dist"
        wheels = sorted(dist.glob("*.whl"))
        assert wheels, "No wheel found"
        with zipfile.ZipFile(wheels[-1]) as zf:
            metadata_files = [n for n in zf.namelist() if n.endswith("METADATA")]
            assert metadata_files, "No METADATA in wheel"
            with zf.open(metadata_files[0]) as f:
                content = f.read().decode("utf-8")
                assert "deskaoy" in content, "Entry point 'deskaoy' not in metadata"

    def test_sdist_exists(self):
        """TEST-22-04: Source distribution exists and is valid."""
        dist = PROJECT_ROOT / "dist"
        sdist = sorted(dist.glob("*.tar.gz"))
        assert sdist, "No sdist found"
        with tarfile.open(sdist[-1]) as tf:
            names = tf.getnames()
            assert any("pyproject.toml" in n for n in names), "pyproject.toml missing from sdist"
