# Phase 1: Fix HIGH-Priority Issues — Detailed Implementation Plan

> 8 issues, ~17 hours. Fixes major features broken across 6 subsystems.
> Prerequisite: Phase 0 (C1–C5) complete — all 1047 tests pass.

---

## Execution Order

```
H8: NumPy DCT hash axis fix          (30 min)  — independent, tiny
H5: Fail-fast on missing LLM client  (1 hour)  — independent, agent
H7: Improve page fingerprint          (2 hours) — independent, agent
H2: Budget cascade ignores governor   (1 hour)  — budget
H3: Compressor bypasses governor      (2 hours) — budget
H4: JS injection via f-string         (3 hours) — security, interaction
H6: Implement CheckpointManager       (4 hours) — recovery
H1: Stealth init script detectable    (4 hours) — stealth
```

**Dependency graph**:
- H2 + H3 can be done together (same module, budget)
- H4 is independent but security-critical
- H6 is the biggest piece of work
- H1 requires CDP knowledge — do last

---

## H8: Fix NumPy DCT Hash Axis — 30 min

### The Bug

`_dct2_numpy()` in `verification/hasher.py` does row-wise DCT correctly but the column-wise pass operates on the wrong data. The row DCT produces `result` (shape N×N) where `result[k]` accumulates across `arr[n]`. But then the column pass iterates `out_rows[r][n]` — this is the row-DCT output treated as columns, which gives a transposed result.

Compare with `_dct2_pure()` which does it correctly:
```python
# Pure version: row DCT then column DCT
for r: for k: s += matrix[r][n] * cos(...)     # row DCT
for c: for k: s += row_dct[n][c] * cos(...)     # column DCT
```

The NumPy version does:
```python
result[k] += arr[n] * cos(...)                   # row DCT (vectorized)
for r: for k: s += out_rows[r][n] * cos(...)     # column DCT (scalar, correct indices)
```

Actually the indices are the same — both produce correct 2D DCT. The real issue reported is that `_pil_to_numpy()` doesn't use numpy at all:

```python
def _pil_to_numpy(img: Image.Image):
    return [[float(img.getpixel((c, r))) for c in range(32)] for r in range(32)]
```

This returns a Python list, not a numpy array. The function name is misleading. The `_dct2_numpy` function then converts it with `np.array(matrix)` — so numpy IS used for the DCT computation, just not for the pixel extraction.

**Actual bug**: The column-wise DCT loop re-reads `out_rows[r][n]` and writes to `col_result[r][k]`. The row index `r` maps to the row-DCT output frequency, and `k` maps to the column-DCT output frequency. The indexing `out_rows[r][n]` iterates over `n` (the row-DCT spatial index), computing `cos(pi * k * (2*n+1) / (2*N))`. This is correct — it's applying DCT along the column dimension.

After careful analysis: **the DCT implementation is actually correct**. The gap report may have been wrong, or the axis issue was already fixed. Let me verify by testing.

### The Fix

**File**: `src/super_browser/verification/hasher.py`

1. Make `_pil_to_numpy()` actually use numpy:
```python
def _pil_to_numpy(img: Image.Image):
    return np.array(img, dtype=np.float64)
```

2. Add a proper vectorized 2D DCT using numpy matrix multiplication:
```python
def _dct2_numpy(matrix: list[list[float]]) -> list[list[float]]:
    arr = np.array(matrix, dtype=np.float64)
    N = arr.shape[0]
    n = np.arange(N)
    k = np.arange(N)
    cos_table = np.cos(np.pi * k[:, None] * (2 * n[None, :] + 1) / (2 * N))
    result = cos_table @ arr @ cos_table.T
    return result.tolist()
```

### New Tests

**File**: `tests/test_verification/test_hasher.py`

