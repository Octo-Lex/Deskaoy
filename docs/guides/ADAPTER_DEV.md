# Adapter Development Guide — desktop-agent

Learn how to build a custom platform adapter for desktop-agent.

---

## Overview

An adapter implements the `SurfaceAdapter` protocol to provide platform-specific UI automation. The Windows adapter is the reference implementation.

## Quick Start

### 1. Subclass `SurfaceAdapter`

```python
from agent_core.cascade.protocol import SurfaceAdapter
from agent_core.results.types import ActionResult, action_result

class MyAdapter(SurfaceAdapter):
    """Custom adapter for my platform."""

    async def click(self, target: str, *, dry_run: bool = False, **kwargs) -> ActionResult:
        if dry_run:
            return action_result(ok=True, data={"action": "click", "target": target, "dry_run": True})
        # Your platform-specific click implementation
        x, y = self._resolve_target(target)
        self._platform_click(x, y)
        return action_result(ok=True, data={"x": x, "y": y})

    # ... implement other abstract methods
```

### 2. Required Methods (10)

| Method | Description | Must Return |
|--------|-------------|-------------|
| `click(target)` | Click on element | `ActionResult` |
| `fill(target, value)` | Click + type in field | `ActionResult` |
| `type_text(text)` | Type text with timing | `ActionResult` |
| `key_press(key, modifiers)` | Press key combo | `ActionResult` |
| `scroll(direction, amount)` | Scroll viewport | `ActionResult` |
| `screenshot()` | Capture screen | `bytes` (PNG) |
| `snapshot()` | Accessibility tree | `AXSnapshot` |
| `hover(target)` | Hover over element | `ActionResult` |
| `wait_for_selector(sel, timeout)` | Wait for element | `ActionResult` |
| `evaluate(expression)` | Eval expression | `Any` |

### 3. Optional Methods (7 pre-built)

These have default implementations but can be overridden:

| Method | Default | Override For |
|--------|---------|--------------|
| `read_clipboard()` | Raises NotImplementedError | Platform clipboard access |
| `write_clipboard(text)` | Raises NotImplementedError | Platform clipboard write |
| `open_app(name)` | Raises NotImplementedError | App launching |
| `invoke_element(ref)` | Delegates to `click` | Custom element invocation |
| `set_window_state(state)` | Raises NotImplementedError | Window management |
| `get_focused_element()` | Returns `""` | Focus tracking |
| `get_element_state(ref)` | Returns `{}` | Element inspection |

### 4. Key Press Safety

Your `key_press` implementation **must** check the key blocklist:

```python
async def key_press(self, key: str, modifiers: int = 0, **kwargs) -> ActionResult:
    from agent_core.safety.key_blocklist import is_blocked_key, block_reason

    # Build combo string from modifiers
    combo = key
    mod_names = []
    if modifiers & 1: mod_names.append("alt")
    if modifiers & 2: mod_names.append("ctrl")
    if modifiers & 4: mod_names.append("shift")
    if modifiers & 8: mod_names.append("win")
    if mod_names:
        combo = "+".join(mod_names) + "+" + key

    if is_blocked_key(combo):
        return action_result(
            ok=False,
            error=ActionError(ErrorCategory.SECURITY, f"Blocked: {combo}")
        )

    # ... proceed with key press
```

### 5. ActionResult Format

All action methods return `ActionResult`:

```python
# Success
return action_result(ok=True, data={"x": 100, "y": 200})

# Failure
return action_result(
    ok=False,
    error=ActionError(
        ErrorCategory.SELECTOR_NOT_FOUND,
        "Element not found",
        selector="btn",
        recoverable=True,
        retry_hint="Try scrolling down",
    ),
)
```

Error categories:
- `UNKNOWN` — Unexpected error
- `VALIDATION` — Invalid input
- `SECURITY` — Blocked by safety policy
- `SELECTOR_NOT_FOUND` — Element not found
- `TIMEOUT` — Operation timed out
- `RATE_LIMITED` — Rate limit exceeded

### 6. AXSnapshot Format

The `snapshot()` method returns an `AXSnapshot`:

```python
from agent_core.cascade.types import AXSnapshot, AXNode

return AXSnapshot(
    url="myplatform://WindowTitle",
    title="Window Title",
    nodes={
        "e1": AXNode(ref="e1", role="button", name="OK"),
        "e2": AXNode(ref="e2", role="textbox", name="Search", value="hello"),
    }
)
```

### 7. Testing Your Adapter

```python
import pytest
from agent_core.cascade.protocol import SurfaceAdapter

class TestMyAdapter:
    def test_implements_protocol(self):
        """Verify all abstract methods are implemented."""
        adapter = MyAdapter()
        assert isinstance(adapter, SurfaceAdapter)

    @pytest.mark.asyncio
    async def test_click_returns_result(self):
        adapter = MyAdapter()
        result = await adapter.click("100,200")
        assert isinstance(result, ActionResult)
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_blocked_key_rejected(self):
        adapter = MyAdapter()
        result = await adapter.key_press("f4", modifiers=1)  # Alt+F4
        assert result.ok is False
        assert result.error.category == ErrorCategory.SECURITY
```

## Checklist

- [ ] Subclass `SurfaceAdapter`
- [ ] Implement all 10 abstract methods
- [ ] Check key blocklist in `key_press()`
- [ ] Return `ActionResult` from all action methods
- [ ] Return `bytes` (PNG) from `screenshot()`
- [ ] Return `AXSnapshot` from `snapshot()`
- [ ] Support `dry_run=True` in action methods
- [ ] Test with `test_implements_protocol`
- [ ] Test blocked key rejection
- [ ] Add to CLI adapter selection

---

*Adapter Development Guide v0.24.0 — Generated 2026-05-03*
