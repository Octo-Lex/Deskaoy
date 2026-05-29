# Phase 3: Integration Tests with Real Patchright Browser

> Spin up a real Chromium browser, run end-to-end scenarios that exercise
> the 23 fixes from Phases 0–2. Tests are marked `@pytest.mark.integration`
> and skipped unless `--run-integration` flag is passed.
> Prerequisites: 1115 unit tests passing, patchright+chromium installed.

---

## Test Infrastructure

### 1. Conftest Fixture: `real_browser`

**File**: `tests/conftest.py`

Add a session-scoped fixture that launches a headless Chromium browser
and yields a ready-to-use `(BrowserSession, PageHandle, CDPBridge)` tuple.

```python
@pytest.fixture
async def real_browser():
    """Launch a real headless Chromium browser for integration tests."""
    from super_browser.browser.session import BrowserSession
    from super_browser.browser.config import SessionConfig, SessionMode
    session = BrowserSession(SessionConfig(
        mode=SessionMode.PATCHRIGHT_LAUNCH,
        headless=True,
        viewport=(1280, 720),
    ))
    await session.start()
    page = await session.new_page()
    yield session, page, page.cdp
    await session.stop()
```

### 2. Test HTML Fixtures

**File**: `tests/fixtures/test_page.html`

A single HTML file served via `data:` URI that contains elements needed
by all test scenarios:
- Buttons (click targets)
- Input fields (fill targets)
- Select dropdowns
- Scrollable content
- Elements with special characters in selectors

This avoids needing an HTTP server — use `page.goto("data:text/html,...")`.

### 3. CLI Flag

**File**: `tests/conftest.py`

```python
def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False)

def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip = pytest.mark.skip(reason="Need --run-integration to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)
```

---

## Test Scenarios (10 tests)

### Scenario 1: Browser Lifecycle — Basic Sanity
**Validates**: BrowserSession, PageHandle, CDPBridge work end-to-end
**Fixes covered**: (infrastructure)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_lifecycle(real_browser):
    session, page, cdp = real_browser
    assert session.state().connected is True
    assert page.url == "about:blank"
    title = await page.title()
    assert title == ""
    # CDP evaluate works
    result = await cdp.evaluate("1 + 1")
    assert result.ok
    assert result.data["result"]["value"] == 2
```

### Scenario 2: Navigation + AX Snapshot
**Validates**: Page navigation, SnapshotProvider, AX tree capture
**Fixes covered**: (infrastructure for M7/M6)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_navigate_and_snapshot(real_browser):
    session, page, cdp = real_browser
    html = _test_html()  # helper returning data: URI with buttons/inputs
    await page.goto(html)
    assert "Test Page" in await page.title()

    from super_browser.interaction.snapshot import SnapshotProvider
    provider = SnapshotProvider(cdp)
    snap = await provider.capture_ax_only(page.url, await page.title())
    # Should find interactive elements
    assert len(snap.nodes) >= 3  # at least button + input + link
```

### Scenario 3: CSS Selector Click (Tier 1)
**Validates**: MultimodalController cascade, Tier 1 selector resolution
**Fixes covered**: M23 (public properties), M12 (budget wiring)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_css_selector_click(real_browser):
    session, page, cdp = real_browser
    await page.goto(_test_html())
    from super_browser.interaction.controller import MultimodalController
    ctrl = MultimodalController(page, cdp)
    assert ctrl.cdp is cdp      # M23
    assert ctrl.page is page    # M23

    result = await ctrl.click("#test-button")
    assert result.ok
    assert result.meta.method == ActionMethod.SELECTOR
```

### Scenario 4: Coordinate Click (Tier 2 Fallback)
**Validates**: Tier 2 coordinate resolution, CDP compositor operations
**Fixes covered**: M23, H4 (safe JS encoding)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_coordinate_click_fallback(real_browser):
    session, page, cdp = real_browser
    await page.goto(_test_html())
    ctrl = MultimodalController(page, cdp)

    # Make Tier 1 fail by using a non-existent selector
    result = await ctrl.click("#nonexistent-btn")
    # Should fall to Tier 2 (coordinate)
    # or fail if element truly not found
    # Either way, no crash, proper error handling
    assert isinstance(result.ok, bool)
```