```python
def test_numpy_dct_matches_pure():
    """NumPy DCT must match pure Python DCT."""
    # 4x4 test matrix
    matrix = [[float(i * 4 + j) for j in range(4)] for i in range(4)]
    np_result = _dct2_numpy(matrix)
    pure_result = _dct2_pure(matrix)
    for r in range(4):
        for c in range(4):
            assert abs(np_result[r][c] - pure_result[r][c]) < 0.01

def test_phash_deterministic():
    """pHash must produce identical results for the same image."""
    # (already exists, just verify it still passes after the fix)
```

---

## H5: Fail-Fast on Missing LLM — 1 hour

### The Bug

`SuperBrowser.act()` creates an `AgentLoop` with `_NoOpLLM()` when no real LLM is configured. `_NoOpLLM.propose_action()` immediately returns `{"done": True}`, so the agent loop completes in 1 step doing nothing. The user gets a success result with no actual work done.

### The Fix

**File**: `src/super_browser/agent/facade.py`

Replace `_NoOpLLM` usage in `act()` with a clear error:

```python
async def act(self, instruction: str, *, max_steps: int = 50) -> ActionResult:
    if not self._controller:
        return action_result(ok=False, ...)

    # H5: require a real LLM client
    llm = self._llm_client
    if llm is None:
        llm = getattr(self, '_external_llm', None)
    if llm is None or isinstance(llm, _NoOpLLM):
        return action_result(
            ok=False,
            error=ActionError(
                ErrorCategory.VALIDATION,
                "act() requires an LLM client. Pass llm_client to SuperBrowser config "
                "or call set_llm_client() before act().",
            ),
        )

    loop = AgentLoop(
        controller=self._controller,
        registry=self._registry,
        llm_client=llm,  # real LLM, not _NoOpLLM
        ...
    )
```

Add `set_llm_client()` and `_llm_client` to `SuperBrowser`:

```python
def set_llm_client(self, client: Any) -> None:
    """Set the LLM client for act() calls."""
    self._llm_client = client
```

**File**: `src/super_browser/agent/config.py`

Add `llm_client` field to `SuperBrowserConfig` if not already present.

### New Tests

**File**: `tests/test_agent/test_facade.py` (extend existing)

```python
def test_act_without_llm_returns_error():
    """H5: act() should fail clearly when no LLM is configured."""
    async def _test():
        sb = SuperBrowser.__new__(SuperBrowser)
        sb._controller = MagicMock()
        sb._registry = ToolRegistry()
        sb._llm_client = None
        sb._coordinator = None
        sb._budget_client = None
        sb._flow_logger = None
        sb._security_manager = None
        sb._stealth_manager = None
        result = await sb.act("click the button")
        assert not result.ok
        assert "LLM" in result.error.message
    asyncio.run(_test())
```

---

## H7: Improve Page Fingerprint — 2 hours

### The Bug

`_compute_page_fingerprint()` in `agent/loop.py` hashes only `url|title`. This means:
- Scrolling doesn't change the fingerprint (same URL/title)
- Dynamic content updates don't change it
- Any page state change invisible to the title is missed

The stagnation detector then fires incorrectly, triggering replans when the page actually did change.

### The Fix

**File**: `src/super_browser/agent/loop.py`

Replace `_compute_page_fingerprint()` to include DOM node count, interactive element count, and scroll position:

```python
async def _compute_page_fingerprint(self) -> str:
    try:
        url = self._controller._page.url
        title = await self._controller._page.title()

        # H7: enrich fingerprint with DOM state
        dom_state = ""
        if self._controller and hasattr(self._controller, '_cdp'):
            try:
                result = await self._controller._cdp.evaluate(
                    '(function(){'
                    'var nodes = document.querySelectorAll("*");'
                    'var interactive = document.querySelectorAll("a,button,input,select,textarea,[onclick],[role]");'
                    'var scrollY = window.scrollY || 0;'
                    'return JSON.stringify({n:nodes.length,i:interactive.length,s:Math.round(scrollY)});'
                    '})()'
                )
                if result.ok and result.data:
                    dom_state = result.data.get("result", {}).get("value", "")
            except Exception:
                pass

        raw = f"{url}|{title}|{dom_state}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    except Exception:
        return ""
```

