"""Adapter truthfulness tests — Batch 5/10.

Verifies that Linux adapter methods report their capabilities honestly:

1. **No backend → UNSUPPORTED**: when xdotool is missing or session is
   Wayland, all input methods return ``ErrorCategory.UNSUPPORTED``, not
   fake success.

2. **Backend present → real execution**: when xdotool is available on X11,
   the methods call the subprocess and return success only if it succeeds.

3. **Dry-run never calls subprocess**.

4. **fill() does not click before failing** when backend is unavailable.

5. **Key blocklist wins before backend check**.

6. **Factory macOS gate**.

7. **ErrorCategory.UNSUPPORTED** exists.
"""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.results.types import ErrorCategory

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_adapter():
    """Create a LinuxAdapter, patching away the pyatspi import check."""
    with patch.dict("sys.modules", {"pyatspi": MagicMock()}):
        from deskaoy.adapters.linux import LinuxAdapter
        return LinuxAdapter()


@pytest.fixture
def adapter():
    return _make_adapter()


@pytest.fixture
def no_backend_env():
    """Patch environment so no xdotool backend is detected."""
    with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ""}, clear=False):
        os.environ.pop("DISPLAY", None)
        with patch("shutil.which", return_value=None):
            yield


@pytest.fixture
def wayland_env():
    """Patch environment to simulate Wayland."""
    with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}, clear=False):
        yield


@pytest.fixture
def xdotool_available():
    """Patch environment and shutil.which to simulate xdotool on X11."""
    with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}, clear=False), \
         patch("shutil.which", return_value="/usr/bin/xdotool"):
        yield


def _mock_completed_process(returncode=0, stdout="", stderr=""):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# ---------------------------------------------------------------------------
# 1. No backend → UNSUPPORTED
# ---------------------------------------------------------------------------

class TestLinuxNoBackendUnsupported:

    @pytest.mark.asyncio
    async def test_type_text_unsupported_without_backend(self, adapter, no_backend_env):
        result = await adapter.type_text("hello")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_key_press_unsupported_without_backend(self, adapter, no_backend_env):
        result = await adapter.key_press("Return")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_scroll_unsupported_without_backend(self, adapter, no_backend_env):
        result = await adapter.scroll("down")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_fill_unsupported_without_backend(self, adapter, no_backend_env):
        result = await adapter.fill("field", "hello")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_fill_does_not_click_without_backend(self, adapter, no_backend_env):
        """fill() must NOT perform a real click before returning unsupported."""
        adapter.click = MagicMock()
        await adapter.fill("field", "hello")
        adapter.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_type_text_unsupported_on_wayland(self, adapter, wayland_env):
        result = await adapter.type_text("hello")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED
        assert "wayland" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_key_press_unsupported_on_wayland(self, adapter, wayland_env):
        result = await adapter.key_press("Return")
        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED
        assert "wayland" in result.error.message.lower()


# ---------------------------------------------------------------------------
# 1b. AT-SPI action click contract — succeeds without xdotool
# ---------------------------------------------------------------------------

class TestLinuxAtspiActionClickContract:
    """AT-SPI action click is a real action that works without xdotool.

    The contract is:
    - AT-SPI action click succeeds even when xdotool is unavailable
      (because it is a real accessibility action, not fake success).
    - Coordinate-based click returns UNSUPPORTED without xdotool.
    """

    @pytest.mark.asyncio
    async def test_atspi_action_click_succeeds_without_xdotool(self, adapter, no_backend_env):
        """click() via AT-SPI action succeeds even when xdotool is missing."""
        mock_acc = MagicMock()
        mock_action = MagicMock()
        mock_action.name = "Click"
        mock_action.doAction.return_value = True
        mock_acc.get_action_count.return_value = 1
        mock_acc.get_action_name.return_value = "Click"
        mock_acc.doAction.return_value = True

        with patch.object(adapter, "_ensure_imports"), \
             patch.object(adapter, "_find_accessible", return_value=mock_acc), \
             patch.object(adapter, "_try_atspi_action", return_value={
                 "method": "atspi_action", "action": "click", "target": "button",
             }):
            result = await adapter.click("button")

        assert result.ok
        assert result.data.get("method") == "atspi_action"

    @pytest.mark.asyncio
    async def test_coordinate_click_unsupported_without_xdotool(self, adapter, no_backend_env):
        """When no AT-SPI action is available and xdotool is missing,
        click() returns UNSUPPORTED."""
        with patch.object(adapter, "_ensure_imports"), \
             patch.object(adapter, "_find_accessible", return_value=None), \
             patch.object(adapter, "_resolve_point_or_none", return_value=(100, 200)):
            result = await adapter.click("100,200")

        assert not result.ok
        assert result.error.category == ErrorCategory.UNSUPPORTED


