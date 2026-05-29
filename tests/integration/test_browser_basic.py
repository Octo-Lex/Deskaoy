"""Integration tests — browser lifecycle and CDP compositor operations."""

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_lifecycle(real_browser):
    """Session is connected, page is blank, CDP evaluate works."""
    session, page, cdp = real_browser

    assert session.state().connected is True
    assert page.url == "about:blank"
    title = await page.title()
    assert title == ""

    result = await cdp.evaluate("1 + 1")
    assert result.ok
    assert result.data["result"]["value"] == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_navigate_to_html(real_browser):
    """Navigate to data: URI and verify title/content."""
    from tests.integration.conftest import _test_html_uri

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    title = await page.title()
    assert title == "Test Page"

    content = await page.content()
    assert "test-button" in content
    assert "test-input" in content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compositor_click_and_type(real_browser):
    """CDP compositor operations: click input, type text, verify result."""
    from tests.integration.conftest import _test_html_uri

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    # Click the input field (roughly at center of viewport top area)
    # First get its bounding box
    box = await page.raw_page.evaluate(
        '(() => { var r = document.getElementById("test-input").getBoundingClientRect();'
        ' return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height}); })()'
    )
    import json
    b = json.loads(box)
    x, y = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2

    r = await cdp.compositor_click(x, y)
    assert r.ok

    r = await cdp.compositor_type("hello world")
    assert r.ok

    # Verify the input received the text exactly once (no double-input)
    value = await page.raw_page.evaluate(
        'document.getElementById("test-input").value'
    )
    assert value == "hello world"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compositor_key_press(real_browser):
    """CDP key press dispatches correctly."""
    from tests.integration.conftest import _test_html_uri

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    # Focus the input
    await page.raw_page.click("#test-input")

    r = await cdp.compositor_key_press("a", modifiers=0)
    assert r.ok

    value = await page.raw_page.evaluate(
        'document.getElementById("test-input").value'
    )
    assert value == "a"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_screenshot_capture(real_browser):
    """Screenshot via CDP returns valid image data with hash."""
    from tests.integration.conftest import _test_html_uri

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    result = await cdp.capture_screenshot(format="png")
    assert result.ok
    assert result.data is not None
    assert "data" in result.data
    assert result.screenshot_hash is not None
    assert len(result.screenshot_hash) == 64  # SHA-256 hex