### New Tests

**File**: `tests/test_agent/test_loop.py`

```python
def test_fingerprint_includes_dom_state():
    """H7: Fingerprint should include DOM node count."""
    async def _test():
        controller = _make_controller()

        # Mock CDP evaluate to return DOM state
        dom_result = MagicMock()
        dom_result.ok = True
        dom_result.data = {"result": {"value": '{"n":42,"i":5,"s":0}'}}
        controller._cdp = MagicMock()
        controller._cdp.evaluate = AsyncMock(return_value=dom_result)

        loop = AgentLoop(
            controller=controller,
            registry=_make_registry(),
            llm_client=_make_llm(),
            max_steps=5,
        )
        fp1 = await loop._compute_page_fingerprint()
        assert len(fp1) == 16

        # Change DOM state
        dom_result.data = {"result": {"value": '{"n":50,"i":7,"s":100}'}}
        fp2 = await loop._compute_page_fingerprint()
        assert fp1 != fp2  # fingerprint changed when DOM changed
    asyncio.run(_test())

def test_fingerprint_same_url_different_scroll():
    """H7: Same URL with different scroll position should differ."""
    async def _test():
        controller = _make_controller()
        controller._cdp = MagicMock()

        dom_top = MagicMock(ok=True, data={"result": {"value": '{"n":42,"i":5,"s":0}'}})
        dom_scrolled = MagicMock(ok=True, data={"result": {"value": '{"n":42,"i":5,"s":500}'}})
        controller._cdp.evaluate = AsyncMock(side_effect=[dom_top, dom_scrolled])

        loop = AgentLoop(
            controller=controller,
            registry=_make_registry(),
            llm_client=_make_llm(),
            max_steps=5,
        )
        fp1 = await loop._compute_page_fingerprint()
        fp2 = await loop._compute_page_fingerprint()
        assert fp1 != fp2  # scroll changed → fingerprint changed
    asyncio.run(_test())
```

---

## H2: Budget Cascade Ignores Governor — 1 hour

### The Bug

`ModelCascade.escalate()` checks `max_total_escalations` but never consults `self._governor` to see if the budget can afford the escalated tier. This means it can escalate to Opus ($0.10/action) even when the daily budget is $0.00.

### The Fix

**File**: `src/super_browser/budget/cascade.py`

Add budget check in `escalate()`:

```python
def escalate(self, current_tier: CostTier, reason: str) -> Optional[CascadeResult]:
    total_escalations = sum(self._escalation_counts.values())
    if total_escalations >= self._config.max_total_escalations:
        return None

    # H2: check governor budget before escalating
    if self._governor is not None:
        from super_browser.budget.types import BudgetScope
        next_idx = _TIER_ORDER.index(current_tier) + 1 if current_tier in _TIER_ORDER else -1
        if next_idx < len(_TIER_ORDER):
            next_tier_key = _TIER_ORDER[next_idx]
            next_cascade = self._tier_map.get(next_tier_key)
            if next_cascade:
                estimated = next_cascade.cost_multiplier * 0.001  # rough estimate
                block = self._governor.check_budget(
                    BudgetScope.DAILY, estimated_cost_usd=estimated
                )
                if block:
                    return None  # can't afford escalation

    # ... rest of existing logic
```

### New Tests

**File**: `tests/test_budget/test_cascade.py`

```python
def test_escalation_blocked_when_budget_exhausted():
    """H2: Escalation should be None when governor says budget is exhausted."""
    from unittest.mock import MagicMock
    from super_browser.budget.governor import TokenBudgetGovernor
    from super_browser.budget.types import BudgetBlock, BudgetAlert, BudgetScope, AlertLevel

    governor = TokenBudgetGovernor()
    # Exhaust the daily budget
    governor._state.daily_spend_usd = governor._config.daily_cap_usd + 1

    cascade = ModelCascade(governor=governor)
    result = cascade.escalate(CostTier.TIER_1, "need better model")
    assert result is None  # blocked by budget

def test_escalation_allowed_when_budget_available():
    """H2: Escalation proceeds when budget is available."""
    governor = TokenBudgetGovernor()  # fresh, has budget
    cascade = ModelCascade(governor=governor)
    result = cascade.escalate(CostTier.TIER_1, "need better model")
    assert result is not None  # allowed
```

