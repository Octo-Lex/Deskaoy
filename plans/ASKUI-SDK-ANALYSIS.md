# AskUI SDK Analysis — Windows UIA Tree Walking Applicability

## What AskUI SDK Is

**AskUI Vision Agent** — a commercial desktop/mobile automation framework.
Python SDK (v0.2) that wraps a proprietary gRPC controller binary for OS-level operations.

## Architecture (Their Approach)

```
User code
  agent.click("Submit button")
       │
       ▼
  ComputerAgent
       │
       ├── Model Router → sends screenshot to VLM (AskUI/Anthropic/Gemini)
       │                  → returns (x, y) coordinates
       │
       └── AgentOS abstraction
              │
              ├── AskUiControllerClient  (gRPC → proprietary binary)  ← PRIMARY
              ├── PlaywrightAgentOs       (browser only)
              └── AndroidAgentOs          (ADB + uiautomator)
```

**Key insight:** AskUI does NOT do UIA tree walking in Python. They delegate ALL
OS-level operations to their proprietary `AskuiRemoteDeviceController.exe` binary,
which is a C/C++ application that talks to Windows via the UI Automation API internally.
The Python SDK just sends gRPC messages like "click at (x, y)" and "take screenshot".

## What's Useful to Us

### 1. AgentOS Abstract Interface (`tools/agent_os.py`)

Clean abstraction for OS-level operations:
```python
class AgentOs(ABC):
    def screenshot(self) -> Image.Image: ...
    def mouse_move(self, x, y, duration=500): ...
    def type(self, text, typing_speed=50): ...
    def click(self, button="left", count=1): ...
    def mouse_scroll(self, dx, dy): ...
    def keyboard_tap(self, key, modifier_keys=None): ...
    def get_process_list(self): ...
    def get_window_list(self, process_id): ...
    def set_active_window(self, process_id, window_id): ...
    def get_active_window(self): ...
```

**Comparison to our SurfaceAdapter:**

| AskUI AgentOS | Our SurfaceAdapter | Notes |
|---------------|-------------------|-------|
| `screenshot()` | `screenshot()` | Same |
| `mouse_move(x, y)` | N/A (internal to click) | We use Bezier |
| `click(button)` | `click(target)` | We resolve target → coords |
| `type(text)` | `type_text(text)` | Same |
| `keyboard_tap(key)` | `key_press(key)` | Same |
| `mouse_scroll(dx, dy)` | `scroll(direction, amount)` | Same |
| `get_process_list()` | N/A | Window management |
| `get_window_list(pid)` | N/A | Window management |
| `set_active_window()` | N/A | Window management |
| `get_active_window()` | N/A | Window management |

### 2. Android UIAutomator Hierarchy (`tools/android/uiautomator_hierarchy.py`)

The pattern for parsing an accessibility tree into structured elements:

```python
@dataclass
class UIElement:
    text: str
    resource_id: str
    content_desc: str
    class_name: str
    bounds: str            # "[x1,y1][x2,y2]"
    clickable: bool
    enabled: bool
    package: str

    @property
    def center(self) -> tuple[int, int]:
        # Parse bounds → center coordinates
```

**This is the exact pattern we need for Windows UIA**, but using
`comtypes` + `uiautomation` instead of XML parsing.

### 3. Locator System (`locators/locators.py`)

```python
class Locator(ABC): ...          # Base
class Prompt(Locator): ...       # Natural language description
class Text(Locator): ...         # Text content (similar/exact/contains/regex)
class Element(Locator): ...      # Element class
class Image(Locator): ...        # Visual image matching
class AiElement(Locator): ...   # Pre-snipped elements
```

Our cascade already covers this:
- Tier 1 = Selector/AX (like `Element` + `Text`)
- Tier 2 = Coordinate (like absolute position)
- Tier 3 = Vision (like `Prompt` + `Image`)

### 4. Process/Window Management

```python
controller.get_process_list()              # List running processes
controller.get_window_list(process_id)      # Windows for a process
controller.set_active_window(pid, wid)      # Focus a window
controller.get_active_window()              # Current focused window
controller.list_displays()                  # All displays
controller.set_display(display_id)          # Switch display
```

**We already have this in our Windows adapter** via `win32gui` + `win32process`.

## What's NOT Useful

| Feature | Why Not Applicable |
|---------|-------------------|
| gRPC controller binary | Proprietary, not open source |
| AskUI Vision API | Cloud-based, requires API key |
| Model Router | We have our own cascade |
| Chat API | Unrelated to desktop agent |
| MCP tools | Different tool protocol |
| Telemetry | Different observability stack |
| Android agent | We're building Windows, not Android |
| Playwright agent | We already use Patchright |

## What We Should Build (Taking Inspiration)

### Windows UIA Tree Walker (Inspired by UIElement pattern)

```python
# Our equivalent of AskUI's UIElement — but for Windows UIA
@dataclass
class UIAElement:
    name: str
    automation_id: str
    class_name: str
    control_type: str       # "Button", "Edit", "Text", etc.
    bounding_rectangle: tuple[float, float, float, float]
    is_enabled: bool
    is_offscreen: bool
    process_id: int
    children: list[UIAElement]

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bounding_rectangle
        return ((x1 + x2) / 2, (y1 + y2) / 2)
```

### How to Build It

Using `comtypes` (COM type library access) + Windows UI Automation:

```python
import comtypes.client
uia = comtypes.client.CreateObject(
    "{ff48dba4-60ef-4201-aa87-54103eef594e}",  # IUIAutomation
    interface=comtypes.gen.UIAutomationClient.IUIAutomation
)

# Get root element
root = uia.GetRootElement()

# Walk the tree
def walk(element, depth=0, max_depth=10):
    if depth > max_depth:
        return []
    condition = uia.CreateTrueCondition()
    walker = uia.CreateTreeWalker(condition)
    child = walker.GetFirstChildElement(element)
    elements = []
    while child:
        name = child.CurrentName
        control_type = child.CurrentControlType
        rect = child.CurrentBoundingRectangle
        # ... convert to UIAElement
        elements.append(...)
        elements.extend(walk(child, depth + 1, max_depth))
        child = walker.GetNextSiblingElement(child)
    return elements
```

## Conclusion

**AskUI SDK doesn't help with UIA tree walking.** Their entire desktop control
stack lives in a proprietary gRPC binary. The Python SDK is a thin client.

However, their **UIElement pattern** from the Android side is the right shape
for our Windows UIA elements. And their **AgentOS interface** validates our
SurfaceAdapter design — both abstract OS operations behind a protocol.

**For actual UIA tree walking, we need:**
1. `comtypes` — COM type library for IUIAutomation
2. `uiautomation` (optional, higher-level wrapper)
3. Custom tree walker that produces `FusedElement` for our fusion engine
4. Integration into `WindowsAdapter.snapshot()`

**Estimated effort:** 8-10 hours (already scaffolded at 515 lines).
