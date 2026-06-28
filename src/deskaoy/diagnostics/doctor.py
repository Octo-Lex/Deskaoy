"""Platform diagnostic checks — ``deskaoy doctor``.

All checks are side-effect-free:
  - no input injection
  - no screenshots
  - no permission prompts
  - no subprocess that changes state
  - no imports that crash on other platforms

The diagnostic reuses the same detection logic as the Linux adapter
(Batch 10) and macOS permission probes (Batch 11), but duplicated as
pure helpers to avoid import side effects from adapter instantiation.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Status(str, Enum):  # noqa: UP042
    """Check outcome status."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    """A single diagnostic check result."""

    name: str
    status: Status
    detail: str = ""

    @property
    def ok(self) -> bool:
        """True if this check passed."""
        return self.status == Status.PASS

    @property
    def is_hard_failure(self) -> bool:
        """True if this check is a hard failure (affects exit code)."""
        return self.status == Status.FAIL

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


# ---------------------------------------------------------------------------
# Pure platform-detection helpers (no adapter instantiation)
# ---------------------------------------------------------------------------


def _detect_linux_input_backend() -> tuple[str, bool, str]:
    """Detect Linux input backend availability (pure, no AT-SPI import).

    Mirrors ``LinuxAdapter._input_backend_status()`` from Batch 10.
    """
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland":
        return ("xdotool", False, "Wayland session — xdotool cannot inject input "
                "on Wayland without compositor-specific portals")
    if not os.environ.get("DISPLAY"):
        return ("xdotool", False, "No DISPLAY — X11 session not detected")
    if not shutil.which("xdotool"):
        return ("xdotool", False, "xdotool not found — install: sudo apt install xdotool")
    return ("xdotool", True, "")


def _check_macos_accessibility() -> tuple[bool, str]:
    """Check macOS Accessibility permission (pure, no pyobjc import side effect).

    Returns ``(available, message)``. If pyobjc isn't installed, returns
    ``(False, "pyobjc not installed")`` without crashing.
    """
    try:
        from ApplicationServices import AXIsProcessTrusted
        trusted = AXIsProcessTrusted()
        if trusted:
            return (True, "granted")
        return (False, "not granted — System Settings > Privacy & Security > Accessibility")
    except ImportError:
        return (False, "pyobjc not installed — pip install pyobjc-framework-ApplicationServices")
    except Exception as exc:
        return (False, f"probe failed: {exc}")


def _check_macos_screen_recording() -> tuple[bool, str]:
    """Check macOS Screen Recording permission."""
    try:
        from Quartz import CGPreflightScreenCaptureAccess
        return (bool(CGPreflightScreenCaptureAccess()), "granted" if CGPreflightScreenCaptureAccess() else "not granted")
    except ImportError:
        return (False, "pyobjc not installed")
    except Exception as exc:
        return (False, f"probe failed: {exc}")


# ---------------------------------------------------------------------------
# Check groups
# ---------------------------------------------------------------------------


def _check_package() -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        import deskaoy
        results.append(CheckResult("Package import", Status.PASS, deskaoy.__file__ or "installed"))
        results.append(CheckResult("Version", Status.PASS, deskaoy.__version__))
    except Exception as exc:
        results.append(CheckResult("Package import", Status.FAIL, str(exc)))

    # Storage path
    try:
        from deskaoy.storage import StorageResolver
        sr = StorageResolver()
        results.append(CheckResult("Storage path", Status.PASS, str(sr.capability_root)))
    except Exception as exc:
        results.append(CheckResult("Storage path", Status.WARN, str(exc)))

    return results


def _check_platform() -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(CheckResult("OS", Status.PASS, f"{platform.system()} {platform.release()}"))
    if sys.version_info >= (3, 11):  # noqa: UP036
        results.append(CheckResult("Python", Status.PASS, sys.version.split()[0]))
    else:
        results.append(CheckResult(
            "Python",
            Status.FAIL,
            f"{sys.version.split()[0]} unsupported — requires Python >= 3.11",
        ))
    results.append(CheckResult("Architecture", Status.PASS, platform.machine()))
    return results


def _check_optional_deps() -> list[CheckResult]:
    results: list[CheckResult] = []
    import importlib

    # LLM
    llm_ok = False
    for pkg in ("openai", "anthropic"):
        try:
            importlib.import_module(pkg)
            llm_ok = True
            break
        except ImportError:
            pass
    results.append(CheckResult(
        "LLM client", Status.PASS if llm_ok else Status.WARN,
        "installed" if llm_ok else "pip install deskaoy[llm]",
    ))

    # Grounding
    try:
        importlib.import_module("ultralytics")
        results.append(CheckResult("Visual grounding", Status.PASS, "installed"))
    except ImportError:
        results.append(CheckResult("Visual grounding", Status.WARN, "pip install deskaoy[grounding]"))

    # Pillow
    try:
        importlib.import_module("PIL")
        results.append(CheckResult("Pillow (images)", Status.PASS, "installed"))
    except ImportError:
        results.append(CheckResult("Pillow (images)", Status.WARN, "pip install Pillow"))

    # Tracing
    try:
        importlib.import_module("opentelemetry")
        results.append(CheckResult("OpenTelemetry", Status.PASS, "installed"))
    except ImportError:
        results.append(CheckResult("OpenTelemetry", Status.WARN, "pip install deskaoy[tracing]"))

    return results


def _check_safety() -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        from deskaoy.safety.key_blocklist import BLOCKED_KEYS
        results.append(CheckResult("Key blocklist", Status.PASS, f"{len(BLOCKED_KEYS)} combos blocked"))
    except Exception as exc:
        results.append(CheckResult("Key blocklist", Status.FAIL, str(exc)))

    try:
        from deskaoy.safety.sensitive_apps import SENSITIVE_APPS
        results.append(CheckResult("Sensitive apps", Status.PASS, f"{len(SENSITIVE_APPS)} apps monitored"))
    except Exception as exc:
        results.append(CheckResult("Sensitive apps", Status.FAIL, str(exc)))

    return results


def _check_adapter_readiness() -> list[CheckResult]:
    results: list[CheckResult] = []
    system = platform.system()

    if system == "Windows":
        # comtypes / pywin32 / pyautogui
        try:
            import comtypes  # noqa: F401
            results.append(CheckResult("Windows: comtypes (UIA)", Status.PASS, "available"))
        except ImportError:
            results.append(CheckResult("Windows: comtypes (UIA)", Status.WARN,
                                       "pip install comtypes"))
        try:
            import win32api  # noqa: F401
            results.append(CheckResult("Windows: pywin32", Status.PASS, "available"))
        except ImportError:
            results.append(CheckResult("Windows: pywin32", Status.WARN,
                                       "pip install pywin32"))
        try:
            import pyautogui  # noqa: F401
            results.append(CheckResult("Windows: pyautogui", Status.PASS, "available"))
        except ImportError:
            results.append(CheckResult("Windows: pyautogui", Status.WARN,
                                       "pip install pyautogui"))
        try:
            import mss  # noqa: F401
            results.append(CheckResult("Windows: mss (screenshots)", Status.PASS, "available"))
        except ImportError:
            results.append(CheckResult("Windows: mss (screenshots)", Status.WARN,
                                       "pip install mss"))

    elif system == "Darwin":
        # macOS experimental gate
        gate = os.environ.get("DESKTOP_AGENT_MACOS", "").lower() in ("1", "true", "yes")
        results.append(CheckResult(
            "macOS: experimental gate",
            Status.PASS if gate else Status.WARN,
            "opted in (DESKTOP_AGENT_MACOS=1)" if gate
            else "not opted in — set DESKTOP_AGENT_MACOS=1 to enable experimental adapter",
        ))

        # pyobjc
        try:
            import ApplicationServices  # noqa: F401
            import Quartz  # noqa: F401
            results.append(CheckResult("macOS: pyobjc", Status.PASS, "installed"))
        except ImportError:
            results.append(CheckResult("macOS: pyobjc", Status.WARN,
                                       "pip install pyobjc-framework-ApplicationServices pyobjc-framework-Quartz"))

        # Permission probes (only if pyobjc available)
        if gate:
            acc_ok, acc_msg = _check_macos_accessibility()
            results.append(CheckResult(
                "macOS: Accessibility permission",
                Status.PASS if acc_ok else Status.WARN,
                acc_msg,
            ))
            sr_ok, sr_msg = _check_macos_screen_recording()
            results.append(CheckResult(
                "macOS: Screen Recording permission",
                Status.PASS if sr_ok else Status.WARN,
                sr_msg,
            ))

        # Validation script
        from pathlib import Path
        script = Path(__file__).parent.parent.parent.parent / "scripts" / "validate_macos_adapter.py"
        results.append(CheckResult(
            "macOS: validation script",
            Status.PASS if script.exists() else Status.WARN,
            str(script) if script.exists() else "not found",
        ))

    else:
        # Linux
        session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
        display = os.environ.get("DISPLAY", "")
        results.append(CheckResult(
            "Linux: session type", Status.PASS,
            session_type or "not set",
        ))
        results.append(CheckResult(
            "Linux: DISPLAY", Status.PASS if display else Status.WARN,
            display or "not set",
        ))

        backend_name, available, reason = _detect_linux_input_backend()
        if available:
            results.append(CheckResult(
                f"Linux: input backend ({backend_name})", Status.PASS, "available"))
        elif session_type == "wayland":
            results.append(CheckResult(
                f"Linux: input backend ({backend_name})", Status.WARN,
                f"unsupported on Wayland — {reason}"))
        else:
            results.append(CheckResult(
                f"Linux: input backend ({backend_name})", Status.WARN, reason))

        # AT-SPI2 for accessibility tree
        try:
            import pyatspi  # noqa: F401
            results.append(CheckResult("Linux: AT-SPI2 (accessibility tree)", Status.PASS, "available"))
        except ImportError:
            results.append(CheckResult(
                "Linux: AT-SPI2 (accessibility tree)", Status.WARN,
                "install: sudo apt install python3-atspi"))

    return results


def _check_known_limitations() -> list[CheckResult]:
    """Report known limitations as informational WARN items."""
    results: list[CheckResult] = []
    system = platform.system()

    if system == "Darwin":
        results.append(CheckResult(
            "macOS adapter is experimental",
            Status.WARN,
            "Gate removal pending real-device validation. "
            "Run scripts/validate_macos_adapter.py to validate.",
        ))

    if system == "Linux" and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        results.append(CheckResult(
            "Wayland input injection unsupported",
            Status.WARN,
            "Wayland sessions cannot use xdotool. "
            "AT-SPI2/portal backend is future work.",
        ))

    results.append(CheckResult(
        "Remaining lint/type debt",
        Status.SKIP,
        "See RELEASE_READINESS.md for ruff/mypy baseline status.",
    ))

    return results


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_doctor() -> dict[str, Any]:
    """Run all diagnostic checks and return structured results.

    Returns a dict with:
      - ``status``: overall status string
      - ``checks``: list of CheckResult dicts
      - ``summary``: counts by status
    """
    all_checks: list[CheckResult] = []

    all_checks.extend(_check_package())
    all_checks.extend(_check_platform())
    all_checks.extend(_check_adapter_readiness())
    all_checks.extend(_check_optional_deps())
    all_checks.extend(_check_safety())
    all_checks.extend(_check_known_limitations())

    # Compute overall status
    has_fail = any(c.is_hard_failure for c in all_checks)
    overall = "FAIL" if has_fail else "OK"

    # Summary counts
    summary = {
        "total": len(all_checks),
        "pass": sum(1 for c in all_checks if c.status == Status.PASS),
        "warn": sum(1 for c in all_checks if c.status == Status.WARN),
        "fail": sum(1 for c in all_checks if c.status == Status.FAIL),
        "skip": sum(1 for c in all_checks if c.status == Status.SKIP),
    }

    return {
        "status": overall,
        "checks": [c.to_dict() for c in all_checks],
        "summary": summary,
    }