# ---------------------------------------------------------------------------
# 2. Backend present → real xdotool execution
# ---------------------------------------------------------------------------

class TestLinuxXdotoolExecution:

    @pytest.mark.asyncio
    async def test_unresolved_named_target_does_not_click(self, adapter, xdotool_available):
        """Regression: a named target that can't be resolved must NOT
        execute xdotool or return success. Previously it would click (0,0)."""
        with patch.object(adapter, "_run_xdotool") as mock_run, \
             patch.object(adapter, "_ensure_imports"), \
             patch.object(adapter, "_find_accessible", return_value=None), \
             patch.object(adapter, "_resolve_point_or_none", return_value=None):
            result = await adapter.click("Submit")

        assert not result.ok
        assert result.error.category == ErrorCategory.SELECTOR_NOT_FOUND
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_direct_coordinate_click_works(self, adapter, xdotool_available):
        """Direct 'x,y' coordinates must resolve and execute xdotool."""
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()) as mock_run, \
             patch.object(adapter, "_ensure_imports"), \
             patch.object(adapter, "_find_accessible", return_value=None), \
             patch.object(adapter, "_resolve_point_or_none", return_value=(300, 200)):
            result = await adapter.click("300,200")

        assert result.ok
        assert result.data["method"] == "xdotool"
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_scroll_amount_scales_to_repeat(self, adapter, xdotool_available):
        """scroll(amount=500) must produce repeat=5 in xdotool args."""
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()) as mock_run:
            result = await adapter.scroll("down", amount=500)
        assert result.ok
        assert result.data["click_count"] == 5
        args = mock_run.call_args[0][0]
        assert "--repeat" in args
        assert "5" in args

    @pytest.mark.asyncio
    async def test_scroll_amount_bounded_to_max_10(self, adapter, xdotool_available):
        """scroll(amount=5000) must be bounded to repeat=10."""
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()):
            result = await adapter.scroll("down", amount=50000)
        assert result.ok
        assert result.data["click_count"] == 10

    @pytest.mark.asyncio
    async def test_scroll_amount_minimum_1(self, adapter, xdotool_available):
        """scroll(amount=0) must still produce at least repeat=1."""
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()):
            result = await adapter.scroll("down", amount=0)
        assert result.ok
        assert result.data["click_count"] == 1

    @pytest.mark.asyncio
    async def test_type_text_calls_xdotool(self, adapter, xdotool_available):
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()) as mock_run:
            result = await adapter.type_text("hello")
        assert result.ok
        assert result.data["method"] == "xdotool"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "type" in args
        assert "hello" in args

    @pytest.mark.asyncio
    async def test_key_press_calls_xdotool(self, adapter, xdotool_available):
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()) as mock_run:
            result = await adapter.key_press("Return")
        assert result.ok
        assert result.data["method"] == "xdotool"
        args = mock_run.call_args[0][0]
        assert "key" in args
        assert "Return" in args

    @pytest.mark.asyncio
    async def test_scroll_down_maps_button_5(self, adapter, xdotool_available):
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()) as mock_run:
            result = await adapter.scroll("down")
        assert result.ok
        assert result.data["button"] == "5"
        args = mock_run.call_args[0][0]
        assert "5" in args

    @pytest.mark.asyncio
    async def test_scroll_up_maps_button_4(self, adapter, xdotool_available):
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()):
            result = await adapter.scroll("up")
        assert result.ok
        assert result.data["button"] == "4"

    @pytest.mark.asyncio
    async def test_scroll_invalid_direction_fails(self, adapter, xdotool_available):
        result = await adapter.scroll("sideways")
        assert not result.ok
        assert result.error.category == ErrorCategory.VALIDATION

    @pytest.mark.asyncio
    async def test_click_calls_xdotool_mousemove(self, adapter, xdotool_available):
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()) as mock_run, \
             patch.object(adapter, "_ensure_imports"), \
             patch.object(adapter, "_find_accessible", return_value=None), \
             patch.object(adapter, "_resolve_point_or_none", return_value=(300, 200)):
            result = await adapter.click("test button")
        assert result.ok
        assert result.data["method"] == "xdotool"
        args = mock_run.call_args[0][0]
        assert "mousemove" in args
        assert "300" in args
        assert "200" in args
        assert "click" in args

    @pytest.mark.asyncio
    async def test_fill_clicks_then_types(self, adapter, xdotool_available):
        """fill() should click the target then type the value."""
        with patch.object(adapter, "_run_xdotool", return_value=_mock_completed_process()) as mock_run, \
             patch.object(adapter, "_ensure_imports"), \
             patch.object(adapter, "_find_accessible", return_value=None), \
             patch.object(adapter, "_resolve_point_or_none", return_value=(100, 100)):
            result = await adapter.fill("input field", "hello world")
        assert result.ok
        assert result.data["method"] == "xdotool"
        # xdotool should have been called twice: mousemove+click, then type
        assert mock_run.call_count == 2

    @pytest.mark.asyncio
    async def test_xdotool_failure_returns_honest_error(self, adapter, xdotool_available):
        """Command failure must be surfaced honestly."""
        exc = subprocess.CalledProcessError(1, "xdotool", stderr="connection refused")
        with patch.object(adapter, "_run_xdotool", side_effect=exc):
            result = await adapter.type_text("hello")
        assert not result.ok
        assert "xdotool" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_type_text_does_not_log_secret(self, adapter, xdotool_available, caplog):
        """Typed text must not appear in debug logs (credential safety)."""
        import logging as _logging

        from deskaoy.adapters.linux import _redact_xdotool_args

        # Unit test for the redaction helper
        redacted = _redact_xdotool_args(["type", "--clearmodifiers", "--", "my-secret-password"])
        assert "my-secret-password" not in redacted
        assert "<redacted>" in redacted

        # Integration test: type_text logs the command but not the secret
        with patch("subprocess.run", return_value=_mock_completed_process()), \
             caplog.at_level(_logging.DEBUG, logger="deskaoy.adapters.linux"):
            await adapter.type_text("my-secret-password")

        logged = " ".join(record.getMessage() for record in caplog.records)
        assert "my-secret-password" not in logged
        assert "xdotool" in logged
        assert "<redacted>" in logged


