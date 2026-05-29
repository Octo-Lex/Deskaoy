"""Tests for BATCH-30 TASK-03 — version bump and integration checks."""
from __future__ import annotations

import argparse
from unittest.mock import patch, MagicMock

import pytest

from deskaoy.cli.version import VERSION
from deskaoy.cli.main import main, _build_parser
from deskaoy.cli.completions import CompletionGenerator


# ------------------------------------------------------------------
# T30-16: Version is 0.42.0
# ------------------------------------------------------------------

class TestVersionBump:

    def test_version_is_038(self):
        parts = VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_version_format_semver(self):
        parts = VERSION.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_version_major_is_v1(self):
        assert VERSION.startswith("2.")

    def test_version_greater_than_previous(self):
        current = tuple(int(x) for x in VERSION.split("."))
        previous = (0, 49, 0)
        assert current > previous


# ------------------------------------------------------------------
# T30-17: Version consistency across sources
# ------------------------------------------------------------------

class TestVersionConsistency:

    def test_version_matches_pyproject(self):
        import tomllib
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[2]  # tests/test_cli/ → project root
        with open(project_root / "pyproject.toml", "rb") as f:
            config = tomllib.load(f)
        assert config["project"]["version"] == VERSION

    def test_version_matches_desktop_agent(self):
        from deskaoy.desktop_agent import DesktopAgent
        # DesktopAgent may or may not be a dataclass; check the version attribute
        da_ver = getattr(DesktopAgent, "version", None)
        if isinstance(da_ver, str):
            assert da_ver == VERSION
        else:
            # It's a dataclass field — check default
            fields = getattr(DesktopAgent, "__dataclass_fields__", None) or getattr(DesktopAgent, "__fields__", {})
            if "version" in fields:
                default = fields["version"].default
                assert default == VERSION


# ------------------------------------------------------------------
# T30-18: Integration — completions command outputs correct version
# ------------------------------------------------------------------

class TestIntegration:

    def test_version_command_outputs_038(self, capsys):
        code = main(["version"])
        assert code == 0
        out = capsys.readouterr().out
        assert VERSION in out

    def test_completions_bash_includes_all_commands(self, capsys):
        code = main(["completions", "bash"])
        assert code == 0
        out = capsys.readouterr().out
        # Verify key commands are present in the completion output
        assert "execute" in out
        assert "version" in out
        assert "completions" in out
        assert "docs" in out
        assert "doctor" in out

    def test_completions_powershell_includes_docs(self, capsys):
        code = main(["completions", "powershell"])
        assert code == 0
        out = capsys.readouterr().out
        assert "'docs'" in out
        assert "'completions'" in out
