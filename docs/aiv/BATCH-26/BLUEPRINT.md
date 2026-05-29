# BATCH-26 BLUEPRINT — Menu, Taskbar, Dialog & Desktop Support

**Batch:**                BATCH-26
**Version:**              v0.33.0 → v0.34.0
**Cycle Type:**           STANDARD
**AIV Framework:**        v5.2
**Date:**                 2026-05-10
**Lead:**                 Craft Agent (Lead Override per §5.3)
**Blueprint Version:**    1.0

---

## 1. Batch Identity

**Batch Name:**           Menu, Taskbar, Dialog & Desktop Support
**Strategic Bet:**        Windows equivalents of Peekaboo's macOS menu/dock/dialog/space features — Start Menu, Taskbar, System Dialogs, and Virtual Desktop support. Peekaboo pattern gap #3.
**Priority:**             HIGH

**Context:**              Peekaboo has 4 dedicated services (MenuService, DockService, DialogService, SpaceService) for macOS-specific UI interaction. On Windows, the equivalents are: Start Menu → Taskbar, System Tray → notification area, System Dialogs → open/save/message boxes, and Task View → Virtual Desktops. This batch adds Windows-native support for all four.

---

## 2. Scope

### In Scope
- **MenuService**: Start Menu interaction (search, list items, click items), application menu bars (via UIA)
- **TaskbarService**: Taskbar interaction (list running apps, click taskbar buttons, system tray icons)
- **DialogService**: System dialog driving (Open/Save dialogs, MessageBox buttons, File picker)
- **DesktopService**: Virtual desktop switching (Task View), list desktops, move windows between desktops
- All via comtypes UIA patterns — no new dependencies
- CLI commands: `menu`, `taskbar`, `dialog`, `desktop` subcommands
- Health check: add menu/taskbar/dialog/desktop subsystem checks (optional, N/A when unsupported)

### Out of Scope
- macOS/Linux equivalents (future BATCH-33/BATCH-34)
- Notification sending (only reading/dismissing)
- Custom dialog creation (only driving existing system dialogs)

---

## 3. Hard Boundaries

| ID  | Constraint |
|-----|-----------|
| HB-01 | Only reads/drives existing Windows UI — no window creation |
| HB-02 | Must work without admin privileges |
| HB-03 | All 3,037 baseline tests must pass |
| HB-04 | No new required dependencies |

---

## 4. Data Models

```python
@dataclass
class MenuItem:
    """A menu item from Start Menu or application menu bar."""
    name: str
    path: str              # Full path in menu tree: "File > Recent > doc.txt"
    is_submenu: bool
    is_enabled: bool
    shortcut: Optional[str]
    element: Optional[Any]  # UIA element reference (not serialized)

@dataclass
class TaskbarItem:
    """A taskbar button or system tray icon."""
    name: str
    app_id: Optional[str]
    is_running: bool
    is_pinned: bool
    tooltip: Optional[str]
    element: Optional[Any]

@dataclass
class DialogButton:
    """A button in a system dialog."""
    name: str
    button_id: int         # Dialog button ID (IDOK=1, IDCANCEL=2, etc.)
    is_enabled: bool

@dataclass
class VirtualDesktop:
    """A Windows virtual desktop."""
    index: int
    name: Optional[str]
    window_count: int
    is_current: bool
```

---

## 5. Task Sequence

**Sequencing:** SEQUENTIAL (T01 → T02 → T03 → T04 → T05)

### TASK-01: Menu Service

**Description:** Start Menu + application menu bar interaction via UIA.

**New Module:** `src/agent_core/services/menu_service.py`

**Methods:**
| Method | Description |
|--------|-------------|
| `open_start_menu()` | Open Windows Start Menu |
| `search_start(query)` | Search in Start Menu |
| `list_start_items()` | List Start Menu pinned/all items |
| `click_start_item(name)` | Click a Start Menu item |
| `list_menu_bar(hwnd)` | List application menu bar items (File, Edit, etc.) |
| `click_menu_item(hwnd, path)` | Click menu item by path "File > Save" |

**Files:**
- NEW: `src/agent_core/services/__init__.py`
- NEW: `src/agent_core/services/menu_service.py`
- MOD: `src/agent_core/desktop_agent.py` — add `menu` property

**Expected Tests:** 10

---

### TASK-02: Taskbar Service

**Description:** Taskbar and System Tray interaction.

**New Module:** `src/agent_core/services/taskbar_service.py`

**Methods:**
| Method | Description |
|--------|-------------|
| `list_running_apps()` | List taskbar buttons for running apps |
| `click_taskbar_button(name)` | Click a taskbar button by app name |
| `right_click_taskbar(name)` | Right-click a taskbar button |
| `list_tray_icons()` | List system tray icons |
| `click_tray_icon(name)` | Click a system tray icon |
| `get_taskbar_state()` | Get taskbar visibility and position |

**Files:**
- NEW: `src/agent_core/services/taskbar_service.py`
- MOD: `src/agent_core/desktop_agent.py` — add `taskbar` property

**Expected Tests:** 10

---

### TASK-03: Dialog Service

**Description:** System dialog driving (Open, Save, MessageBox, File picker).

**New Module:** `src/agent_core/services/dialog_service.py`

**Methods:**
| Method | Description |
|--------|-------------|
| `list_dialogs()` | List open system dialogs |
| `get_dialog_buttons(hwnd)` | Get buttons for a dialog |
| `click_dialog_button(hwnd, button_id)` | Click dialog button |
| `set_dialog_text(hwnd, text)` | Type in dialog text field |
| `dismiss_dialog(hwnd, action)` | Dismiss dialog (ok/cancel/close) |
| `wait_for_dialog(timeout)` | Wait for a system dialog to appear |