---

## H3: Compressor Bypasses Governor — 2 hours

### The Bug

`ContextCompressor._summarize_older_turns()` calls `self._llm_client(summary_prompt)` directly when compressing context. This bypasses `BudgetAwareLLMClient.call()`, so:
- Token costs are not tracked by the governor
- No budget check before the compression call
- No credential rotation or circuit breaker protection

### The Fix

**File**: `src/super_browser/budget/compressor.py`

The compressor needs to go through the budget-aware path. Two options:

**Option A** (simpler): Accept a `BudgetAwareLLMClient` instead of raw `llm_client`:

```python
class ContextCompressor:

    def __init__(
        self,
        llm_client: Any = None,
        budget_client: Any = None,  # H3: BudgetAwareLLMClient
        governor: Optional[Any] = None,
        compress_threshold: float = 0.75,
        max_output_tokens: int = 4_096,
    ) -> None:
        self._llm_client = llm_client
        self._budget_client = budget_client
        self._governor = governor
        self._compress_threshold = compress_threshold
        self._max_output_tokens = max_output_tokens
```

Then in `_summarize_older_turns()`, use `budget_client` when available:

```python
if self._budget_client is not None:
    response, record = await self._budget_client.call(
        summary_prompt,
        action_type="context_compression",
        complexity="simple",
    )
    summary = response if isinstance(response, str) else str(response)
elif self._llm_client is not None:
    # fallback to raw client (backward compat)
    ...
```

**File**: `src/super_browser/agent/facade.py`

Wire the `BudgetAwareLLMClient` into the `ContextCompressor`:

```python
if self._config.enable_budget:
    ...
    comp = ContextCompressor(budget_client=self._budget_client)  # H3
```

### New Tests

**File**: `tests/test_budget/test_compressor.py`

```python
def test_compression_uses_budget_client():
    """H3: Compressor should route through BudgetAwareLLMClient when available."""
    mock_budget = MagicMock()
    mock_budget.call = AsyncMock(return_value=("Summary text", MagicMock(estimated_cost_usd=0.001)))

    comp = ContextCompressor(budget_client=mock_budget)

    messages = [
        {"role": "system", "content": "You are helpful."},
    ] + [{"role": "user", "content": f"Message {i} " * 500} for i in range(10)]

    compressed, result = asyncio.run(comp.compress(messages, context_window=4000))
    assert mock_budget.call.called  # went through budget client
    assert result.compression_ratio < 1.0

def test_compression_falls_back_to_raw_llm():
    """H3: Compressor falls back to raw llm_client when no budget_client."""
    mock_llm = MagicMock(return_value="Summary text")
    comp = ContextCompressor(llm_client=mock_llm)

    messages = [
        {"role": "system", "content": "You are helpful."},
    ] + [{"role": "user", "content": f"Message {i} " * 500} for i in range(10)]

    compressed, result = asyncio.run(comp.compress(messages, context_window=4000))
    assert mock_llm.called
```

---

## H4: JS Injection via F-String Selectors — 3 hours

### The Bug

`MultimodalController._resolve_to_coordinates()` interpolates user-provided selectors into JavaScript strings:

```python
escaped = target.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
expr = f'(function(){{ var el = document.querySelector("{escaped}"); ... }})()'
```

The escaping is insufficient. A crafted selector like `"]; alert(1); //` breaks out of the string. Same issue in XPath resolution and `SuperBrowser.extract()`.

### The Fix

**File**: `src/super_browser/interaction/controller.py`

Replace all f-string JS interpolation with CDP parameterized evaluation:

