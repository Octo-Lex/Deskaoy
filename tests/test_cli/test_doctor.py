"""Tests for the deskaoy doctor platform diagnostic — Batch 12.

Covers:
  - doctor exits 0 on a usable environment
  - doctor --json emits valid JSON with stable top-level keys
  - doctor does not call input injection methods
  - Linux X11 + xdotool reports PASS (mocked)
  - Linux Wayland reports WARN, not FAIL
  - Linux missing xdotool reports WARN, not FAIL
  - macOS gate disabled reports WARN/SKIP, not FAIL
  - missing optional cross-platform deps are WARN, not FAIL
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

from deskaoy.diagnostics.doctor import (
    _detect_linux_input_backend,
    run_doctor,
)

# ---------------------------------------------------------------------------
# run_doctor unit tests
# ---------------------------------------------------------------------------

class TestRunDoctor:

    def test_returns_dict_with_required_keys(self):
        result = run_doctor()
        assert "status" in result
        assert "checks" in result
        assert "summary" in result

    def test_status_is_ok_or_fail(self):
        result = run_doctor()
        assert result["status"] in ("OK", "FAIL")

    def test_checks_have_name_status_detail(self):
        result = run_doctor()
        for check in result["checks"]:
            assert "name" in check
            assert "status" in check
            assert "detail" in check
            assert check["status"] in ("PASS", "WARN", "FAIL", "SKIP")

    def test_summary_has_counts(self):
        result = run_doctor()
        summary = result["summary"]
        assert summary["total"] == len(result["checks"])
        assert summary["pass"] + summary["warn"] + summary["fail"] + summary["skip"] == summary["total"]

    def test_does_not_inject_input(self):
        """Doctor must not call any input injection methods."""
        import subprocess
        original_run = subprocess.run
        called = []

        def tracking_run(*args, **kwargs):
            if args and "xdotool" in str(args[0]):
                called.append(args[0])
            return original_run(*args, **kwargs)

        with patch("subprocess.run", side_effect=tracking_run):
            run_doctor()

        assert called == [], f"Doctor called subprocess: {called}"


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

class TestDoctorJSON:

    def test_json_output_is_valid(self, capsys):
        import contextlib

        from deskaoy.cli.main import main
        with contextlib.suppress(SystemExit):
            main(["doctor", "--json"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["status"] in ("OK", "FAIL")
        assert isinstance(data["checks"], list)
        assert isinstance(data["summary"], dict)

    def test_json_returns_nonzero_on_fail(self):
        """JSON mode must return exit code 1 when status is FAIL."""
        from deskaoy.cli.main import main
        fail_result = {
            "status": "FAIL",
            "checks": [],
            "summary": {"total": 0, "pass": 0, "warn": 0, "fail": 1, "skip": 0},
        }
        with patch("deskaoy.diagnostics.run_doctor", return_value=fail_result):
            code = main(["doctor", "--json"])
        assert code == 1


# ---------------------------------------------------------------------------
# CLI exit code
# ---------------------------------------------------------------------------

class TestDoctorExitCode:

    def test_doctor_exits_zero_on_usable(self, capsys):
        from deskaoy.cli.main import main
        try:
            code = main(["doctor"])
        except SystemExit as exc:
            code = exc.code
        # On a dev machine, environment should be usable (warnings only)
        assert code == 0


# ---------------------------------------------------------------------------
# Python version check
# ---------------------------------------------------------------------------

class TestPythonVersionCheck:

    def test_supported_version_reports_pass(self):
        """Python >= 3.11 should be PASS."""
        from deskaoy.diagnostics.doctor import Status, _check_platform
        with patch.object(sys, "version_info", (3, 12, 1)):
            results = _check_platform()
        py_check = [c for c in results if c.name == "Python"][0]
        assert py_check.status == Status.PASS

    def test_unsupported_version_reports_fail(self):
        """Python < 3.11 should be FAIL with clear message."""
        from deskaoy.diagnostics.doctor import Status, _check_platform
        with patch.object(sys, "version_info", (3, 10, 0)):
            results = _check_platform()
        py_check = [c for c in results if c.name == "Python"][0]
        assert py_check.status == Status.FAIL
        assert "3.11" in py_check.detail


# ---------------------------------------------------------------------------
# Linux backend detection
# ---------------------------------------------------------------------------

class TestLinuxBackendDetection:

    def test_x11_with_xdotool_reports_available(self):
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}), \
             patch("shutil.which", return_value="/usr/bin/xdotool"):
            name, available, reason = _detect_linux_input_backend()
        assert available is True

    def test_wayland_reports_unavailable(self):
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}):
            name, available, reason = _detect_linux_input_backend()
        assert available is False
        assert "wayland" in reason.lower()

    def test_no_display_reports_unavailable(self):
        env = {"XDG_SESSION_TYPE": "x11"}
        env.pop("DISPLAY", None)
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("DISPLAY", None)
            name, available, reason = _detect_linux_input_backend()
        assert available is False
        assert "display" in reason.lower()

    def test_missing_xdotool_reports_unavailable(self):
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}), \
             patch("shutil.which", return_value=None):
            name, available, reason = _detect_linux_input_backend()
        assert available is False
        assert "xdotool" in reason.lower()


# ---------------------------------------------------------------------------
# Cross-platform: missing optional deps are WARN not FAIL
# ---------------------------------------------------------------------------

class TestDoctorStatusSemantics:

    def test_missing_optional_deps_are_warn_not_fail(self):
        """Optional deps (LLM, grounding, etc.) should be WARN, not FAIL."""
        result = run_doctor()
        for check in result["checks"]:
            if ("LLM" in check["name"] or "grounding" in check["name"].lower()) and check["status"] != "PASS":
                assert check["status"] == "WARN", (
                    f"{check['name']} is {check['status']}, expected WARN"
                )

    def test_cross_platform_optional_deps_skip_not_fail(self):
        """Platform-specific deps on the wrong platform should be WARN/SKIP."""
        result = run_doctor()
        system = sys.platform
        for check in result["checks"]:
            # On non-Windows, Windows-specific checks should be WARN/SKIP
            if system != "win32" and check["name"].startswith("Windows:"):
                assert check["status"] in ("WARN", "SKIP"), (
                    f"{check['name']} is {check['status']} on non-Windows"
                )
            if system != "darwin" and check["name"].startswith("macOS:"):
                assert check["status"] in ("WARN", "SKIP"), (
                    f"{check['name']} is {check['status']} on non-macOS"
                )
