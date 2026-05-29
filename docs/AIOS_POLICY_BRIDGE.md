# AI-OS Policy Bridge

## Rule

**No GUI action should bypass AI-OS policy when running inside AI-OS.**

## Permissions

Desktop-Agent declares these permissions in its capability manifest:

| Permission | Actions that require it |
|---|---|
| `screen_capture` | screenshot, visual grounding |
| `accessibility_read` | snapshot, UIA tree walking |
| `keyboard_input` | fill, type_text, key_press |
| `mouse_input` | click, scroll, hover |
| `window_focus` | click, fill, hover (requires target window) |
| `clipboard_read` | clipboard operations |
| `clipboard_write` | clipboard operations |
| `browser_navigation` | navigate |
| `network_access` | navigate, stealth proxy |
| `stealth_browser` | anti-detection browser automation (separate) |

## Policy Effects

| Effect | Meaning | Desktop-Agent behavior |
|---|---|---|
| `allow` | Action permitted | Execute normally |
| `deny` | Action forbidden | Return failure with policy denial |
| `ask` | User confirmation required | Return pending (AI-OS handles UI) |
| `allow_dry_run_only` | Only simulate | Execute as dry_run |
| `allow_with_obligations` | Permitted with conditions | Execute + track obligations |
| `degraded` | Limited capability | Execute with reduced features |

## Stealth Separation

Stealth browser automation is **disabled by default** and requires:

1. Explicit policy allow via `stealth_browser` permission
2. User-facing disclosure
3. Higher risk classification
4. Receipt/evidence generation

See `agent_core.policy.PolicyBridge` for implementation.

## Integration

```python
from agent_core.policy import PolicyBridge

bridge = PolicyBridge(dev_mode=True)
decision = await bridge.preflight("click", {"target": "Submit button"})
if decision.effect == "allow":
    # proceed
elif decision.effect == "deny":
    # return denied result
```

When running inside AI-OS, provide `preflight_fn` that delegates to the AI-OS policy service.
