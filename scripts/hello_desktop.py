#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hello Desktop -- standalone demo of real desktop automation.

Proves the entire stack works end-to-end:
  1. Launches Notepad
  2. Finds its window handle
  3. Types "Hello from desktop-agent!"
  4. Captures a screenshot
  5. Takes an accessibility tree snapshot
  6. Closes Notepad

Usage:
    python scripts/hello_desktop.py

Requires: pip install comtypes pyautogui mss pywin32
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time


async def main() -> int:
    print("=" * 60)
    print("  desktop-agent -- Hello Desktop Demo")
    print("=" * 60)
    print()

    # Step 1: Launch Notepad
    print("[1/6] Launching Notepad...")
    proc = subprocess.Popen(["notepad.exe"])
    time.sleep(2.0)

    # Step 2: Find window handle
    print("[2/6] Finding window handle...")
    try:
        import win32gui
        import win32con
    except ImportError:
        print("ERROR: win32gui not installed. pip install pywin32")
        proc.terminate()
        return 1

    hwnd = win32gui.FindWindow("Notepad", None)
    if not hwnd:
        hwnd = win32gui.FindWindow("NOTEPAD", None)
    if not hwnd:
        print("ERROR: Could not find Notepad window")
        proc.terminate()
        return 1
    print(f"       Found hwnd: {hwnd}")

    # Step 3: Create adapter and type text
    print("[3/6] Typing 'Hello from desktop-agent!'...")
    from deskaoy.adapters.windows import WindowsAdapter
    adapter = WindowsAdapter(hwnd=hwnd)
    adapter._ensure_imports()

    result = await adapter.type_text("Hello from desktop-agent!")
    if result.ok:
        print("       [OK] Text typed successfully")
    else:
        print(f"       [FAIL] Type failed: {result.error}")
    await asyncio.sleep(0.5)

    # Step 4: Screenshot
    print("[4/6] Capturing screenshot...")
    screenshot_data = await adapter.screenshot()
    if screenshot_data and screenshot_data[:4] == b"\x89PNG":
        size_kb = len(screenshot_data) / 1024
        print(f"       [OK] Screenshot captured ({size_kb:.1f} KB PNG)")
    else:
        print("       [FAIL] Screenshot failed")

    # Step 5: Accessibility snapshot
    print("[5/6] Taking accessibility tree snapshot...")
    snapshot = await adapter.snapshot()
    node_count = len(snapshot.nodes) if snapshot and snapshot.nodes else 0
    print(f"       [OK] Snapshot: {node_count} nodes, title='{snapshot.title}'")

    # Step 6: Close Notepad
    print("[6/6] Closing Notepad...")
    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.5)
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    print("       [OK] Notepad closed")

    print()
    print("=" * 60)
    print("  All steps completed successfully!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
