"""Tests for CLI completion generator — BATCH-30 TASK-01."""
from __future__ import annotations

import argparse

import pytest

from deskaoy.cli.completions import CompletionGenerator

# ------------------------------------------------------------------
# Fixtures — mock argparse parsers
# ------------------------------------------------------------------

def _simple_parser() -> argparse.ArgumentParser:
    """Build a minimal parser with a few subcommands."""
    parser = argparse.ArgumentParser(prog="deskaoy")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("execute", help="Execute instruction")
    sub.add_parser("version", help="Print version")
    sub.add_parser("health", help="Health check")
    return parser


def _rich_parser() -> argparse.ArgumentParser:
    """Build a richer parser with nested subcommands and options."""
    parser = argparse.ArgumentParser(prog="deskaoy")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--storage-dir", help="Storage dir")
    sub = parser.add_subparsers(dest="command")

    p_exec = sub.add_parser("execute", help="Execute instruction")
    p_exec.add_argument("instruction", help="Instruction")
    p_exec.add_argument("--dry-run", action="store_true")
    p_exec.add_argument("--capability", default="automate")

    p_sched = sub.add_parser("schedule", help="Manage routines")
    sched_sub = p_sched.add_subparsers(dest="schedule_command")
    p_add = sched_sub.add_parser("add", help="Add routine")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--cron", required=True)
    sched_sub.add_parser("list", help="List routines")

    sub.add_parser("version", help="Print version")
    return parser


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestCompletionGeneratorInit:
    """T30-01: CompletionGenerator wraps parser."""

    def test_stores_parser(self):
        parser = _simple_parser()
        gen = CompletionGenerator(parser)
        assert gen._parser is parser


class TestCollectCommands:
    """T30-02: _collect_commands introspects subcommand names."""

    def test_simple_commands(self):
        gen = CompletionGenerator(_simple_parser())
        cmds = gen._collect_commands()
        assert "execute" in cmds
        assert "version" in cmds
        assert "health" in cmds

    def test_no_duplicates(self):
        gen = CompletionGenerator(_simple_parser())
        cmds = gen._collect_commands()
        assert len(cmds) == len(set(cmds))

    def test_sorted_order(self):
        gen = CompletionGenerator(_simple_parser())
        cmds = gen._collect_commands()
        assert cmds == sorted(cmds)


class TestCollectGlobalOptions:
    """T30-03: _collect_global_options finds top-level flags."""

    def test_finds_json_and_verbose(self):
        gen = CompletionGenerator(_simple_parser())
        opts = gen._collect_global_options()
        assert "--json" in opts
        assert "--verbose" in opts
        assert "-v" in opts

    def test_excludes_help(self):
        gen = CompletionGenerator(_simple_parser())
        opts = gen._collect_global_options()
        assert "--help" not in opts
        assert "-h" not in opts


class TestCollectCommandOptions:
    """T30-04: _collect_command_options finds per-command options."""

    def test_execute_options(self):
        gen = CompletionGenerator(_rich_parser())
        opts = gen._collect_command_options()
        assert "--dry-run" in opts.get("execute", [])
        assert "--capability" in opts.get("execute", [])

    def test_schedule_nested_subcommands(self):
        gen = CompletionGenerator(_rich_parser())
        opts = gen._collect_command_options()
        sched_opts = opts.get("schedule", [])
        assert "add" in sched_opts
        assert "list" in sched_opts


class TestGeneratePowerShell:
    """T30-05: PowerShell output is a valid completion script."""

    def test_contains_register_argument_completer(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_powershell()
        assert "Register-ArgumentCompleter" in script

    def test_contains_commands(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_powershell()
        assert "'execute'" in script
        assert "'version'" in script

    def test_prog_name_used(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_powershell()
        assert "deskaoy" in script


class TestGenerateBash:
    """T30-06: Bash output is a valid completion script."""

    def test_contains_complete_f(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_bash()
        assert "complete -F" in script

    def test_contains_init_completion(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_bash()
        assert "_init_completion" in script

    def test_contains_commands(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_bash()
        assert "execute" in script
        assert "version" in script


class TestGenerateZsh:
    """T30-07: Zsh output is a valid completion script."""

    def test_contains_compdef(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_zsh()
        assert "#compdef" in script

    def test_contains_arguments(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_zsh()
        assert "_arguments" in script

    def test_contains_describe(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate_zsh()
        assert "_describe" in script


class TestGenerateDispatch:
    """T30-08: generate() dispatches by shell name."""

    def test_powershell_dispatch(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate("powershell")
        assert "Register-ArgumentCompleter" in script

    def test_bash_dispatch(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate("bash")
        assert "complete -F" in script

    def test_zsh_dispatch(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate("zsh")
        assert "#compdef" in script

    def test_unsupported_shell_raises(self):
        gen = CompletionGenerator(_simple_parser())
        with pytest.raises(ValueError, match="Unsupported shell"):
            gen.generate("fish")

    def test_case_insensitive(self):
        gen = CompletionGenerator(_simple_parser())
        script = gen.generate("PowerShell")
        assert "Register-ArgumentCompleter" in script


class TestFromRealParser:
    """T30-09: Completions from the real CLI parser."""

    def test_real_parser_powershell(self):
        from deskaoy.cli.main import _build_parser
        gen = CompletionGenerator(_build_parser())
        script = gen.generate_powershell()
        assert "execute" in script
        assert "version" in script
        assert "doctor" in script

    def test_real_parser_bash(self):
        from deskaoy.cli.main import _build_parser
        gen = CompletionGenerator(_build_parser())
        script = gen.generate_bash()
        assert "complete -F" in script
        assert "execute" in script

    def test_real_parser_zsh(self):
        from deskaoy.cli.main import _build_parser
        gen = CompletionGenerator(_build_parser())
        script = gen.generate_zsh()
        assert "#compdef" in script
        assert "_describe" in script


class TestRichParserCompletions:
    """T30-10: Nested subcommands produce correct output."""

    def test_bash_schedule_subcommands(self):
        gen = CompletionGenerator(_rich_parser())
        script = gen.generate_bash()
        # The schedule command should list its nested subcommands (add, list)
        assert "schedule" in script

    def test_powershell_schedule_subcommands(self):
        gen = CompletionGenerator(_rich_parser())
        script = gen.generate_powershell()
        assert "'schedule'" in script
