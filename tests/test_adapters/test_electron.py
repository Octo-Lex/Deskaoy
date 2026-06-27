"""Tests for deskaoy.adapters.electron — G10 Electron App Registry."""

from __future__ import annotations

import pytest

from deskaoy.adapters.electron import (
    ELECTRON_APPS,
    ElectronAppEntry,
    ElectronLauncher,
)

# ---------------------------------------------------------------------------
# Built-in registry
# ---------------------------------------------------------------------------

class TestBuiltInApps:

    def test_all_entries_have_required_fields(self):
        for name, entry in ELECTRON_APPS.items():
            assert entry.name, f"Missing name for {name}"
            assert entry.process_name, f"Missing process_name for {name}"
            assert entry.cdp_port > 0, f"Invalid cdp_port for {name}"
            assert entry.executable_names, f"Missing executable_names for {name}"

    def test_unique_cdp_ports(self):
        ports = [e.cdp_port for e in ELECTRON_APPS.values()]
        assert len(ports) == len(set(ports)), "Duplicate CDP ports detected"

    def test_cursor_entry(self):
        assert "cursor" in ELECTRON_APPS
        assert ELECTRON_APPS["cursor"].cdp_port == 9226

    def test_vscode_entry(self):
        assert "vscode" in ELECTRON_APPS
        assert ELECTRON_APPS["vscode"].process_name == "Code"


# ---------------------------------------------------------------------------
# Launcher
# ---------------------------------------------------------------------------

class TestLauncher:

    def test_get_entry(self):
        launcher = ElectronLauncher()
        entry = launcher.get_entry("cursor")
        assert entry is not None
        assert entry.name == "Cursor"

    def test_get_entry_case_insensitive(self):
        launcher = ElectronLauncher()
        assert launcher.get_entry("Cursor") is not None
        assert launcher.get_entry("CURSOR") is not None

    def test_get_entry_unknown(self):
        launcher = ElectronLauncher()
        assert launcher.get_entry("nonexistent") is None

    def test_get_cdp_url(self):
        launcher = ElectronLauncher()
        url = launcher.get_cdp_url("vscode")
        assert url == "http://localhost:9224"

    def test_get_cdp_url_unknown_raises(self):
        launcher = ElectronLauncher()
        with pytest.raises(ValueError, match="Unknown"):
            launcher.get_cdp_url("nonexistent")

    def test_registered_apps(self):
        launcher = ElectronLauncher()
        apps = launcher.registered_apps
        assert "cursor" in apps
        assert "vscode" in apps
        assert "notion" in apps

    def test_custom_apps(self):
        custom = {
            "myapp": ElectronAppEntry("MyApp", "MyApp", 9999, ["myapp.exe"]),
        }
        launcher = ElectronLauncher(apps=custom)
        assert launcher.get_entry("myapp") is not None
        assert launcher.get_entry("myapp").cdp_port == 9999
        assert launcher.get_entry("cursor") is None  # not in custom
