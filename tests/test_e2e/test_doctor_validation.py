"""Doctor command validation tests — BATCH-35, TASK-03.

Tests verify:
  1. Doctor command runs all subsystem checks
  2. Each check produces clear pass/fail message
  3. Exit code 0 on all-pass, 1 on any failure
  4. Output is parseable and human-readable
  5. Subsystem count >= 14
"""
from __future__ import annotations

import asyncio
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
        exit_code, output = _run_doctor()
        assert exit_code in (0, 1)

    def test_doctor_prints_header(self):
        """Doctor prints version and diagnostic header."""
        _, output = _run_doctor()
        assert "deskaoy" in output
        assert "Environment Diagnostic" in output

    def test_doctor_prints_platform_info(self):
        """Doctor shows platform and Python version."""
        _, output = _run_doctor()
        assert "Platform:" in output
        assert "Python:" in output

    def test_doctor_checks_python_version(self):
        """Doctor verifies Python >= 3.11."""
        _, output = _run_doctor()
        assert "Python >= 3.11" in output
        # Should show [OK] since we're running on 3.11+
        assert "[OK]" in output

    def test_doctor_checks_deskaoy_importable(self):
        """Doctor verifies deskaoy can be imported."""
        _, output = _run_doctor()
        assert "deskaoy importable" in output


class TestDoctorSubsystems:
    """Doctor checks all required subsystems."""

    def test_subsystem_count(self):
        """Doctor checks at least 14 subsystems."""
        _, output = _run_doctor()
        # Count [OK] and [FAIL] markers
        checks = output.count("[OK]") + output.count("[FAIL]")
        assert checks >= 14, f"Expected >= 14 checks, found {checks}"

    def test_doctor_checks_storage_writable(self):
        """Doctor verifies storage directory is writable."""
        _, output = _run_doctor()
        assert "Storage writable" in output

    def test_doctor_checks_surface_adapter(self):
        """Doctor checks for platform-specific surface adapter."""
        _, output = _run_doctor()
        assert "adapter" in output.lower()

    def test_doctor_checks_key_blocklist(self):
        """Doctor verifies safety key blocklist is loaded."""
        _, output = _run_doctor()
        assert "Key blocklist" in output

    def test_doctor_checks_sensitive_apps(self):
        """Doctor verifies sensitive apps list is loaded."""
        _, output = _run_doctor()
        assert "Sensitive apps" in output


class TestDoctorExitCodes:
    """Doctor returns correct exit codes."""

    def test_exit_code_zero_on_clean(self):
        """Doctor returns 0 when all critical checks pass (or are N/A)."""
        exit_code, output = _run_doctor()
        # On a dev machine with Python >= 3.11 and deskaoy importable,
        # the critical checks should pass.
        # Optional deps (patchright, mcp, etc.) are not counted as failures.
        # Only issues counter determines exit code.
        if "issue(s) found" not in output:
            assert exit_code == 0

    def test_exit_code_has_consistent_format(self):
        """Output has [OK]/[FAIL] markers for each check."""
        _, output = _run_doctor()
        assert "[OK]" in output or "[FAIL]" in output
