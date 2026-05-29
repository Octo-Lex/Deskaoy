# AI-OS Storage Policy

## Rule

**No production durable state outside AIOS_HOME.**

## Production Mode

When `AIOS_HOME` is set and the agent is not in development mode:

```
AIOS_HOME/capabilities/aios.first_party.desktop_agent/
├── action-memory/     # Action memory JSON files
├── checkpoints/       # Recovery checkpoints
├── artifacts/         # Screenshots, snapshots, debug output
├── logs/              # Diagnostic logs
└── temp/              # Transient working files
```

## Development Mode

When `DESKTOP_AGENT_DEV=1` or `AIOS_HOME` is not set:

```
~/.desktop-agent-dev/
├── action-memory/
├── checkpoints/
├── artifacts/
├── logs/
└── temp/
```

This is explicitly a development fallback. No production state should be stored here.

## Implementation

See `agent_core.storage.StorageResolver` for path resolution.

```python
from agent_core.storage import StorageResolver

storage = StorageResolver()
mem_dir = storage.resolve_action_memory()   # → AIOS_HOME/.../action-memory/
ckpt_dir = storage.resolve_checkpoints()    # → AIOS_HOME/.../checkpoints/
```

## Migration

When transitioning from standalone to AI-OS-managed:

1. AIOS_HOME is set by the AI-OS runtime
2. StorageResolver detects AIOS_HOME and switches to production paths
3. Existing dev-mode data is NOT auto-migrated — clean start
4. Dev mode remains available for standalone development
