"""TASK-01 verification: runtime dependencies importable.

These tests verify that comtypes, pyautogui, and mss are installed
and that WindowsAdapter can initialise its lazy imports.
"""
from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows runtime dependency tests",
)


class TestRuntimeDependencies:
    """TEST-16-01-01 through TEST-16-01-04."""

    def test_comtypes_imports(self):
        """TEST-16-01-01: import comtypes succeeds."""
        import comtypes
        assert comtypes is not None

    def test_pyautogui_imports(self):
        """TEST-16-01-02: import pyautogui succeeds."""
        import pyautogui
        assert pyautogui is not None

    def test_mss_imports(self):
        """TEST-16-01-03: import mss succeeds."""
        import mss
        assert mss is not None

    def test_windows_adapter_ensure_imports(self):
        """TEST-16-01-04: WindowsAdapter._ensure_imports() works with real deps."""
        from deskaoy.adapters.windows import WindowsAdapter
        adapter = WindowsAdapter(hwnd=0)
        adapter._ensure_imports()
        assert adapter._win32gui is not None
        assert adapter._win32api is not None
        assert adapter._win32con is not None
        assert adapter._pyautogui is not None
