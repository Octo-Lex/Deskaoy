"""Doctor command validation tests — Batch 12.

Tests verify:
  1. Doctor command runs all subsystem checks
  2. Each check produces clear pass/fail message
  3. Exit code 0 on usable, 1 on hard failure
  4. Output is parseable and human-readable
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import sys

from deskaoy.cli.main import _build_parser, _cmd_doctor


def _run_doctor() -> tuple[int, str]:
    """Run doctor command and capture output + exit code."""
    parser = _build_parser()
    args = parser.parse_args(["doctor"])

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    try:
        exit_code = asyncio.run(_cmd_doctor(args))
    finally:
        sys.stdout = old_stdout

    return exit_code, captured.getvalue()


class TestDoctorCommand:
    """Doctor command validates all subsystems."""

    def test_doctor_returns_exit_code(self):
        """Doctor returns 0 or 1, never crashes."""
        exit_code, _ = _run_doctor()
        assert exit_code in (0, 1)

    def test_doctor_prints_header(self):
        """Doctor prints version and diagnostic header."""
        _, output = _run_doctor()
        assert "deskaoy" in output
        assert "Platform Diagnostic" in output

    def test_doctor_prints_platform_info(self):
        """Doctor shows platform and Python version."""
        _, output = _run_doctor()
        assert "Platform:" in output
        assert "Python:" in output

    def test_doctor_checks_package_import(self):
        """Doctor verifies deskaoy can be imported."""
        _, output = _run_doctor()
        assert "Package import" in output

    def test_doctor_checks_version(self):
        """Doctor reports the package version."""
        _, output = _run_doctor()
        assert "Version" in output


class TestDoctorSubsystems:
    """Doctor checks all required subsystems."""

    def test_subsystem_count(self):
        """Doctor checks at least 10 subsystems."""
        _, output = _run_doctor()
        checks = output.count("[OK]") + output.count("[WARN]") + output.count("[FAIL]")
        assert checks >= 10, f"Expected >= 10 checks, found {checks}"

    def test_doctor_checks_storage_path(self):
        """Doctor reports storage directory."""
        _, output = _run_doctor()
        assert "Storage" in output

    def test_doctor_checks_adapter_readiness(self):
        """Doctor checks for platform-specific adapter readiness."""
        _, output = _run_doctor()
        assert "Adapter Readiness" in output or "adapter" in output.lower()

    def test_doctor_checks_key_blocklist(self):
        """Doctor verifies safety key blocklist is loaded."""
        _, output = _run_doctor()
        assert "Key blocklist" in output

    def test_doctor_checks_sensitive_apps(self):
        """Doctor verifies sensitive apps list is loaded."""
        _, output = _run_doctor()
        assert "Sensitive apps" in output

    def test_doctor_reports_summary(self):
        """Doctor prints a summary with counts."""
        _, output = _run_doctor()
        assert "Summary" in output
        assert "passed" in output
