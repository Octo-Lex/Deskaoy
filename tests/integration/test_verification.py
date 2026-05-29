"""Integration tests — perceptual hashing and page fingerprinting with real screenshots."""

import base64

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_screenshot_perceptual_hash(real_browser):
    """H8 fix: compute perceptual hash from a real screenshot."""
    from tests.integration.conftest import _test_html_uri
    from deskaoy.verification.hasher import compute_hash

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    result = await cdp.capture_screenshot(format="png")
    assert result.ok

    img_bytes = base64.b64decode(result.data["data"])
    phash = compute_hash(img_bytes)

    assert phash.dhash != 0  # non-trivial
    assert phash.phash != 0  # non-trivial
    assert len(phash.source_sha256) == 64


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hash_consistency(real_browser):
    """Two screenshots of the same page produce identical hashes."""
    from tests.integration.conftest import _test_html_uri
    from deskaoy.verification.hasher import compute_hash

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    r1 = await cdp.capture_screenshot(format="png")
    r2 = await cdp.capture_screenshot(format="png")

    img1 = base64.b64decode(r1.data["data"])
    img2 = base64.b64decode(r2.data["data"])

    h1 = compute_hash(img1)
    h2 = compute_hash(img2)

    # Same page = same dhash and phash (deterministic rendering)
    assert h1.dhash == h2.dhash
    assert h1.phash == h2.phash


@pytest.mark.integration
@pytest.mark.asyncio
async def test_page_fingerprint_changes_on_scroll(real_browser):
    """H7 fix: fingerprint includes scroll position and changes on scroll."""
    from tests.integration.conftest import _test_html_uri
    from deskaoy.agent.loop import AgentLoop
    from deskaoy.agent.registry import ToolRegistry
    from unittest.mock import MagicMock

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    # Build a minimal controller mock with real page/cdp
    controller = MagicMock()
    controller._page = page
    controller._cdp = cdp

    loop = AgentLoop(
        controller=controller,
        registry=ToolRegistry(),
        llm_client=MagicMock(),
        max_steps=1,
    )

    fp1 = await loop._compute_page_fingerprint()
    assert len(fp1) == 16  # SHA-256 truncated to 16 hex chars

    # Scroll the page
    await cdp.evaluate("window.scrollTo(0, 1000)")

    fp2 = await loop._compute_page_fingerprint()
    assert fp1 != fp2  # scroll changed the fingerprint


@pytest.mark.integration
@pytest.mark.asyncio
async def test_page_fingerprint_changes_on_navigation(real_browser):
    """Fingerprint changes when navigating to a different page."""
    from tests.integration.conftest import _test_html_uri
    from deskaoy.agent.loop import AgentLoop
    from deskaoy.agent.registry import ToolRegistry
    from unittest.mock import MagicMock

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    controller = MagicMock()
    controller._page = page
    controller._cdp = cdp

    loop = AgentLoop(
        controller=controller,
        registry=ToolRegistry(),
        llm_client=MagicMock(),
        max_steps=1,
    )

    fp1 = await loop._compute_page_fingerprint()

    # Navigate to a different data: URI
    await page.goto("data:text/html,<html><head><title>Other</title></head><body>Other</body></html>")

    fp2 = await loop._compute_page_fingerprint()
    assert fp1 != fp2