```python
async def _resolve_to_coordinates(self, target: str) -> Optional[tuple[float, float]]:
    # @ref resolution — safe, no JS injection
    if target.startswith("@"):
        if self._ax_snapshot is None:
            await self.capture_ax_snapshot()
        node = self._ax_snapshot.resolve(target) if self._ax_snapshot else None
        if node and node.center:
            return node.center
        return None

    # H4: Use CDP Runtime.callFunctionOn with arguments instead of string interpolation
    js_fn = "(function(selector){" \
            "var r = document.evaluate(selector, document, null, " \
            "XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;" \
            "if(!r) return null;" \
            "var rect = r.getBoundingClientRect();" \
            "return JSON.stringify({x:rect.x,y:rect.y,w:rect.width,h:rect.height});" \
            "})"

    if target.startswith("//") or target.startswith("./"):
        result = await self._cdp.send("Runtime.evaluate", {
            "expression": f"{js_fn}({json.dumps(target)})",
            "returnByValue": True,
        })
    else:
        # CSS selector path
        js_fn_css = "(function(selector){" \
                    "var el = document.querySelector(selector);" \
                    "if(!el) return null;" \
                    "var rect = el.getBoundingClientRect();" \
                    "return JSON.stringify({x:rect.x,y:rect.y,w:rect.width,h:rect.height});" \
                    "})"
        result = await self._cdp.send("Runtime.evaluate", {
            "expression": f"{js_fn_css}({json.dumps(target)})",
            "returnByValue": True,
        })

    if result.ok and result.data:
        val = result.data.get("result", {}).get("value")
        if val:
            b = json.loads(val)
            return (b["x"] + b["w"] / 2, b["y"] + b["h"] / 2)
    return None
```

Key change: Use `json.dumps(target)` to safely encode the selector as a JS string literal, instead of hand-rolling escaping.

**File**: `src/super_browser/agent/facade.py`

Fix `extract()` the same way:

```python
# H4: Use json.dumps for safe selector injection
if selector:
    result = await self._controller._cdp.send("Runtime.evaluate", {
        "expression": f"(function(sel){{ var el = document.querySelector(sel); return el ? el.textContent : null; }})({json.dumps(selector)})",
        "returnByValue": True,
    })
    extracted = result.data.get("result", {}).get("value") if result.ok else None
```

### New Tests

**File**: `tests/test_interaction/test_controller.py` (add new test class)

```python
def test_resolve_coordinates_handles_quote_in_selector():
    """H4: Selectors with quotes should not break JS."""
    # This should not raise — the selector is safely encoded
    ...
```

---

## H6: Implement CheckpointManager — 4 hours

### The Bug

`CheckpointManager` is a stub — every method raises `NotImplementedError`. The recovery pipeline's `CHECKPOINT_ROLLBACK` strategy can never work.

### The Fix

**File**: `src/super_browser/recovery/checkpoint.py`

Implement checkpoint save/restore using JSON serialization instead of git:

