# AI-OS Capability Manifest

## Identity

```yaml
capability_id: aios.first_party.desktop_agent
name: Desktop Agent
version: 0.5.0
publisher: aios
capability_type: agent
```

## Domains

- `desktop_automation`
- `browser_automation`

## Entrypoint

```
agent_core.desktop_agent:DesktopAgent
```

## Supported Actions

| Action | Class | Description |
|---|---|---|
| click | sensitive | Click on a desktop element |
| fill | sensitive | Fill a text input field |
| type_text | sensitive | Type text with human-like delays |
| key_press | recoverable | Press a key with optional modifiers |
| scroll | read_only | Scroll in a direction |
| screenshot | read_only | Capture a screenshot |
| snapshot | read_only | Capture the accessibility tree |
| navigate | read_only | Navigate to a URL |
| automate | sensitive | Multi-step automation |
| orchestrate | sensitive | Multi-app workflow |

## Runtime Requirements

- **Process**: Local process (not sandboxed)
- **Session**: Requires local user session
- **OS Permissions**: Accessibility, screen capture, input injection
- **Optional ML**: ultralytics, transformers, paddleocr, torch

## Storage

```
AIOS_HOME/capabilities/aios.first_party.desktop_agent/
├── action-memory/
├── checkpoints/
├── artifacts/
├── logs/
└── temp/
```

## Feature Support

- **dry_run**: Yes — all mutating actions support dry_run
- **estimate**: Yes — cost/latency/confidence prediction
- **undo**: Best-effort — inverse action replay
- **compensation**: Yes — manual recovery instructions
- **trace**: Bridge — emits to AI-OS TraceService
- **receipt**: Bridge — emits via trace bridge
- **policy_simulation**: Yes — dry_run serves as simulation

## Implementation

See `agent_core.manifest` for the validated manifest dictionary.
