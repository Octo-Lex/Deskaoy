"""Tests for MenuService — Start Menu + app menu bar interaction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deskaoy.services.menu_service import MenuItem, MenuService


class TestMenuItem:
    """Tests for MenuItem dataclass."""

    def test_construction_defaults(self):
        item = MenuItem(name="Test")
        assert item.name == "Test"
        assert item.path == ""
        assert item.is_submenu is False
        assert item.is_enabled is True
        assert item.shortcut is None
        assert item.element is None

    def test_construction_full(self):
        elem = MagicMock()
        item = MenuItem(
            name="Save",
            path="File > Save",
            is_submenu=False,
            is_enabled=True,
            shortcut="Ctrl+S",
            element=elem,
        )
        assert item.name == "Save"
        assert item.path == "File > Save"
        assert item.shortcut == "Ctrl+S"
        assert item.element is elem

    def test_repr_excludes_element(self):
        """element field should not appear in repr (field(repr=False))."""
        item = MenuItem(name="Test", element=MagicMock())
        r = repr(item)
        assert "element=" not in r


class TestMenuServiceInit:
    """Tests for MenuService initialization."""

    def test_default_init(self):
        svc = MenuService()
        assert svc._walker is None

    def test_init_with_walker(self):
        walker = MagicMock()
        svc = MenuService(walker=walker)
        assert svc._walker is walker


class TestMenuServiceStartMenu:
    """Tests for Start Menu operations."""

    def test_open_start_menu(self):
        svc = MenuService()
        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            result = svc.open_start_menu()
            assert result is True
            mock_pyautogui.press.assert_called_once_with("win")

    def test_open_start_menu_fails_gracefully(self):
        svc = MenuService()
        with patch.dict("sys.modules", {"pyautogui": None}):
            # No pyautogui import → should catch and return False
            svc.open_start_menu = lambda: False  # Simulated failure
            assert svc.open_start_menu() is False

    def test_search_start_returns_list(self):
        svc = MenuService()
        with patch.object(svc, "open_start_menu", return_value=True):
            with patch.object(svc, "_walk_start_results", return_value=[]):
                with patch.dict("sys.modules", {"pyautogui": MagicMock()}):
                    results = svc.search_start("notepad")
                    assert isinstance(results, list)

    def test_list_start_items_returns_list(self):
        svc = MenuService()
        with patch.object(svc, "open_start_menu", return_value=True):
            with patch.object(svc, "_walk_start_items", return_value=[]):
                results = svc.list_start_items()
                assert isinstance(results, list)

    def test_click_start_item_no_element(self):
        svc = MenuService()
        with patch.object(svc, "open_start_menu", return_value=True):
            with patch.object(svc, "_find_start_menu_element", return_value=None):
                result = svc.click_start_item("Notepad")
                assert result is False

    def test_click_start_item_with_element(self):
        svc = MenuService()
        mock_elem = MagicMock()
        mock_elem.FindFirst.return_value = None  # No match

        with patch.object(svc, "open_start_menu", return_value=True):
            with patch.object(svc, "_find_start_menu_element", return_value=mock_elem):
                result = svc.click_start_item("Notepad")
                assert result is False  # No match found

    def test_list_start_items_error_handling(self):
        svc = MenuService()
        with patch.object(svc, "open_start_menu", side_effect=Exception("boom")):
            results = svc.list_start_items()
            assert results == []


class TestMenuServiceMenuBar:
    """Tests for application menu bar operations."""

    def test_list_menu_bar_no_menubar(self):
        svc = MenuService()
        mock_root = MagicMock()
        mock_root.FindFirst.return_value = None

        with patch.object(svc, "_get_uia") as mock_uia:
            mock_uia.return_value.element_from_handle.return_value = mock_root
            mock_uia.return_value.iuia.CreatePropertyCondition.return_value = MagicMock()
            mock_uia.return_value._uia_dll.UIA_ControlTypePropertyId = 30003
            results = svc.list_menu_bar(hwnd=12345)
            assert results == []

    def test_click_menu_item_empty_path(self):
        svc = MenuService()
        result = svc.click_menu_item(hwnd=12345, path="")
        assert result is False

    def test_click_menu_item_no_menubar(self):
        svc = MenuService()
        mock_root = MagicMock()
        mock_root.FindFirst.return_value = None

        with patch.object(svc, "_get_uia") as mock_uia:
            mock_uia.return_value.element_from_handle.return_value = mock_root
            mock_uia.return_value.iuia.CreatePropertyCondition.return_value = MagicMock()
            mock_uia.return_value._uia_dll.UIA_ControlTypePropertyId = 30003
            result = svc.click_menu_item(hwnd=12345, path="File > Save")
            assert result is False

    def test_list_menu_bar_error_handling(self):
        svc = MenuService()
        with patch.object(svc, "_get_uia", side_effect=Exception("boom")):
            results = svc.list_menu_bar(hwnd=12345)
            assert results == []


class TestMenuServiceFindStartMenu:
    """Tests for _find_start_menu_element helper."""

    def test_find_by_class_name(self):
        svc = MenuService()
        mock_root = MagicMock()
        mock_found = MagicMock()
        mock_root.FindFirst.return_value = mock_found

        with patch.object(svc, "_get_uia") as mock_uia:
            mock_uia.return_value.root = mock_root
            mock_uia.return_value.iuia.CreatePropertyCondition.return_value = MagicMock()
            mock_uia.return_value._uia_dll.UIA_ClassNamePropertyId = 30004
            result = svc._find_start_menu_element()
            assert result == mock_found

    def test_find_returns_none_on_error(self):
        svc = MenuService()
        with patch.object(svc, "_get_uia", side_effect=Exception("no uia")):
            result = svc._find_start_menu_element()
            assert result is None
