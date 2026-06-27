"""BATCH-36 TASK-02: Documentation final pass tests."""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.skipif(
    not (PROJECT_ROOT / "docs").exists(),
    reason="docs/ not present in test environment",
)


def _read(filename: str) -> str:
    return (PROJECT_ROOT / filename).read_text(encoding="utf-8")


class TestDocumentationV1:
    """TASK-02: Documentation final pass for v1.0.0."""

    def test_changelog_has_v1_release(self):
        """TEST-36-08: CHANGELOG has v1.0.0 release entry."""
        changelog = _read("CHANGELOG.md")
        assert "## [1.0.0]" in changelog, "CHANGELOG missing [1.0.0] entry"
        assert "Production" in changelog or "production" in changelog, (
            "CHANGELOG v1.0.0 missing 'Production' mention"
        )

    def test_api_reference_version(self):
        """TEST-36-09: API Reference version is v1.0.0."""
        ref = _read("docs/api/REFERENCE.md")
        assert "v1.0.0" in ref, "API Reference not updated to v1.0.0"
        # Should NOT contain old version references
        assert "v0.24.0" not in ref, "API Reference still references v0.24.0"

    def test_contributing_has_optional_deps(self):
        """TEST-36-10: CONTRIBUTING.md documents optional dependency groups."""
        contributing = _read("CONTRIBUTING.md")
        assert "[browser]" in contributing, "CONTRIBUTING missing [browser] dep group"
        assert "[windows]" in contributing, "CONTRIBUTING missing [windows] dep group"
        assert "[all]" in contributing, "CONTRIBUTING missing [all] dep group"
        assert "3,471" in contributing, "CONTRIBUTING test count not updated"
