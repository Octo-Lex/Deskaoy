#!/usr/bin/env python3
"""Super Browser — End-to-end demo script.

Exercises the full stack with a real Chromium browser:
  1. Launch browser, navigate to a real website
  2. Observe the page (AX snapshot)
  3. Click an element via CSS selector (Tier 1)
  4. Extract page content
  5. Take a screenshot and compute perceptual hash
  6. Save a checkpoint and restore it
  7. Verify output defender truncation
  8. Shut down cleanly

Usage:
    python scripts/demo_e2e.py
"""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


async def main():
    from super_browser.agent.config import SuperBrowserConfig
    from super_browser.agent.facade import SuperBrowser
    from super_browser.browser.config import SessionConfig, SessionMode
    from super_browser.browser.session import BrowserSession
    from super_browser.interaction.controller import MultimodalController
    from super_browser.interaction.snapshot import SnapshotProvider
    from super_browser.recovery.checkpoint import CheckpointManager
    from super_browser.recovery.event_bus import WatchdogEventBus
    from super_browser.recovery.types import WatchdogEvent, WatchdogEventData
    from super_browser.results import action_result
    from super_browser.results.output import OutputDefender, OutputBudgetConfig
    from super_browser.verification.hasher import compute_hash

    print("=" * 60)
    print("Super Browser — End-to-End Demo")
    print("=" * 60)

    # ── 1. Launch browser ─────────────────────────────────────────────
    print("\n[1/8] Launching headless Chromium...")
    session = BrowserSession(SessionConfig(
        mode=SessionMode.PATCHRIGHT_LAUNCH,
        headless=True,
        viewport=(1280, 720),
    ))
    await session.start()
    page = await session.new_page()
    cdp = page.cdp
    print(f"  ✓ Browser started: v{session.state().browser_version}")
    print(f"  ✓ PID: {session.state().browser_pid}")

    # ── 2. Navigate to example.com ────────────────────────────────────
    print("\n[2/8] Navigating to https://example.com ...")
    await page.goto("https://example.com", wait_until="domcontentloaded")
    title = await page.title()
    url = page.url
    print(f"  ✓ Title: {title!r}")
    print(f"  ✓ URL: {url}")

    # ── 3. Observe page (AX snapshot) ─────────────────────────────────
    print("\n[3/8] Capturing accessibility snapshot...")
    ctrl = MultimodalController(page, cdp)
    snap = await ctrl.capture_ax_snapshot()
    interactive = sum(1 for n in snap.nodes.values() if n.is_interactive)
    print(f"  ✓ Found {len(snap.nodes)} interactive nodes ({interactive} interactive)")
    for ref, node in list(snap.nodes.items())[:5]:
        print(f"    [{node.ref}] {node.role}: {node.name!r}")
    if len(snap.nodes) > 5:
        print(f"    ... and {len(snap.nodes) - 5} more")

    # ── 4. Click the "More information..." link ───────────────────────
    print("\n[4/8] Clicking link (Tier 1 selector)...")
    # example.com has a <a href="https://www.iana.org/domains/example"> link
    result = await ctrl.click("a", description="More information link")
    print(f"  ✓ Click result: ok={result.ok}")
    if result.ok:
        await asyncio.sleep(1)  # wait for navigation
        new_url = page.url
        new_title = await page.title()
        print(f"  ✓ Navigated to: {new_url}")
        print(f"  ✓ New title: {new_title!r}")

        # Go back for remaining tests
        await page.raw_page.go_back()
        await asyncio.sleep(1)

    # ── 5. Screenshot + perceptual hash ───────────────────────────────
    print("\n[5/8] Taking screenshot and computing perceptual hash...")
    ss_result = await cdp.capture_screenshot(format="png")
    if ss_result.ok:
        img_bytes = base64.b64decode(ss_result.data["data"])
        phash = compute_hash(img_bytes)
        print(f"  ✓ Screenshot: {len(img_bytes):,} bytes")
        print(f"  ✓ SHA-256: {phash.source_sha256[:32]}...")
        print(f"  ✓ dHash:  {phash.dhash:016x}")
        print(f"  ✓ pHash:  {phash.phash:016x}")
    else:
        print(f"  ✗ Screenshot failed: {ss_result.error}")

    # ── 6. Checkpoint save/restore ────────────────────────────────────
    print("\n[6/8] Saving checkpoint...")
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    cp_mgr = CheckpointManager(Path(tmp_dir))
    await cp_mgr.initialize()
    cp = await cp_mgr.create_checkpoint(
        message="pre-demo checkpoint",
        url=page.url,
        title=await page.title(),
        scroll_y=await page.raw_page.evaluate("Math.round(window.scrollY)"),
        action_history=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "click", "target": "a"},
        ],
    )
    print(f"  ✓ Checkpoint saved: {cp.checkpoint_id}")
    data = cp_mgr.load_checkpoint_data(cp.checkpoint_id)
    print(f"  ✓ Checkpoint loaded: {data['url']} ({len(data['actions'])} actions)")

    # ── 7. Event bus stress test ──────────────────────────────────────
    print("\n[7/8] Testing event bus history cap...")
    bus = WatchdogEventBus(max_history=10)
    for i in range(25):
        await bus.emit(WatchdogEventData(
            event_type=WatchdogEvent.RECOVERY_STARTED,
            source="demo",
            detail=f"event {i}",
        ))
    print(f"  ✓ Emitted 25 events with max_history=10")
    print(f"  ✓ History size: {len(bus._history)} (capped at 10)")
    events = bus.drain()
    print(f"  ✓ Newest event: {events[-1].detail!r}")

    # ── 8. Output defender ────────────────────────────────────────────
    print("\n[8/8] Testing output defender...")
    content = await page.content()
    defender = OutputDefender(spill_dir=Path(tmp_dir))
    r = action_result(ok=True, data={"html": content})
    defended = defender.defend(r, max_chars=500)
    if isinstance(defended.data, dict) and defended.data.get("truncated"):
        print(f"  ✓ Content truncated from {len(content):,} chars to fit budget")
    else:
        print(f"  ✓ Content ({len(content):,} chars) within budget")

    # ── Cleanup ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("All steps completed. Shutting down...")
    await session.stop()
    print("Browser closed. Demo finished.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
