# BATCH-28 BLUEPRINT — Clipboard, Set-Value & Perform-Action

**Batch:**                BATCH-28
**Version:**              v0.35.0 → v0.36.0
**Cycle Type:**           STANDARD
**AIV Framework:**        v5.2
**Date:**                 2026-05-10
**Lead:**                 Craft Agent (Lead Override per §5.3)
**Blueprint Version:**    1.0

---

## 1. Batch Identity

**Batch Name:**           Clipboard, Set-Value & Perform-Action
**Strategic Bet:**        Direct accessibility value setting + named AX actions + clipboard read/write — Peekaboo's `set-value`, `perform-action`, and `clipboard` commands adapted for Desktop-Agent's action-first architecture.
**Priority:**             MEDIUM

**Context:**              Peekaboo has dedicated CLI commands for `set-value` (direct accessibility value setting), `perform-action` (named AX actions), and `clipboard` (get/set/paste). Desktop-Agent has the underlying UIA patterns from BATCH-25 and WindowsAdapter clipboard via PowerShell, but no CLI commands or unified API surface for these. This batch wires them together and exposes them properly.

---

## 2. Scope

### In Scope
- **Clipboard commands**: `clipboard read`, `clipboard write <text>`, `clipboard paste`
- **Set-Value command**: `set-value <target> <value>` using ValuePattern first, fallback to click+type
- **Perform-Action command**: `perform-action <target> <action>` dispatching to all UIA patterns
- **DesktopAgent facade methods**: `set_value()`, `perform_action()`, `read_clipboard()`, `write_clipboard()`
- **MCP tool exposure**: clipboard, set_value, perform_action tools
- **REST endpoints**: POST /clipboard, POST /set-value, POST /perform-action

### Out of Scope
- macOS/Linux clipboard (requires platform adapters)
- Image/binary clipboard (text only for now)
- Custom AX action registration

---

## 3. Hard Boundaries

| ID  | Constraint |
|-----|-----------|
| HB-01 | Clipboard text-only — no binary/image support |
| HB-02 | All 3,158 baseline tests must pass |
| HB-03 | No new required dependencies |
| HB-04 | set-value/perform-action must use action-first (UIA patterns before pyautogui) |

---

## 4. Task Sequence

**Sequencing:** SEQUENTIAL (T01 → T02 → T03 → T04)

### TASK-01: Clipboard Enhancement & CLI

**Description:** Enhance clipboard with cross-platform protocol and expose via CLI.

**Methods (on SurfaceAdapter):**
- `read_clipboard()` — already exists, Windows uses PowerShell
- `write_clipboard(text)` — already exists, Windows uses PowerShell
- `paste()` — NEW: Ctrl+V via pyautogui/key_press

**CLI Commands:**
```
desktop-agent clipboard read [--json]
desktop-agent clipboard write <text>
desktop-agent clipboard paste
```

**Files:**
- MOD: `src/agent_core/cascade/protocol.py` — add `paste()` method
- MOD: `src/agent_core/adapters/windows.py` — implement `paste()`
- MOD: `src/agent_core/desktop_agent.py` — add clipboard convenience methods
- MOD: `src/agent_core/cli/main.py` — `clipboard` subcommand

**Expected Tests:** 10

---

### TASK-02: Set-Value Command

**Description:** Direct accessibility value setting via UIA ValuePattern.

**DesktopAgent Facade:**
```python
async def set_value(self, target: str, value: str) -> ActionResult:
    """Set a value on a target element using UIA ValuePattern first.
    
    Falls back to click+type when ValuePattern unavailable.
    """
```

**CLI Command:**
```
desktop-agent set-value <target> <value> [--dry-run]
```

**Files:**
- MOD: `src/agent_core/desktop_agent.py` — `set_value()` method
- MOD: `src/agent_core/cli/main.py` — `set-value` command

**Expected Tests:** 10

---

### TASK-03: Perform-Action Command

**Description:** Named AX action dispatching to UIA patterns.

**DesktopAgent Facade:**
```python
async def perform_action(self, target: str, action: str, **kwargs) -> ActionResult:
    """Perform a named accessibility action on a target element.
    
    Supported actions: invoke, toggle, expand, collapse, select,
    scroll_into_view, focus, set_value, get_value
    """
```

**CLI Command:**
```
desktop-agent perform-action <target> <action> [--value <val>] [--dry-run]
```

**Files:**
- MOD: `src/agent_core/desktop_agent.py` — `perform_action()` method
- MOD: `src/agent_core/cli/main.py` — `perform-action` command
- MOD: `src/agent_core/transport/mcp_server.py` — add clipboard, set_value, perform_action tools
- MOD: `src/agent_core/transport/rest_server.py` — add POST endpoints

**Expected Tests:** 12

---

### TASK-04: Version Bump + Integration Tests

**Description:** Version bump, full suite validation.

**Files:**
- MOD: `src/agent_core/cli/version.py` — 0.35.0 → 0.36.0
- MOD: `pyproject.toml` — version bump
- NEW: `tests/test_clipboard/test_clipboard.py`
- NEW: `tests/test_agent/test_set_value.py`
- NEW: `tests/test_agent/test_perform_action.py`

**Expected Tests:** 5

**Total:** 10 + 10 + 12 + 5 = **37 new tests**

---

## 5. Acceptance Criteria

| AC ID | Criterion | Task |
|-------|-----------|------|
| AC-01-01 | CLI `clipboard read` returns clipboard text | TASK-01 |
| AC-01-02 | CLI `clipboard write <text>` writes to clipboard | TASK-01 |
| AC-01-03 | CLI `clipboard paste` triggers Ctrl+V | TASK-01 |
| AC-02-01 | `set_value()` uses ValuePattern first | TASK-02 |
| AC-02-02 | `set_value()` falls back to click+type | TASK-02 |
| AC-02-03 | CLI `set-value` command functional | TASK-02 |
| AC-03-01 | `perform_action()` dispatches to correct UIA pattern | TASK-03 |
| AC-03-02 | CLI `perform-action` command functional | TASK-03 |
| AC-03-03 | MCP tools for clipboard/set_value/perform_action | TASK-03 |
| AC-03-04 | REST endpoints for clipboard/set_value/perform_action | TASK-03 |
| AC-04-01 | Version is 0.36.0 | TASK-04 |
| AC-04-02 | Full suite passes: 3,195 (3,158 + 37) | TASK-04 |

---

## 6. Baseline Metrics

| Metric | Value |
|--------|-------|
| Version at Batch start:       | v0.35.0 |
| Test count at Batch start:    | 3,158 passing |
| Expected delta (all Tasks):   | +37 new tests |
| Expected total at Batch close:| 3,195 |

---

## 7. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| PowerShell clipboard encoding issues | LOW | Fallback to win32clipboard |
| ValuePattern not available on target | LOW | HB-04: fallback to click+type |

---

## 8. Reviewer Notes

Reviewer Report ID:
Lead Decision:            [ ] ACCEPT   [ ] ACCEPT WITH MODIFICATIONS   [ ] REJECT
Blueprint Version after response:
Lead Sign:                Craft Agent — 2026-05-10