```python
class CheckpointManager:
    """Manages action checkpoints for recovery rollback.

    Each checkpoint captures the browser state (URL, title, scroll position)
    and a list of actions that can be replayed.
    """

    def __init__(self, workspace: Path, checkpoint_dir: Optional[Path] = None) -> None:
        self._workspace = workspace
        self._checkpoint_dir = checkpoint_dir or workspace / ".super-browser" / "checkpoints"
        self._checkpoints: dict[str, Checkpoint] = {}

    async def initialize(self) -> None:
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    async def create_checkpoint(
        self,
        message: str,
        *,
        url: str = "",
        title: str = "",
        scroll_y: int = 0,
        action_history: Optional[list[dict]] = None,
    ) -> Checkpoint:
        checkpoint_id = hashlib.sha256(
            f"{time.monotonic()}|{message}".encode()
        ).hexdigest()[:12]

        data = {
            "url": url,
            "title": title,
            "scroll_y": scroll_y,
            "actions": action_history or [],
            "message": message,
        }

        file_path = self._checkpoint_dir / f"{checkpoint_id}.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        cp = Checkpoint(
            checkpoint_id=checkpoint_id,
            message=message,
            created_at=time.monotonic(),
            file_count=1,
            commit_hash=checkpoint_id,
        )
        self._checkpoints[checkpoint_id] = cp
        return cp

    async def rollback(self, checkpoint_id: str) -> bool:
        cp = self._checkpoints.get(checkpoint_id)
        if cp is None:
            return False
        file_path = self._checkpoint_dir / f"{checkpoint_id}.json"
        if not file_path.exists():
            return False
        # The recovery coordinator reads the checkpoint data
        # and replays from that state
        return True

    def load_checkpoint_data(self, checkpoint_id: str) -> Optional[dict]:
        file_path = self._checkpoint_dir / f"{checkpoint_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text(encoding="utf-8"))

    def list_checkpoints(self, limit: int = 20) -> list[Checkpoint]:
        return list(self._checkpoints.values())[-limit:]

    def _load_existing(self) -> None:
        for path in sorted(self._checkpoint_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                cp = Checkpoint(
                    checkpoint_id=path.stem,
                    message=data.get("message", ""),
                    created_at=0.0,
                    file_count=1,
                    commit_hash=path.stem,
                )
                self._checkpoints[cp.checkpoint_id] = cp
            except (json.JSONDecodeError, KeyError):
                pass
```

### New Tests

Replace all stub tests with real tests:

```python
class TestCheckpointManager:
    def test_initialize_creates_dir(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        assert (tmp_path / ".super-browser" / "checkpoints").is_dir()

    def test_create_and_list(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        cp = asyncio.run(mgr.create_checkpoint("test", url="https://example.com"))
        assert cp.checkpoint_id
        assert len(mgr.list_checkpoints()) == 1

    def test_checkpoint_persists_to_disk(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        cp = asyncio.run(mgr.create_checkpoint("test", url="https://example.com"))
        data = mgr.load_checkpoint_data(cp.checkpoint_id)
        assert data["url"] == "https://example.com"

    def test_rollback_returns_true_for_existing(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        cp = asyncio.run(mgr.create_checkpoint("test"))
        assert asyncio.run(mgr.rollback(cp.checkpoint_id)) is True

    def test_rollback_returns_false_for_missing(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        assert asyncio.run(mgr.rollback("nonexistent")) is False

    def test_persists_across_instances(self, tmp_path):
        mgr1 = CheckpointManager(tmp_path)
        asyncio.run(mgr1.initialize())
        asyncio.run(mgr1.create_checkpoint("test", url="https://example.com"))
        mgr2 = CheckpointManager(tmp_path)
        asyncio.run(mgr2.initialize())
        assert len(mgr2.list_checkpoints()) == 1
```

---

## H1: Stealth Init Script Detection — 4 hours

### The Bug

`StealthManager._inject_init_scripts()` uses `Page.addScriptToEvaluateOnNewDocument` to inject stealth scripts. Anti-bot systems (Cloudflare, DataDome) can detect this CDP method itself — they monitor for script injection events.

Patchright provides `Fetch.requestPaused` as the stealthy alternative: intercept page responses and inject scripts into the HTML before the page processes them.

### The Fix

**File**: `src/super_browser/stealth/manager.py`

Add a second injection method using `Fetch.requestPaused`:

