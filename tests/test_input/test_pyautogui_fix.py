"""Tests for pyautogui '<' bug fix (v0.16.0 — OSWorld pattern)."""

from __future__ import annotations

from deskaoy.input.types import fix_pyautogui_less_than


class TestFixPyautguiLessThan:
    def test_converts_less_than(self):
        assert fix_pyautogui_less_than("<") == ","

    def test_handles_multiple_less_than(self):
        assert fix_pyautogui_less_than("a<b<c") == "a,b,c"

    def test_passes_through_no_less_than(self):
        assert fix_pyautogui_less_than("hello world") == "hello world"

    def test_empty_string(self):
        assert fix_pyautogui_less_than("") == ""

    def test_only_less_than(self):
        assert fix_pyautogui_less_than("<<<") == ",,,"

    def test_mixed_content(self):
        assert fix_pyautogui_less_than("5 < 10") == "5 , 10"
