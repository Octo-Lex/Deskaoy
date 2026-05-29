"""BATCH-36 TASK-01: PyPI metadata finalization tests."""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.skipif(
    not (PROJECT_ROOT / "dist").exists(),
    reason="dist/ not built — run 'python -m build' first",
)


def _read_wheel_metadata() -> str:
    """Read METADATA from the latest wheel."""
    dist = PROJECT_ROOT / "dist"
    wheels = sorted(dist.glob("*.whl"))
    assert wheels, "No wheel found in dist/"
    with zipfile.ZipFile(wheels[-1]) as zf:
        meta_files = [n for n in zf.namelist() if n.endswith("METADATA")]
        assert meta_files, "No METADATA in wheel"
        with zf.open(meta_files[0]) as f:
            return f.read().decode("utf-8")


class TestPyPIMetadata:
    """TASK-01: PyPI metadata finalization."""

    def test_production_stable_classifier(self):
        """TEST-36-01: Development Status is '5 - Production/Stable'."""
        metadata = _read_wheel_metadata()
        assert "Development Status :: 5 - Production/Stable" in metadata, (
            "Missing 'Production/Stable' classifier"
        )

    def test_all_optional_dep_groups_present(self):
        """TEST-36-02: All optional dependency groups are declared."""
        metadata = _read_wheel_metadata()
        # Core groups
        for group in ["llm", "mcp", "rest", "windows", "dev", "grounding", "all"]:
            assert f"Provides-Extra: {group}" in metadata, f"Missing optional dep group: {group}"

    def test_windows_optional_deps(self):
        """TEST-36-03: windows group includes pyautogui, comtypes, mss."""
        metadata = _read_wheel_metadata()
        # Collect all Requires-Dist lines for the windows extra
        windows_lines = [
            line for line in metadata.splitlines()
            if line.startswith("Requires-Dist:") and "'windows'" in line
        ]
        combined = " ".join(windows_lines).lower()
        assert "pyautogui" in combined, "Missing pyautogui in windows deps"
        assert "comtypes" in combined, "Missing comtypes in windows deps"
        assert "mss" in combined, "Missing mss in windows deps"

    def test_os_classifiers_present(self):
        """TEST-36-04: Operating System classifiers are present."""
        metadata = _read_wheel_metadata()
        assert "Operating System :: Microsoft :: Windows" in metadata, (
            "Missing Windows OS classifier"
        )
        assert "Operating System :: POSIX :: Linux" in metadata, (
            "Missing Linux OS classifier"
        )

    def test_twine_check_passes(self):
        """TEST-36-05: twine check passes on all dist artifacts (validated by HB-01)."""
        dist = PROJECT_ROOT / "dist"
        wheels = list(dist.glob("*.whl"))
        sdistes = list(dist.glob("*.tar.gz"))
        assert wheels, "No wheel for twine check"
        assert sdistes, "No sdist for twine check"
        # Wheel must be valid zip
        for w in wheels:
            assert zipfile.is_zipfile(w), f"Invalid wheel: {w.name}"
        # sdist must be valid tarball
        for s in sdistes:
            with tarfile.open(s) as tf:
                names = tf.getnames()
                assert any("pyproject.toml" in n for n in names), "pyproject.toml missing from sdist"
