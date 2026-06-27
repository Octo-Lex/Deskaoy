"""Tests for DialogService — System dialog driving."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deskaoy.services.dialog_service import (
    BUTTON_NAME_TO_ID,
    DIALOG_CLASS,
    IDCANCEL,
    IDNO,
    IDOK,
    IDYES,
    DialogButton,
    DialogService,
)


class TestDialogButton:
    """Tests for DialogButton dataclass."""

    def test_construction(self):
        btn = DialogButton(name="OK", button_id=IDOK)
        assert btn.name == "OK"
        assert btn.button_id == 1
        assert btn.is_enabled is True

    def test_disabled_button(self):
        btn = DialogButton(name="Cancel", button_id=IDCANCEL, is_enabled=False)
        assert btn.is_enabled is False


class TestButtonConstants:
    """Tests for dialog button constants."""

    def test_button_ids(self):
        assert IDOK == 1
        assert IDCANCEL == 2
        assert IDYES == 6
        assert IDNO == 7

    def test_button_name_mapping(self):
        assert BUTTON_NAME_TO_ID["ok"] == IDOK
        assert BUTTON_NAME_TO_ID["cancel"] == IDCANCEL
        assert BUTTON_NAME_TO_ID["&ok"] == IDOK
        assert BUTTON_NAME_TO_ID["yes"] == IDYES

    def test_dialog_class(self):
        assert DIALOG_CLASS == "#32770"


class TestDialogServiceInit:
    """Tests for DialogService initialization."""

    def test_default_init(self):
        svc = DialogService()
        assert svc._walker is None

    def test_init_with_walker(self):
        walker = MagicMock()
        svc = DialogService(walker=walker)
        assert svc._walker is walker


class TestDialogServiceListDialogs:
    """Tests for list_dialogs."""

    def test_list_dialogs_no_win32gui(self):
        svc = DialogService()
        with patch.dict("sys.modules", {"win32gui": None}):
            results = svc.list_dialogs()
            assert results == []

    def test_list_dialogs_returns_list(self):
        svc = DialogService()
        with patch.dict("sys.modules", {"win32gui": MagicMock()}):
            results = svc.list_dialogs()
            assert isinstance(results, list)


class TestDialogServiceGetButtons:
    """Tests for get_dialog_buttons."""

    def test_get_buttons_no_uia(self):
        svc = DialogService()
        with patch.object(svc, "_get_uia", side_effect=Exception("no uia")):
            buttons = svc.get_dialog_buttons(hwnd=12345)
            assert buttons == []

    def test_get_buttons_returns_list(self):
        svc = DialogService()
        mock_root = MagicMock()
        mock_found_all = MagicMock()
        mock_found_all.Length = 0

        mock_root.FindAll.return_value = mock_found_all

        with patch.object(svc, "_get_uia") as mock_uia:
            mock_uia.return_value.element_from_handle.return_value = mock_root
            mock_uia.return_value.iuia.CreatePropertyCondition.return_value = MagicMock()
            mock_uia.return_value._uia_dll.UIA_ControlTypePropertyId = 30003
            mock_uia.return_value.TREE_SCOPE_CHILDREN = 2
            buttons = svc.get_dialog_buttons(hwnd=12345)
            assert isinstance(buttons, list)


class TestDialogServiceClickButton:
    """Tests for click_dialog_button."""

    def test_click_with_win32gui(self):
        svc = DialogService()
        mock_win32gui = MagicMock()
        mock_win32gui.GetDlgItem.return_value = 999  # Found button
        mock_win32gui.SendMessage.return_value = None

        with patch.dict("sys.modules", {"win32gui": mock_win32gui}):
            with patch.dict("sys.modules", {"win32con": MagicMock()}):
                result = svc.click_dialog_button(hwnd=12345, button_id=IDOK)
                assert result is True

    def test_click_no_win32gui(self):
        svc = DialogService()
        with patch.dict("sys.modules", {"win32gui": None, "win32con": None}):
            result = svc.click_dialog_button(hwnd=12345, button_id=IDOK)
            assert result is False


class TestDialogServiceSetDialogText:
    """Tests for set_dialog_text."""

    def test_set_text_no_uia(self):
        svc = DialogService()
        with patch.object(svc, "_get_uia", side_effect=Exception("no uia")):
            result = svc.set_dialog_text(hwnd=12345, text="hello")
            assert result is False

    def test_set_text_no_edit_field(self):
        svc = DialogService()
        mock_root = MagicMock()
        mock_root.FindFirst.return_value = None  # No edit control

        with patch.object(svc, "_get_uia") as mock_uia:
            mock_uia.return_value.element_from_handle.return_value = mock_root
            mock_uia.return_value.iuia.CreatePropertyCondition.return_value = MagicMock()
            mock_uia.return_value._uia_dll.UIA_ControlTypePropertyId = 30003
            mock_uia.return_value.TREE_SCOPE_DESCENDANTS = 4
            result = svc.set_dialog_text(hwnd=12345, text="hello")
            assert result is False


class TestDialogServiceDismiss:
    """Tests for dismiss_dialog."""

    def test_dismiss_ok(self):
        svc = DialogService()
        with patch.object(svc, "click_dialog_button", return_value=True) as mock_click:
            result = svc.dismiss_dialog(hwnd=12345, action="ok")
            assert result is True
            mock_click.assert_called_once_with(12345, IDOK)

    def test_dismiss_cancel(self):
        svc = DialogService()
        with patch.object(svc, "click_dialog_button", return_value=True) as mock_click:
            result = svc.dismiss_dialog(hwnd=12345, action="cancel")
            assert result is True
            mock_click.assert_called_once_with(12345, IDCANCEL)

    def test_dismiss_unknown_action(self):
        svc = DialogService()
        result = svc.dismiss_dialog(hwnd=12345, action="unknown")
        assert result is False


class TestDialogServiceWaitForDialog:
    """Tests for wait_for_dialog."""

    def test_wait_immediate_find(self):
        svc = DialogService()
        with patch.object(svc, "list_dialogs", return_value=[
            {"hwnd": 12345, "title": "Test", "visible": True},
        ]):
            result = svc.wait_for_dialog(timeout=1.0, poll_interval=0.1)
            assert result == 12345

    def test_wait_timeout(self):
        svc = DialogService()
        with patch.object(svc, "list_dialogs", return_value=[]):
            result = svc.wait_for_dialog(timeout=0.3, poll_interval=0.1)
            assert result is None
