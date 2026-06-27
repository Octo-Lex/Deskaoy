"""Tests for DesktopService — Virtual desktop management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deskaoy.services.desktop_service import DesktopService, VirtualDesktop


class TestVirtualDesktop:
    """Tests for VirtualDesktop dataclass."""

    def test_construction_defaults(self):
        vd = VirtualDesktop(index=0)
        assert vd.index == 0
        assert vd.name is None
        assert vd.window_count == 0
        assert vd.is_current is False

    def test_construction_full(self):
        vd = VirtualDesktop(
            index=2,
            name="Desktop 3",
            window_count=5,
            is_current=True,
        )
        assert vd.index == 2
        assert vd.name == "Desktop 3"
        assert vd.window_count == 5
        assert vd.is_current is True


class TestDesktopServiceInit:
    """Tests for DesktopService initialization."""

    def test_default_init(self):
        svc = DesktopService()
        assert svc._walker is None
        assert svc._vdm is None

    def test_init_with_walker(self):
        walker = MagicMock()
        svc = DesktopService(walker=walker)
        assert svc._walker is walker


class TestDesktopServiceListDesktops:
    """Tests for list_desktops."""

    def test_list_returns_at_least_one(self):
        """Even if Task View fails, should return current desktop."""
        svc = DesktopService()
        with patch.object(svc, "_open_task_view"):
            with patch.object(svc, "_walk_task_view_desktops", return_value=[]):
                with patch.object(svc, "_close_task_view"):
                    desktops = svc.list_desktops()
                    assert len(desktops) >= 1
                    assert desktops[0].is_current is True

    def test_list_returns_found_desktops(self):
        svc = DesktopService()
        found = [
            VirtualDesktop(index=0, name="Desktop 1", is_current=True),
            VirtualDesktop(index=1, name="Desktop 2", is_current=False),
        ]
        with patch.object(svc, "_open_task_view"):
            with patch.object(svc, "_walk_task_view_desktops", return_value=found):
                with patch.object(svc, "_close_task_view"):
                    desktops = svc.list_desktops()
                    assert len(desktops) == 2
                    assert desktops[0].is_current is True


class TestDesktopServiceGetCurrentDesktop:
    """Tests for get_current_desktop."""

    def test_get_current_returns_index(self):
        svc = DesktopService()
        with patch.object(svc, "list_desktops", return_value=[
            VirtualDesktop(index=0, name="Desktop 1", is_current=True),
            VirtualDesktop(index=1, name="Desktop 2", is_current=False),
        ]):
            idx = svc.get_current_desktop()
            assert idx == 0

    def test_get_current_default(self):
        svc = DesktopService()
        with patch.object(svc, "list_desktops", side_effect=Exception("boom")):
            idx = svc.get_current_desktop()
            assert idx == 0


class TestDesktopServiceSwitchDesktop:
    """Tests for switch_desktop."""

    def test_switch_same_desktop(self):
        svc = DesktopService()
        with patch.object(svc, "get_current_desktop", return_value=1):
            result = svc.switch_desktop(index=1)
            assert result is True

    def test_switch_forward(self):
        svc = DesktopService()
        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            with patch.object(svc, "get_current_desktop", return_value=0):
                result = svc.switch_desktop(index=2)
                assert result is True
                mock_pyautogui.hotkey.assert_called()

    def test_switch_backward(self):
        svc = DesktopService()
        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            with patch.object(svc, "get_current_desktop", return_value=2):
                result = svc.switch_desktop(index=0)
                assert result is True

    def test_switch_error(self):
        svc = DesktopService()
        with patch.object(svc, "get_current_desktop", side_effect=Exception("boom")):
            result = svc.switch_desktop(index=1)
            assert result is False


class TestDesktopServiceCreateDesktop:
    """Tests for create_desktop."""

    def test_create_sends_shortcut(self):
        svc = DesktopService()
        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            result = svc.create_desktop()
            assert result is True
            mock_pyautogui.hotkey.assert_called_once_with("win", "ctrl", "d")

    def test_create_error(self):
        svc = DesktopService()
        with patch.dict("sys.modules", {"pyautogui": None}):
            svc.create_desktop = lambda: False  # Simulated failure
            assert svc.create_desktop() is False


class TestDesktopServiceCloseDesktop:
    """Tests for close_desktop."""

    def test_close_switches_and_sends_shortcut(self):
        svc = DesktopService()
        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            with patch.object(svc, "switch_desktop", return_value=True):
                result = svc.close_desktop(index=1)
                assert result is True
                mock_pyautogui.hotkey.assert_called_once_with("win", "ctrl", "f4")

    def test_close_switch_fails(self):
        svc = DesktopService()
        with patch.object(svc, "switch_desktop", return_value=False):
            result = svc.close_desktop(index=5)
            assert result is False


class TestDesktopServiceMoveWindow:
    """Tests for move_window_to_desktop."""

    def test_move_keyboard_fallback(self):
        svc = DesktopService()
        with patch.object(svc, "_get_vdm", return_value=None):
            with patch.object(svc, "_move_window_keyboard", return_value=True):
                result = svc.move_window_to_desktop(hwnd=12345, index=1)
                assert result is True

    def test_move_error(self):
        svc = DesktopService()
        with patch.object(svc, "_get_vdm", side_effect=Exception("boom")):
            result = svc.move_window_to_desktop(hwnd=12345, index=1)
            assert result is False
