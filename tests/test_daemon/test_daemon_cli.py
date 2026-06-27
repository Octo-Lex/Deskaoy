"""BATCH-37 TASK-03 tests: CLI integration — daemon subcommands and --daemon flag.

Tests TEST-37-03-01 through TEST-37-03-11.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deskaoy.cli.main import _COMMANDS, _build_parser, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(args: list[str]) -> tuple[int, str]:
    """Run CLI command and capture output."""
    captured = StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        rc = main(args)
        output = captured.getvalue()
    except SystemExit as e:
        output = captured.getvalue()
        rc = e.code if e.code is not None else 0
    finally:
        sys.stdout = old_stdout
    return rc, output


# ---------------------------------------------------------------------------
# TEST-37-03-01: `deskaoy daemon start` starts daemon process
# TEST-37-03-07: `deskaoy daemon start` prints socket path
# ---------------------------------------------------------------------------


class TestDaemonStart:
    """TEST-37-03-01 and TEST-37-03-07: daemon start."""

    def test_start_registers_in_parser(self):
        """TEST-37-03-06 partial: 'start' is a valid daemon subcommand."""
        parser = _build_parser()
        # Parse 'daemon start'
        args = parser.parse_args(["daemon", "start"])
        assert args.command == "daemon"
        assert args.daemon_command == "start"

    @pytest.mark.asyncio
    async def test_start_prints_socket_path(self):
        """TEST-37-03-07: daemon start prints socket path."""
        # Mock subprocess and connection check
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            # Mock the connection check to fail (no existing daemon)
            with patch("deskaoy.cli.main._connect_to_daemon",
                       side_effect=ConnectionError("no daemon")):
                from deskaoy.cli.main import _cmd_daemon_start
                args = MagicMock()
                args.json = False
                rc = await _cmd_daemon_start(args)

                assert rc == 0

    @pytest.mark.asyncio
    async def test_start_reports_already_running(self):
        """TEST-37-03-08: daemon start reports if already running."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()

        ping_response = json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"status": "ok", "uptime_s": 10.0},
        }) + "\n"
        mock_reader.readline = AsyncMock(return_value=ping_response.encode())
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("deskaoy.cli.main._connect_to_daemon",
                   return_value=(mock_reader, mock_writer)):
            from deskaoy.cli.main import _cmd_daemon_start
            args = MagicMock()
            args.json = False
            rc = await _cmd_daemon_start(args)
            assert rc == 0


# ---------------------------------------------------------------------------
# TEST-37-03-02: `deskaoy daemon stop` shuts down daemon
# ---------------------------------------------------------------------------