**Files:**
- NEW: `src/agent_core/services/dialog_service.py`
- MOD: `src/agent_core/desktop_agent.py` — add `dialog` property

**Expected Tests:** 8

---

### TASK-04: Desktop Service

**Description:** Virtual desktop management via Task View.

**New Module:** `src/agent_core/services/desktop_service.py`

**Methods:**
| Method | Description |
|--------|-------------|
| `list_desktops()` | List virtual desktops |
| `get_current_desktop()` | Get current desktop index |
| `switch_desktop(index)` | Switch to desktop by index |
| `create_desktop()` | Create new virtual desktop |
| `close_desktop(index)` | Close virtual desktop |
| `move_window_to_desktop(hwnd, index)` | Move window to desktop |

**Implementation Note:** Windows Virtual Desktops don't have a public API. Implementation uses:
- Keyboard shortcuts: `Win+Ctrl+D` (create), `Win+Ctrl+F4` (close), `Win+Ctrl+Left/Right` (switch)
- UIA inspection of Task View for listing desktops
- `SetWindowDesktop` via `IVirtualDesktopManager` COM interface (internal, no admin needed)

**Files:**
- NEW: `src/agent_core/services/desktop_service.py`
- MOD: `src/agent_core/desktop_agent.py` — add `desktop` property

**Expected Tests:** 8

---

### TASK-05: CLI Integration + Health Check + Version Bump

**Description:** CLI commands, health check integration, tests, version bump.

**New CLI Commands:**
| Command | Description |
|---------|-------------|
| `desktop-agent menu search <query>` | Search Start Menu |
| `desktop-agent menu click <path>` | Click menu item |
| `desktop-agent menu list` | List Start Menu items |
| `desktop-agent taskbar list` | List taskbar items |
| `desktop-agent taskbar click <name>` | Click taskbar button |
| `desktop-agent dialog list` | List open dialogs |
| `desktop-agent dialog dismiss <hwnd>` | Dismiss dialog |
| `desktop-agent desktop list` | List virtual desktops |
| `desktop-agent desktop switch <index>` | Switch desktop |

**Health Check:** Add `menu_service`, `taskbar_service`, `dialog_service`, `desktop_service` checks (all N/A when not on Windows or comtypes unavailable).

**Files:**
- MOD: `src/agent_core/cli/main.py` — 4 new command groups
- MOD: `src/agent_core/safety/health.py` — 4 new subsystem checks (13 total)
- MOD: `src/agent_core/cli/version.py` — 0.33.0 → 0.34.0
- MOD: `pyproject.toml` — version bump
- NEW: `tests/test_services/test_menu_service.py`
- NEW: `tests/test_services/test_taskbar_service.py`
- NEW: `tests/test_services/test_dialog_service.py`
- NEW: `tests/test_services/test_desktop_service.py`
- MOD: `tests/test_safety/test_health.py` — update check count
- MOD: `tests/test_release/test_readiness.py` — update check count

**Expected Tests:** 6 (2 CLI tests + 2 health check tests + 2 version/validation)

**Total:** 10 + 10 + 8 + 8 + 6 = **42 new tests**

---

## 6. Acceptance Criteria Summary

| AC ID | Criterion | Task |
|-------|-----------|------|
| AC-01-01 | MenuService can list Start Menu items | TASK-01 |
| AC-01-02 | MenuService can search and click Start Menu items | TASK-01 |
| AC-01-03 | MenuService can read application menu bars via UIA | TASK-01 |
| AC-02-01 | TaskbarService lists running apps in taskbar | TASK-02 |
| AC-02-02 | TaskbarService can click taskbar buttons | TASK-02 |
| AC-02-03 | TaskbarService can enumerate system tray icons | TASK-02 |
| AC-03-01 | DialogService lists open system dialogs | TASK-03 |
| AC-03-02 | DialogService can dismiss dialogs | TASK-03 |
| AC-03-03 | DialogService can set text in dialog fields | TASK-03 |
| AC-04-01 | DesktopService lists virtual desktops | TASK-04 |
| AC-04-02 | DesktopService switches desktops | TASK-04 |
| AC-04-03 | DesktopService creates/closes desktops | TASK-04 |
| AC-05-01 | CLI commands for all 4 services functional | TASK-05 |
| AC-05-02 | Health check includes 13 subsystems (9 + 4 new) | TASK-05 |
| AC-05-03 | Version is 0.34.0 | TASK-05 |
| AC-05-04 | Full suite passes: 3,079 (3,037 + 42) | TASK-05 |

---

## 7. Baseline Metrics

| Metric | Value |
|--------|-------|
| Version at Batch start:       | v0.33.0 |
| Test count at Batch start:    | 3,037 passing |
| Expected delta (all Tasks):   | +42 new tests |
| Expected total at Batch close:| 3,079 |

---

## 8. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Start Menu UI varies across Windows versions | MEDIUM | Use UIA tree walk with graceful fallback |
| Virtual Desktop has no public API | HIGH | Use keyboard shortcuts + IVirtualDesktopManager COM (works without admin) |
| System tray icons are hard to enumerate | MEDIUM | Use ToolbarWindow32 (notify icon overflow) via UIA |
| Dialog automation may trigger security prompts | LOW | Only interact with already-visible dialogs |

---

## 9. Reviewer Notes

Reviewer Report ID:
Review Cycle:
Lead Decision:            [ ] ACCEPT   [ ] ACCEPT WITH MODIFICATIONS   [ ] REJECT

Blueprint Version after response:
Lead Sign:                Craft Agent — 2026-05-10