# ---------------------------------------------------------------------------
# 3. Dry-run never calls subprocess
# ---------------------------------------------------------------------------

class TestLinuxDryRun:

    @pytest.mark.asyncio
    async def test_type_text_dry_run_no_subprocess(self, adapter):
        with patch.object(adapter, "_run_xdotool") as mock_run:
            result = await adapter.type_text("hello", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_key_press_dry_run_no_subprocess(self, adapter):
        with patch.object(adapter, "_run_xdotool") as mock_run:
            result = await adapter.key_press("Return", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_scroll_dry_run_no_subprocess(self, adapter):
        with patch.object(adapter, "_run_xdotool") as mock_run:
            result = await adapter.scroll("down", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_fill_dry_run_no_subprocess(self, adapter):
        with patch.object(adapter, "_run_xdotool") as mock_run:
            result = await adapter.fill("field", "hello", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_click_dry_run_no_subprocess(self, adapter):
        with patch.object(adapter, "_run_xdotool") as mock_run:
            result = await adapter.click("btn", dry_run=True)
        assert result.ok
        assert result.data["dry_run"] is True
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Key blocklist wins before backend check
# ---------------------------------------------------------------------------

class TestLinuxKeyBlocklist:

    @pytest.mark.asyncio
    async def test_blocked_key_returns_security_error(self, adapter, xdotool_available):
        """Key blocklist must win even when backend is available."""
        with patch.object(adapter, "_run_xdotool") as mock_run:
            # Alt+F4 is blocked (closes window)
            result = await adapter.key_press("F4", modifiers=1)
        assert not result.ok
        assert result.error.category == ErrorCategory.SECURITY
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Factory — macOS requires explicit opt-in
# ---------------------------------------------------------------------------

class TestFactoryMacOSGate:

    def test_macos_factory_requires_opt_in(self):
        """Without DESKTOP_AGENT_MACOS=1, the factory must not silently
        select the experimental macOS adapter."""
        with patch.object(sys, "platform", "darwin"), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DESKTOP_AGENT_MACOS", None)
            with pytest.raises(ImportError, match="experimental"):
                from deskaoy.adapters.environment import Environment
                Environment.create_adapter()

    def test_macos_factory_allows_opt_in(self):
        """With DESKTOP_AGENT_MACOS=1, the factory should proceed past the
        experimental gate. It may still fail if pyobjc isn't installed, but
        the error should be about pyobjc, not about experimental status."""
        with patch.object(sys, "platform", "darwin"), patch.dict(os.environ, {"DESKTOP_AGENT_MACOS": "1"}):
            try:
                from deskaoy.adapters.environment import Environment
                Environment.create_adapter()
            except ImportError as exc:
                assert "experimental" not in str(exc).lower(), (
                    f"Expected pyobjc import error, got experimental gate: {exc}"
                )


# ---------------------------------------------------------------------------
# 6. ErrorCategory.UNSUPPORTED exists
# ---------------------------------------------------------------------------

class TestErrorTaxonomy:

    def test_unsupported_category_exists(self):
        assert ErrorCategory.UNSUPPORTED == "unsupported"
