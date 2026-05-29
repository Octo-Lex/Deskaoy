"""Tests for TaskbarService — Taskbar buttons + system tray interaction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from deskaoy.services.taskbar_service import TaskbarService, TaskbarItem


class TestTaskbarItem:
    """Tests for TaskbarItem dataclass."""

    def test_construction_defaults(self):
        item = TaskbarItem(name="Test")
        assert item.name == "Test"
        assert item.app_id is None
        assert item.is_running is True
        assert item.is_pinned is False
        assert item.tooltip is None
        assert item.element is None

    def test_construction_full(self):
        elem = MagicMock()
        item = TaskbarItem(
            name="Chrome",
            app_id="chrome.exe",
            is_running=True,
            is_pinned=True,
            tooltip="Google Chrome",
            element=elem,
        )
        assert item.name == "Chrome"
        assert item.app_id == "chrome.exe"
        assert item.is_pinned is True
        assert item.tooltip == "Google Chrome"

    def test_repr_excludes_element(self):
        item = TaskbarItem(name="Test", element=MagicMock())
        r = repr(item)
        assert "element=" not in r


class TestTaskbarServiceInit:
    """Tests for TaskbarService initialization."""

    def test_default_init(self):
        svc = TaskbarService()
        assert svc._walker is None

    def test_init_with_walker(self):
        walker = MagicMock()
        svc = TaskbarService(walker=walker)
        assert svc._walker is walker


class TestTaskbarServiceListApps:
    """Tests for list_running_apps."""

    def test_no_taskbar_returns_empty(self):
        svc = TaskbarService()
        mock_root = MagicMock()
        mock_root.FindFirst.return_value = None

        with patch.object(svc, "_get_uia") as mock_uia:
            mock_uia.return_value.root = mock_root
            mock_uia.return_value.iuia.CreatePropertyCondition.return_value = MagicMock()
            mock_uia.return_value._uia_dll.UIA_ClassNamePropertyId = 30004
            results = svc.list_running_apps()
            assert results == []

    def test_no_tasklist_returns_empty(self):
        svc = TaskbarService()
        mock_root = MagicMock()
        mock_taskbar = MagicMock()
        mock_taskbar.FindFirst.return_value = None  # No MSTaskListWClass
        # First FindFirst finds the taskbar, second finds nothing
        mock_root.FindFirst.return_value = mock_taskbar

        with patch.object(svc, "_get_uia") as mock_uia:
            mock_uia.return_value.root = mock_root
            mock_uia.return_value.iuia.CreatePropertyCondition.return_value = MagicMock()
            mock_uia.return_value._uia_dll.UIA_ClassNamePropertyId = 30004
            results = svc.list_running_apps()
            assert results == []

    def test_error_returns_empty(self):
        svc = TaskbarService()
        with patch.object(svc, "_get_uia", side_effect=Exception("boom")):
            results = svc.list_running_apps()
            assert results == []


class TestTaskbarServiceClickButton:
    """Tests for click_taskbar_button and right_click_taskbar."""

    def test_click_no_match(self):
        svc = TaskbarService()
        with patch.object(svc, "list_running_apps", return_value=[
            TaskbarItem(name="Chrome"),
            TaskbarItem(name="VS Code"),
        ]):
            result = svc.click_taskbar_button("Firefox")
            assert result is False

    def test_click_match_invoke(self):
        svc = TaskbarService()
        mock_elem = MagicMock()
        mock_walker = MagicMock()
        mock_walker.try_invoke.return_value = MagicMock(success=True)

        svc._walker = mock_walker
        with patch.object(svc, "list_running_apps", return_value=[
            TaskbarItem(name="Chrome", element=mock_elem),
        ]):
            result = svc.click_taskbar_button("Chrome")
            assert result is True

    def test_right_click_no_match(self):
        svc = TaskbarService()
        with patch.object(svc, "list_running_apps", return_value=[
            TaskbarItem(name="Chrome"),
        ]):
            result = svc.right_click_taskbar("Firefox")
            assert result is False

    def test_click_case_insensitive(self):
        svc = TaskbarService()
        mock_elem = MagicMock()
        mock_walker = MagicMock()
        mock_walker.try_invoke.return_value = MagicMock(success=True)

        svc._walker = mock_walker
        with patch.object(svc, "list_running_apps", return_value=[
            TaskbarItem(name="Google Chrome", element=mock_elem),
        ]):
            result = svc.click_taskbar_button("chrome")
            assert result is True


class TestTaskbarServiceTray:
    """Tests for system tray operations."""

    def test_list_tray_icons_no_taskbar(self):
        svc = TaskbarService()
        mock_root = MagicMock()
        mock_root.FindFirst.return_value = None

        with patch.object(svc, "_get_uia") as mock_uia:
            mock_uia.return_value.root = mock_root
            mock_uia.return_value.iuia.CreatePropertyCondition.return_value = MagicMock()
            mock_uia.return_value._uia_dll.UIA_ClassNamePropertyId = 30004
            results = svc.list_tray_icons()
            assert isinstance(results, list)

    def test_click_tray_icon_no_match(self):
        svc = TaskbarService()
        with patch.object(svc, "list_tray_icons", return_value=[
            TaskbarItem(name="Volume"),
        ]):
            result = svc.click_tray_icon("Network")
            assert result is False

    def test_click_tray_icon_match(self):
        svc = TaskbarService()
        mock_elem = MagicMock()
        mock_walker = MagicMock()
        mock_walker.try_invoke.return_value = MagicMock(success=True)

        svc._walker = mock_walker
        with patch.object(svc, "list_tray_icons", return_value=[
            TaskbarItem(name="Volume", element=mock_elem),
        ]):
            result = svc.click_tray_icon("Volume")
            assert result is True


class TestTaskbarServiceState:
    """Tests for get_taskbar_state."""

    def test_state_no_win32gui(self):
        svc = TaskbarService()
        with patch.dict("sys.modules", {"win32gui": None}):
            state = svc.get_taskbar_state()
            assert state["visible"] is False

    def test_state_default_values(self):
        svc = TaskbarService()
        state = svc.get_taskbar_state()
        assert "visible" in state
        assert "position" in state
        assert "auto_hide" in state
        assert "bounds" in state
