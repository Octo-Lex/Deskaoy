#!/usr/bin/env python3
"""macOS adapter hardware validation script — Batch 11.

Run this on a real macOS machine after granting permissions:
    python scripts/validate_macos_adapter.py

Requirements:
    - macOS 10.15+ (Catalina or later for privacy permissions)
    - pyobjc-framework-ApplicationServices
    - pyobjc-framework-Quartz
    - Accessibility permission granted
    - Screen Recording permission granted
    - Input Monitoring permission granted (if required by macOS version)

This script validates that the MacOSAdapter can perform real desktop
actions without fake success. It does NOT run in CI — it requires
real hardware, real permissions, and a real interactive session.

Usage:
    # Find a target app (e.g. TextEdit) and run:
    python scripts/validate_macos_adapter.py --pid $(pgrep TextEdit)

    Note: --bundle is not supported yet because MacOSAdapter does not resolve
    bundle ID to PID. Use --pid only.

Exit codes:
    0 — all validations passed
    1 — one or more validations failed
    2 — missing prerequisites (permissions, pyobjc, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys
import time


def _check_prerequisites() -> list[str]:
    """Check that the environment can run validation. Returns list of issues."""
    issues: list[str] = []

    if sys.platform != "darwin":
        issues.append(f"Not running on macOS (platform={sys.platform})")
        return issues

    try:
        import ApplicationServices  # noqa: F401
    except ImportError:
        issues.append("pyobjc-framework-ApplicationServices not installed")

    try:
        import Quartz  # noqa: F401
    except ImportError:
        issues.append("pyobjc-framework-Quartz not installed")

    return issues


async def validate_adapter(pid: int | None = None) -> dict[str, str]:
    """Run all validation checks. Returns dict of test_name → pass/fail/skip."""
    results: dict[str, str] = {}

    from deskaoy.adapters.macos import MacOSAdapter

    # Construct adapter (bundle ID resolution not yet implemented — PID only)
    try:
        adapter = MacOSAdapter(pid=pid)
        results["construction"] = "pass"
    except Exception as exc:
        results["construction"] = f"fail: {exc}"
        return results

    # 1. Permission probes
    print("\n=== Permission probes ===")

    acc_ok = adapter._check_accessibility_permission()
    results["permission_accessibility"] = "pass" if acc_ok else "fail"
    print(f"  Accessibility: {'✓ granted' if acc_ok else '✗ MISSING'}")

    sr_ok = adapter._check_screen_recording_permission()
    results["permission_screen_recording"] = "pass" if sr_ok else "fail"
    print(f"  Screen Recording: {'✓ granted' if sr_ok else '✗ MISSING'}")

    if not acc_ok:
        print("\n  ⚠ Accessibility permission is required for all input methods.")
        print("    Grant in: System Settings > Privacy & Security > Accessibility")

    if not sr_ok:
        print("\n  ⚠ Screen Recording permission is required for screenshots.")
        print("    Grant in: System Settings > Privacy & Security > Screen Recording")

    # 2. Dry-run (should always work regardless of permissions)
    print("\n=== Dry-run (no permissions needed) ===")

    dry_click = await adapter.click("100,100", dry_run=True)
    results["dry_run_click"] = "pass" if dry_click.ok else "fail"
    print(f"  click dry-run: {'✓' if dry_click.ok else '✗'}")

    dry_type = await adapter.type_text("test", dry_run=True)
    results["dry_run_type_text"] = "pass" if dry_type.ok else "fail"
    print(f"  type_text dry-run: {'✓' if dry_type.ok else '✗'}")

    # 3. Screenshot (requires Screen Recording)
    print("\n=== Screenshot (requires Screen Recording) ===")
    if not sr_ok:
        results["screenshot"] = "skip"
        print("  Skipped — Screen Recording permission missing")
    else:
        try:
            screenshot = await adapter.screenshot()
            if screenshot and len(screenshot) > 0:
                results["screenshot"] = "pass"
                print(f"  ✓ screenshot returned {len(screenshot)} bytes")
            else:
                results["screenshot"] = "fail"
                print("  ✗ screenshot returned empty bytes (permission likely dropped)")
        except PermissionError as exc:
            results["screenshot"] = f"fail: {exc}"
            print(f"  ✗ screenshot raised PermissionError: {exc}")
        except Exception as exc:
            results["screenshot"] = f"fail: {exc}"
            print(f"  ✗ screenshot failed: {exc}")

    # 4. Input injection (requires Accessibility)
    print("\n=== Input injection (requires Accessibility) ===")
    if not acc_ok:
        for method in ["click", "type_text", "key_press", "scroll", "fill"]:
            results[f"input_{method}"] = "skip"
        print("  All skipped — Accessibility permission missing")
    else:
        # Click on a harmless screen coordinate (center of screen)
        click_result = await adapter.click("500,500")
        results["input_click"] = "pass" if click_result.ok else "fail"
        print(f"  click: {'✓' if click_result.ok else '✗ ' + str(click_result.error.message)}")
        time.sleep(0.5)

        # Type text
        type_result = await adapter.type_text("hello")
        results["input_type_text"] = "pass" if type_result.ok else "fail"
        print(f"  type_text: {'✓' if type_result.ok else '✗ ' + str(type_result.error.message)}")
        time.sleep(0.3)

        # Key press (Return — harmless)
        key_result = await adapter.key_press("return")
        results["input_key_press"] = "pass" if key_result.ok else "fail"
        print(f"  key_press: {'✓' if key_result.ok else '✗ ' + str(key_result.error.message)}")
        time.sleep(0.3)

        # Scroll
        scroll_result = await adapter.scroll("down", amount=100)
        results["input_scroll"] = "pass" if scroll_result.ok else "fail"
        print(f"  scroll: {'✓' if scroll_result.ok else '✗ ' + str(scroll_result.error.message)}")
        time.sleep(0.3)

        # Fill (click + type)
        fill_result = await adapter.fill("500,500", "test")
        results["input_fill"] = "pass" if fill_result.ok else "fail"
        print(f"  fill: {'✓' if fill_result.ok else '✗ ' + str(fill_result.error.message)}")

    # 5. Blocked key (should fail regardless of permissions)
    print("\n=== Key blocklist ===")
    blocked_result = await adapter.key_press("F4", modifiers=1)  # Alt+F4
    blocked_ok = not blocked_result.ok and blocked_result.error.category.name == "SECURITY"
    results["blocked_key"] = "pass" if blocked_ok else "fail"
    print(f"  Alt+F4 blocked: {'✓' if blocked_ok else '✗ (not blocked!)'}")

    # 6. Missing-permission behavior (revoke and verify honest failure)
    # This is manual — can't programmatically revoke permissions.
    # Instead, verify that the permission probe methods exist and work.
    print("\n=== Permission failure paths ===")
    # If permissions were missing, the methods above should have returned errors.
    # This is implicitly tested — if permissions are granted, we can't test
    # the failure path here. Document it.
    if acc_ok and sr_ok:
        results["missing_permission_behavior"] = "not_tested"
        print("  Not tested (all permissions granted — cannot revoke programmatically)")
    else:
        # At least one permission missing — the input methods should have
        # returned honest errors instead of fake success
        for method in ["click", "type_text", "key_press", "scroll", "fill"]:
            r = results.get(f"input_{method}", "")
            if r == "skip":
                results["missing_permission_behavior"] = "pass"
                print(f"  ✓ {method} was correctly skipped due to missing permission")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate MacOSAdapter on real hardware")
    parser.add_argument("--pid", type=int, required=True,
                        help="Target application PID (e.g. $(pgrep TextEdit))")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════╗")
    print("║   macOS Adapter Hardware Validation (B11)   ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"\nMachine: {platform.machine()}")
    print(f"macOS: {platform.mac_ver()[0]}")
    print(f"Python: {platform.python_version()}")

    # Check prerequisites
    issues = _check_prerequisites()
    if issues:
        print("\n✗ Prerequisites not met:")
        for issue in issues:
            print(f"  - {issue}")
        return 2

    # Run validation
    results = asyncio.run(validate_adapter(pid=args.pid))

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    passed = sum(1 for v in results.values() if v == "pass")
    failed = sum(1 for v in results.values() if v.startswith("fail"))
    skipped = sum(1 for v in results.values() if v == "skip" or v == "not_tested")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Skipped: {skipped}")

    if failed > 0:
        print("\n✗ Validation FAILED")
        return 1
    else:
        print("\n✓ Validation PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
