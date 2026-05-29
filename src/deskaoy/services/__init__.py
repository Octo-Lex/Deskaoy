"""Desktop UI services — Windows-native menu, taskbar, dialog, and desktop interaction.

Services map to Peekaboo's macOS equivalents:
  - MenuService  → macOS MenuService (Start Menu + app menu bars)
  - TaskbarService → macOS DockService (taskbar + system tray)
  - DialogService → macOS DialogService (system dialogs)
  - DesktopService → macOS SpaceService (virtual desktops)

All services use comtypes UI Automation — no new dependencies.
"""

from deskaoy.services.desktop_service import DesktopService
from deskaoy.services.dialog_service import DialogService
from deskaoy.services.menu_service import MenuService
from deskaoy.services.taskbar_service import TaskbarService

__all__ = [
    "MenuService",
    "TaskbarService",
    "DialogService",
    "DesktopService",
]