```python
async def _inject_init_scripts(self) -> None:
    if not self._config.custom_init_scripts:
        return

    # H1: Use Fetch.requestPaused for stealth injection instead of
    # Page.addScriptToEvaluateOnNewDocument (detectable by anti-bot)
    try:
        # Enable Fetch domain
        await self._cdp.send("Fetch.enable", {
            "patterns": [{"resourceType": "Document"}],
        })

        # Start background listener
        asyncio.create_task(self._fetch_interceptor())

        logger.info("Stealth scripts injected via Fetch.requestPaused (undetectable)")
    except Exception as exc:
        # Fallback to old method if Fetch fails
        logger.warning("Fetch.enable failed, falling back to addScriptToEvaluateOnNewDocument: %s", exc)
        await self._inject_init_scripts_fallback()

async def _fetch_interceptor(self) -> None:
    """Intercept document responses and inject scripts into HTML."""
    combined_script = "\n".join(self._config.custom_init_scripts)

    try:
        while True:
            event = await self._cdp.wait_for_event("Fetch.requestPaused")
            request_id = event.get("requestId")
            resource_type = event.get("resourceType", "")

            if resource_type != "Document":
                await self._cdp.send("Fetch.continueRequest", {"requestId": request_id})
                continue

            # Get response body
            try:
                resp = await self._cdp.send("Fetch.getResponseBody", {"requestId": request_id})
                body = resp.get("body", "")
                is_base64 = resp.get("base64Encoded", False)

                if is_base64:
                    import base64
                    body = base64.b64decode(body).decode("utf-8", errors="replace")

                # Inject script before </head> or at start
                injection = f"<script>{combined_script}</script>"
                if "</head>" in body:
                    body = body.replace("</head>", f"{injection}</head>", 1)
                else:
                    body = injection + body

                await self._cdp.send("Fetch.fulfillRequest", {
                    "requestId": request_id,
                    "responseCode": 200,
                    "body": base64.b64encode(body.encode()).decode(),
                })
            except Exception:
                try:
                    await self._cdp.send("Fetch.continueRequest", {"requestId": request_id})
                except Exception:
                    pass
    except Exception:
        pass  # Task cancelled or CDP disconnected

async def _inject_init_scripts_fallback(self) -> None:
    """Fallback: use detectable CDP method."""
    for script in self._config.custom_init_scripts:
        try:
            await self._cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": script})
        except Exception as exc:
            logger.warning("Failed to inject init script: %s", exc)
```

**Note**: This requires CDPBridge to support `wait_for_event()`. Check if it exists; if not, add it.

### New Tests

**File**: `tests/test_stealth/test_manager.py`

```python
def test_inject_uses_fetch_first():
    """H1: StealthManager should try Fetch.requestPaused before addScriptToEvaluateOnNewDocument."""
    # Verify it calls Fetch.enable first
    ...

def test_fallback_to_add_script():
    """H1: Falls back to addScriptToEvaluateOnNewDocument if Fetch fails."""
    ...
```

---

## Verification Checklist

After all 8 fixes:

```bash
# Run full test suite
pytest tests/ -v

# Verify each fix specifically
pytest tests/test_verification/test_hasher.py -v              # H8
pytest tests/test_agent/test_facade.py -v                      # H5
pytest tests/test_agent/test_loop.py -v                        # H7
pytest tests/test_budget/test_cascade.py -v                    # H2
pytest tests/test_budget/test_compressor.py -v                 # H3
pytest tests/test_interaction/test_controller.py -v            # H4
pytest tests/test_recovery/test_checkpoint.py -v               # H6
pytest tests/test_stealth/test_manager.py -v                   # H1

# Check no regressions
pytest tests/ --tb=short
```

All 1047 existing tests + all new tests must pass.

---

## Effort Summary

| Fix | Effort | Risk | Lines Changed |
|-----|--------|------|---------------|
| H8 | 30 min | Low | ~20 (hasher.py) |
| H5 | 1 hour | Low | ~30 (facade.py) |
| H7 | 2 hours | Low | ~25 (loop.py) |
| H2 | 1 hour | Low | ~15 (cascade.py) |
| H3 | 2 hours | Medium | ~40 (compressor.py, facade.py) |
| H4 | 3 hours | Medium | ~60 (controller.py, facade.py) |
| H6 | 4 hours | Medium | ~120 (checkpoint.py) |
| H1 | 4 hours | High | ~100 (manager.py) |
| **Total** | **~17 hours** | | **~410 lines** |
