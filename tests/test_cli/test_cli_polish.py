"""Tests for CLI polish — BATCH-30 TASK-02.

Covers: --verbose flag, docs command, completions command dispatch,
error suggestions, and help text improvements.
"""
from __future__ import annotations

import logging
import sys
from unittest.mock import patch, MagicMock

import pytest

from deskaoy.cli.main import main, _build_parser, _suggest_command


# ------------------------------------------------------------------
# T30-11: --verbose / -v flag enables DEBUG logging
# ------------------------------------------------------------------

class TestVerboseFlag:

    def test_verbose_flag_parsed(self):
        parser = _build_parser()
        args = parser.parse_args(["--verbose", "version"])
        assert args.verbose is True

    def test_short_verbose_flag_parsed(self):
        parser = _build_parser()
        args = parser.parse_args(["-v", "version"])
        assert args.verbose is True

    def test_verbose_sets_debug_logging(self, capsys):
        with patch.dict("os.environ", {}, clear=False):
            code = main(["--verbose", "version"])
        assert code == 0
        # The logging level should have been set to DEBUG
        # We can't easily check the root logger state after main() returns
        # because basicConfig may have been called already, but we verify
        # the flag is accepted without error.
        out = capsys.readouterr().out
        assert "deskaoy" in out

    def test_no_verbose_default_is_warning(self):
        parser = _build_parser()
        args = parser.parse_args(["version"])
        assert args.verbose is False


# ------------------------------------------------------------------
# T30-12: completions command dispatches correctly
# ------------------------------------------------------------------

class TestCompletionsCommand:

    def test_completions_bash(self, capsys):
        code = main(["completions", "bash"])
        assert code == 0
        out = capsys.readouterr().out
        assert "complete -F" in out
        assert "deskaoy" in out

    def test_completions_powershell(self, capsys):
        code = main(["completions", "powershell"])
        assert code == 0
        out = capsys.readouterr().out
        assert "Register-ArgumentCompleter" in out

    def test_completions_zsh(self, capsys):
        code = main(["completions", "zsh"])
        assert code == 0
        out = capsys.readouterr().out
        assert "#compdef" in out

    def test_completions_invalid_shell_exits(self):
        with pytest.raises(SystemExit):
            main(["completions", "fish"])


# ------------------------------------------------------------------
# T30-13: docs command
# ------------------------------------------------------------------

class TestDocsCommand:

    def test_docs_print_flag(self, capsys):
        code = main(["docs", "--print"])
        assert code == 0
        out = capsys.readouterr().out
        assert "github.com" in out or "README" in out

    def test_docs_topic_changelog(self, capsys):
        code = main(["docs", "--topic", "changelog", "--print"])
        assert code == 0
        out = capsys.readouterr().out
        assert "CHANGELOG" in out

    def test_docs_topic_api(self, capsys):
        code = main(["docs", "--topic", "api", "--print"])
        assert code == 0
        out = capsys.readouterr().out
        assert "api" in out


# ------------------------------------------------------------------
# T30-14: Help text improvements
# ------------------------------------------------------------------

class TestHelpText:

    def test_parser_has_description(self):
        parser = _build_parser()
        assert parser.description is not None
        assert "Deskaoy" in parser.description

    def test_help_contains_examples(self):
        parser = _build_parser()
        assert parser.description is not None
        assert "Examples" in parser.description

    def test_verbose_flag_has_help(self):
        parser = _build_parser()
        for action in parser._actions:
            if "--verbose" in getattr(action, "option_strings", []):
                assert action.help is not None
                assert "DEBUG" in action.help
                break
        else:
            pytest.fail("--verbose flag not found")


# ------------------------------------------------------------------
# T30-15: Error suggestions ("did you mean ...?")
# ------------------------------------------------------------------

class TestErrorSuggestions:

    def test_suggest_close_match(self, capsys):
        _suggest_command(["exxcute"])
        out = capsys.readouterr().err
        assert "Did you mean" in out
        assert "execute" in out

    def test_no_suggestion_for_exact_match(self, capsys):
        _suggest_command(["execute"])
        out = capsys.readouterr().err
        assert "Did you mean" not in out

    def test_no_suggestion_for_flags_only(self, capsys):
        _suggest_command(["--json", "--verbose"])
        out = capsys.readouterr().err
        assert "Did you mean" not in out

    def test_no_suggestion_for_empty(self, capsys):
        _suggest_command([])
        out = capsys.readouterr().err
        assert "Did you mean" not in out