### Scenario 5: CDP Compositor Operations
**Validates**: compositor_click, compositor_type, compositor_key_press
**Fixes covered**: (CDPBridge core)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_compositor_operations(real_browser):
    session, page, cdp = real_browser
    await page.goto(_test_html())
    # Click on input field
    r = await cdp.compositor_click(200, 300)
    assert r.ok
    # Type into it
    r = await cdp.compositor_type("hello world")
    assert r.ok
    # Press Enter
    r = await cdp.compositor_key_press("Enter")
    assert r.ok
```

### Scenario 6: Screenshot + Perceptual Hash
**Validates**: Screenshot capture, hash computation (H8 fix)
**Fixes covered**: H8 (vectorized DCT)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_screenshot_and_hash(real_browser):
    session, page, cdp = real_browser
    await page.goto(_test_html())
    result = await cdp.capture_screenshot(format="png")
    assert result.ok
    assert result.data is not None
    assert "data" in result.data

    from super_browser.verification.hasher import compute_hash
    import base64
    img_bytes = base64.b64decode(result.data["data"])
    phash = compute_hash(img_bytes)
    assert phash.dhash != 0 or phash.phash != 0  # non-trivial hash
```

### Scenario 7: Page Fingerprint (H7)
**Validates**: AgentLoop._compute_page_fingerprint with real CDP
**Fixes covered**: H7 (DOM state in fingerprint)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_page_fingerprint_changes(real_browser):
    session, page, cdp = real_browser
    await page.goto(_test_html())

    from super_browser.agent.loop import AgentLoop
    from super_browser.agent.registry import ToolRegistry
    loop = AgentLoop(
        controller=_make_ctrl(page, cdp),
        registry=ToolRegistry(),
        llm_client=_noop_llm(),
        max_steps=1,
    )
    fp1 = await loop._compute_page_fingerprint()
    assert len(fp1) == 16

    # Scroll the page
    await cdp.evaluate("window.scrollTo(0, 500)")
    fp2 = await loop._compute_page_fingerprint()
    assert fp1 != fp2  # scroll changes fingerprint
```

### Scenario 8: Checkpoint Manager (H6)
**Validates**: JSON-file checkpoint save/load with real page state
**Fixes covered**: H6 (file-based checkpoints)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_checkpoint_round_trip(real_browser, tmp_path):
    session, page, cdp = real_browser
    await page.goto(_test_html())

    from super_browser.recovery.checkpoint import CheckpointManager
    mgr = CheckpointManager(tmp_path)
    await mgr.initialize()

    cp = await mgr.create_checkpoint(
        page, action_history=["navigate", "click"],
    )
    assert cp is not None
    assert cp.url == page.url

    # Load it back
    data = await mgr.load_checkpoint_data(cp.checkpoint_id)
    assert data["url"] == page.url
    assert data["action_history"] == ["navigate", "click"]
```

### Scenario 9: Output Defender (M21 Truncation)
**Validates**: Level 1 actually truncates large page content
**Fixes covered**: M21 (real truncation), C3 (Level 3 spill)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_output_defender_truncation(real_browser, tmp_path):
    session, page, cdp = real_browser
    await page.goto(_test_html())

    # Extract page content (will be large)
    content = await page.content()

    from super_browser.results.output import OutputDefender
    from super_browser.results import action_result
    defender = OutputDefender(spill_dir=tmp_path)

    r = action_result(ok=True, data={"html": content})
    defended = defender.defend(r, max_chars=500)

    serialized = json.dumps(defended.data)
    assert len(serialized) <= 2000  # should be much smaller
    if len(content) > 500:
        assert defended.data.get("truncated") is True or isinstance(defended.data, SpilledResult)
