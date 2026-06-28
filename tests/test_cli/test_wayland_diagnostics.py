"""Tests for Wayland diagnostic states — Batch 13.

Covers:
  - Portal service file detection (real path, not mocked)
  - Main portal service detected => WARN
  - GNOME backend detected => WARN with "GNOME"
  - KDE backend detected => WARN with "KDE"
  - No service files => WARN "not detected"
  - libei check is SKIP when not installed
  - All portal checks are WARN/SKIP, never FAIL
  - Wayland input still UNSUPPORTED
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

from deskaoy.diagnostics.doctor import (
    Status,
    _detect_linux_input_backend,
    _detect_wayland_portal,
)


class TestWaylandPortalDetection:
    """Exercise the real service-file scanning logic."""

    def _make_service_dir(self, tmp_path, files: list[str]):
        """Create a temp D-Bus service directory with the given service files."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        for f in files:
            (services_dir / f).write_text("[D-BUS]\n")
        return [str(services_dir)]

    def test_main_portal_service_detected(self, tmp_path):
        """org.freedesktop.portal.Desktop.service => portal detected, WARN."""
        dirs = self._make_service_dir(tmp_path, [
            "org.freedesktop.portal.Desktop.service",
        ])
        results = _detect_wayland_portal(service_dirs=dirs)
        portal = [c for c in results if "portal" in c.name.lower()][0]
        assert portal.status == Status.WARN
        assert "not yet implemented" in portal.detail.lower()

    def test_gnome_backend_detected(self, tmp_path):
        """GNOME backend service file => backend identified."""
        dirs = self._make_service_dir(tmp_path, [
            "org.freedesktop.portal.Desktop.service",
            "org.freedesktop.impl.portal.desktop.gnome.service",
        ])
        results = _detect_wayland_portal(service_dirs=dirs)
        portal = [c for c in results if "portal" in c.name.lower()][0]
        assert portal.status == Status.WARN
        assert "GNOME" in portal.detail

    def test_kde_backend_detected(self, tmp_path):
        """KDE backend service file => backend identified."""
        dirs = self._make_service_dir(tmp_path, [
            "org.freedesktop.portal.Desktop.service",
            "org.freedesktop.impl.portal.desktop.kde.service",
        ])
        results = _detect_wayland_portal(service_dirs=dirs)
        portal = [c for c in results if "portal" in c.name.lower()][0]
        assert portal.status == Status.WARN
        assert "KDE" in portal.detail

    def test_wlroots_backend_detected(self, tmp_path):
        """wlroots backend service file => backend identified."""
        dirs = self._make_service_dir(tmp_path, [
            "org.freedesktop.portal.Desktop.service",
            "org.freedesktop.impl.portal.desktop.wlr.service",
        ])
        results = _detect_wayland_portal(service_dirs=dirs)
        portal = [c for c in results if "portal" in c.name.lower()][0]
        assert portal.status == Status.WARN
        assert "wlroots" in portal.detail

    def test_backend_only_without_main_service(self, tmp_path):
        """Backend impl service alone (no main portal service) should still
        be detected because it implies xdg-desktop-portal is installed."""
        dirs = self._make_service_dir(tmp_path, [
            "org.freedesktop.impl.portal.desktop.gnome.service",
        ])
        results = _detect_wayland_portal(service_dirs=dirs)
        portal = [c for c in results if "portal" in c.name.lower()][0]
        assert "GNOME" in portal.detail

    def test_no_service_files_reports_not_detected(self, tmp_path):
        """Empty service directory => not detected, WARN."""
        dirs = self._make_service_dir(tmp_path, [])
        results = _detect_wayland_portal(service_dirs=dirs)
        portal = [c for c in results if "portal" in c.name.lower()][0]
        assert portal.status == Status.WARN
        assert "not detected" in portal.detail.lower()

    def test_nonexistent_directory_handled(self):
        """Nonexistent service directories should not crash."""
        results = _detect_wayland_portal(service_dirs=["/nonexistent/path"])
        portal = [c for c in results if "portal" in c.name.lower()][0]
        assert portal.status == Status.WARN

    def test_all_portal_checks_are_warn_or_skip(self, tmp_path):
        """No portal check should ever be FAIL."""
        dirs = self._make_service_dir(tmp_path, [
            "org.freedesktop.portal.Desktop.service",
        ])
        results = _detect_wayland_portal(service_dirs=dirs)
        for check in results:
            assert check.status in (Status.WARN, Status.SKIP), (
                f"{check.name} is {check.status} — should be WARN/SKIP"
            )


class TestLibeiDetection:

    def test_libei_not_installed_reports_skip(self):
        with patch.dict(sys.modules, {"libei": None}):
            results = _detect_wayland_portal(service_dirs=[])
        libei = [c for c in results if "libei" in c.name.lower()][0]
        assert libei.status == Status.SKIP

    def test_libei_installed_reports_warn(self):
        with patch.dict(sys.modules, {"libei": object()}):
            results = _detect_wayland_portal(service_dirs=[])
        libei = [c for c in results if "libei" in c.name.lower()][0]
        assert libei.status == Status.WARN


class TestWaylandInputStillUnsupported:

    def test_detect_backend_reports_unavailable_on_wayland(self):
        """Wayland input injection is still UNSUPPORTED."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}):
            name, available, reason = _detect_linux_input_backend()
        assert available is False
        assert "wayland" in reason.lower()