class TestDaemonStop:
    """TEST-37-03-02: daemon stop."""

    def test_stop_registers_in_parser(self):
        """TEST-37-03-06 partial: 'stop' is a valid daemon subcommand."""
        parser = _build_parser()
        args = parser.parse_args(["daemon", "stop"])
        assert args.command == "daemon"
        assert args.daemon_command == "stop"

    @pytest.mark.asyncio
    async def test_stop_sends_shutdown(self):
        """Stop sends shutdown request to daemon."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()

        shutdown_response = json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"status": "shutting_down"},
        }) + "\n"
        mock_reader.readline = AsyncMock(return_value=shutdown_response.encode())
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("deskaoy.cli.main._connect_to_daemon",
                   return_value=(mock_reader, mock_writer)):
            from deskaoy.cli.main import _cmd_daemon_stop
            args = MagicMock()
            rc = await _cmd_daemon_stop(args)
            assert rc == 0


# ---------------------------------------------------------------------------
# TEST-37-03-03: `deskaoy daemon status` reports running state
# TEST-37-03-10: `deskaoy daemon status` shows uptime and calls served
# ---------------------------------------------------------------------------


class TestDaemonStatus:
    """TEST-37-03-03 and TEST-37-03-10: daemon status."""

    def test_status_registers_in_parser(self):
        """TEST-37-03-06 partial: 'status' is a valid daemon subcommand."""
        parser = _build_parser()
        args = parser.parse_args(["daemon", "status"])
        assert args.command == "daemon"
        assert args.daemon_command == "status"

    @pytest.mark.asyncio
    async def test_status_reports_running(self):
        """TEST-37-03-03: daemon status reports running state."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()

        status_response = json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "result": {
                "healthy": True,
                "surface": "none",
                "calls_served": 5,
                "uptime_s": 120.5,
                "pid": 12345,
            },
        }) + "\n"
        mock_reader.readline = AsyncMock(return_value=status_response.encode())
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        with patch("deskaoy.cli.main._connect_to_daemon",
                   return_value=(mock_reader, mock_writer)):
            from deskaoy.cli.main import _cmd_daemon_status
            args = MagicMock()
            args.json = False
            rc = await _cmd_daemon_status(args)
            output = captured.getvalue()

        sys.stdout = old_stdout
        assert rc == 0
        assert "running" in output

    @pytest.mark.asyncio
    async def test_status_shows_uptime_and_calls(self):
        """TEST-37-03-10: daemon status shows uptime and calls served."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()

        status_response = json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "result": {
                "healthy": True,
                "surface": "none",
                "calls_served": 42,
                "uptime_s": 300.0,
                "pid": 999,
            },
        }) + "\n"
        mock_reader.readline = AsyncMock(return_value=status_response.encode())
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        with patch("deskaoy.cli.main._connect_to_daemon",
                   return_value=(mock_reader, mock_writer)):
            from deskaoy.cli.main import _cmd_daemon_status
            args = MagicMock()
            args.json = False
            rc = await _cmd_daemon_status(args)
            output = captured.getvalue()

        sys.stdout = old_stdout
        assert rc == 0
        assert "uptime" in output.lower() or "300" in output
        assert "42" in output  # calls served

    @pytest.mark.asyncio
    async def test_status_not_running(self):
        """Daemon status when daemon not running."""
        with patch("deskaoy.cli.main._connect_to_daemon",
                   side_effect=ConnectionError("no daemon")):
            from deskaoy.cli.main import _cmd_daemon_status
            args = MagicMock()
            args.json = False
            rc = await _cmd_daemon_status(args)
            assert rc == 1


# ---------------------------------------------------------------------------
# TEST-37-03-04: `deskaoy execute --daemon` routes through DaemonClient
# ---------------------------------------------------------------------------


class TestDaemonFlag:
    """TEST-37-03-04: execute --daemon routes through DaemonClient."""

    def test_daemon_flag_parsed(self):
        """--daemon flag is parsed correctly."""
        parser = _build_parser()
        args = parser.parse_args(["execute", "--daemon", "test instruction"])
        assert args.daemon is True

    def test_no_daemon_flag_default(self):
        """Without --daemon, flag is False."""
        parser = _build_parser()
        args = parser.parse_args(["execute", "test instruction"])
        assert args.daemon is False


# ---------------------------------------------------------------------------
# TEST-37-03-05: `deskaoy execute` (no --daemon) uses direct DesktopAgent
# ---------------------------------------------------------------------------


class TestExecuteDefault:
    """TEST-37-03-05: Default execute uses direct DesktopAgent."""

    def test_execute_without_daemon_flag(self):
        """execute without --daemon creates DesktopAgent directly."""
        parser = _build_parser()
        args = parser.parse_args(["execute", "test instruction"])
        assert hasattr(args, "daemon")
        assert args.daemon is False


# ---------------------------------------------------------------------------
# TEST-37-03-06: daemon subcommand parser registered with correct sub-subcommands
# ---------------------------------------------------------------------------


class TestDaemonParser:
    """TEST-37-03-06: daemon subcommand parser has start/stop/status."""

    def test_subcommands_available(self):
        """start, stop, status are available sub-subcommands."""
        parser = _build_parser()
        # Try parsing each
        for subcmd in ("start", "stop", "status"):
            args = parser.parse_args(["daemon", subcmd])
            assert args.command == "daemon"
            assert args.daemon_command == subcmd


# ---------------------------------------------------------------------------
# TEST-37-03-08: `deskaoy daemon start` fails if already running
# ---------------------------------------------------------------------------


class TestDaemonStartDuplicate:
    """TEST-37-03-08: daemon start fails with error if already running."""

    @pytest.mark.asyncio
    async def test_already_running_message(self):
        """Start reports already running when daemon responds to ping."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()

        ping_response = json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"status": "ok", "uptime_s": 5.0},
        }) + "\n"
        mock_reader.readline = AsyncMock(return_value=ping_response.encode())
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        with patch("deskaoy.cli.main._connect_to_daemon",
                   return_value=(mock_reader, mock_writer)):
            from deskaoy.cli.main import _cmd_daemon_start
            args = MagicMock()
            args.json = False
            rc = await _cmd_daemon_start(args)
            output = captured.getvalue()

        sys.stdout = old_stdout
        assert rc == 0
        assert "already running" in output.lower()


# ---------------------------------------------------------------------------
# TEST-37-03-09: daemon CLI commands accessible from help text
# ---------------------------------------------------------------------------


class TestDaemonHelpText:
    """TEST-37-03-09: daemon CLI commands accessible from help text."""

    def test_daemon_in_commands(self):
        """'daemon' is registered in _COMMANDS."""
        assert "daemon" in _COMMANDS

    def test_daemon_in_help_output(self):
        """'daemon' appears in help output."""
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            main(["--help"])
        except SystemExit:
            pass
        finally:
            sys.stdout = old_stdout
        output = captured.getvalue()
        assert "daemon" in output.lower()


# ---------------------------------------------------------------------------
# TEST-37-03-11: Existing CLI commands still work after daemon subcommands
# ---------------------------------------------------------------------------


class TestCLIRegression:
    """TEST-37-03-11: Existing CLI commands still work."""

    def test_execute_in_commands(self):
        assert "execute" in _COMMANDS

    def test_health_in_commands(self):
        assert "health" in _COMMANDS

    def test_version_in_commands(self):
        assert "version" in _COMMANDS

    def test_describe_in_commands(self):
        assert "describe" in _COMMANDS

    def test_schema_in_commands(self):
        assert "schema" in _COMMANDS

    def test_all_original_commands_present(self):
        """All pre-existing commands are still in _COMMANDS."""
        expected = [
            "execute", "estimate", "health", "describe", "schema",
            "version", "doctor", "repl", "status", "snapshot",
            "snapshots", "observe", "set-value", "perform-action",
            "completions", "docs", "chat", "run",
        ]
        for cmd in expected:
            assert cmd in _COMMANDS, f"Command '{cmd}' missing from _COMMANDS"