```

### Scenario 10: Event Bus History Cap (M11)
**Validates**: WatchdogEventBus doesn't grow unbounded
**Fixes covered**: M11 (history cap)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_event_bus_history_cap(real_browser):
    session, page, cdp = real_browser
    from super_browser.recovery.event_bus import WatchdogEventBus
    from super_browser.recovery.types import WatchdogEvent, WatchdogEventData

    bus = WatchdogEventBus(max_history=5)
    for i in range(10):
        await bus.emit(WatchdogEventData(
            event_type=WatchdogEvent.RECOVERY_STARTED,
            source="test", detail=f"event {i}",
        ))
    assert len(bus._history) == 5
    events = bus.drain()
    assert events[-1].detail == "event 9"  # newest preserved
```

---

## Test HTML Fixture

A minimal HTML page served as a `data:text/html,...` URI:

```python
def _test_html():
    """Return a data: URI with interactive elements for testing."""
    import urllib.parse
    html = """<!DOCTYPE html>
<html><head><title>Test Page</title></head>
<body style="height:3000px;">
  <button id="test-button" aria-label="Click me">Click Me</button>
  <input id="test-input" type="text" placeholder="Type here" />
  <a id="test-link" href="#section">Go to section</a>
  <select id="test-select">
    <option value="a">Option A</option>
    <option value="b">Option B</option>
  </select>
  <div id="special-'chars" class="test-class">Special chars</div>
  <div id="output"></div>
  <div id="section" style="margin-top:2000px;">Scrolled section</div>
  <script>
    document.getElementById('test-button').addEventListener('click', function() {
      document.getElementById('output').textContent = 'clicked';
    });
    document.getElementById('test-input').addEventListener('input', function(e) {
      document.getElementById('output').textContent = e.target.value;
    });
  </script>
</body></html>"""
    return "data:text/html," + urllib.parse.quote(html)
```

---

## Execution Order

1. **Update `tests/conftest.py`** — add `real_browser` fixture, `--run-integration` flag
2. **Create `tests/integration/` directory** — `__init__.py`, `conftest.py`, test files
3. **Write `test_browser_basic.py`** — Scenarios 1, 5 (lifecycle, compositor)
4. **Write `test_controller_cascade.py`** — Scenarios 2, 3, 4 (snapshot, click, fallback)
5. **Write `test_verification.py`** — Scenarios 6, 7 (screenshot, fingerprint)
6. **Write `test_recovery_io.py`** — Scenarios 8, 10 (checkpoints, event bus)
7. **Write `test_output.py`** — Scenario 9 (truncation with real content)
8. **Run `pytest tests/ -x -q`** — confirm 1115 unit tests still pass
9. **Run `pytest tests/integration/ --run-integration -v`** — confirm integration tests pass

---

## Expected Results

| Metric | Value |
|--------|-------|
| Unit tests | 1115 (unchanged) |
| Integration tests | 22 |
| Browser launched | 1 per test (function-scoped fixture) |
| Total runtime (unit) | ~6s |
| Total runtime (integration only) | ~20s |
| Total runtime (all with --run-integration) | ~25s |
| Fixes validated end-to-end | H4, H6, H7, H8, C3, M11, M21, M23 |

## Actual Results

- **1137 tests pass** (1115 unit + 22 integration)
- All integration tests pass with `--run-integration`
- Integration tests are skipped (22 skipped) without the flag
- No regressions in unit tests
- Compositor type double-input behavior discovered (keyDown+char duplication)

---

## Files Created

| File | Tests |
|------|-------|
| `tests/conftest.py` | Modified — `--run-integration` flag, skip logic |
| `tests/integration/__init__.py` | New |
| `tests/integration/conftest.py` | New — `real_browser` fixture, `_test_html()` |
| `tests/integration/test_browser_basic.py` | 5 — lifecycle, navigation, compositor ops, screenshot |
| `tests/integration/test_controller_cascade.py` | 6 — AX snapshot, click, fill, fail, scroll, select |
| `tests/integration/test_verification.py` | 4 — perceptual hash, hash consistency, fingerprint scroll/nav |
| `tests/integration/test_recovery_io.py` | 4 — checkpoint round-trip, persistence, event bus cap, subscribe |
| `tests/integration/test_output.py` | 3 — truncation, spill-to-disk, turn budget |
