"""Tests for key blocklist and sensitive app detection (BATCH-05 TASK-02)."""
from __future__ import annotations

import pytest

from deskaoy.safety.key_blocklist import BLOCKED_KEYS, block_reason, is_blocked_key
from deskaoy.safety.sensitive_apps import (
    SENSITIVE_APPS,
    SensitiveTier,
    is_sensitive_app,
    sensitive_app_reason,
    sensitive_app_tier,
)

# ---------------------------------------------------------------------------
# Key Blocklist Tests
# ---------------------------------------------------------------------------

class TestKeyBlocklist:
    """TEST-05-02-01 through TEST-05-02-04."""

    def test_alt_f4_blocked(self):
        """TEST-05-02-01: Alt+F4 is blocked."""
        assert is_blocked_key("Alt+F4") is True

    def test_ctrl_alt_del_blocked(self):
        """TEST-05-02-02: Ctrl+Alt+Del is blocked."""
        assert is_blocked_key("Ctrl+Alt+Del") is True

    def test_normal_key_not_blocked(self):
        """TEST-05-02-03: Normal key 'a' is not blocked."""
        assert is_blocked_key("a") is False
        assert is_blocked_key("Enter") is False
        assert is_blocked_key("ctrl+c") is False

    def test_block_reason_exists(self):
        """TEST-05-02-04: Blocked keys have explanations."""
        reason = block_reason("Alt+F4")
        assert "window" in reason.lower() or "close" in reason.lower()

    def test_block_reason_unknown(self):
        """Block reason for unknown key is generic."""
        reason = block_reason("ctrl+a")
        assert "blocked" in reason.lower()

    def test_cmd_q_blocked(self):
        """Cmd+Q (macOS quit) is blocked."""
        assert is_blocked_key("Cmd+Q") is True
        assert is_blocked_key("cmd+q") is True

    def test_shift_delete_blocked(self):
        """Shift+Delete (permanent delete) is blocked."""
        assert is_blocked_key("Shift+Delete") is True

    def test_case_insensitive(self):
        """Key matching is case-insensitive."""
        assert is_blocked_key("ALT+F4") is True
        assert is_blocked_key("alt+f4") is True

    def test_no_false_positives(self):
        """Common safe keys are not blocked."""
        safe_keys = ["ctrl+s", "ctrl+z", "ctrl+a", "f5", "tab", "escape", "space"]
        for key in safe_keys:
            assert is_blocked_key(key) is False, f"{key} should not be blocked"

    def test_blocked_keys_frozenset(self):
        """BLOCKED_KEYS is immutable."""
        assert isinstance(BLOCKED_KEYS, frozenset)
        with pytest.raises(AttributeError):
            BLOCKED_KEYS.add("test")  # type: ignore


# ---------------------------------------------------------------------------
# Sensitive App Detection Tests
# ---------------------------------------------------------------------------

class TestSensitiveApps:
    """TEST-05-02-05 through TEST-05-02-07."""

    def test_outlook_is_sensitive(self):
        """TEST-05-02-05: Outlook is a sensitive app."""
        assert is_sensitive_app("outlook") is True
        assert is_sensitive_app("Microsoft Outlook") is True

    def test_notepad_not_sensitive(self):
        """TEST-05-02-06: Notepad is not a sensitive app."""
        assert is_sensitive_app("notepad") is False

    def test_gmail_confirm_tier(self):
        """TEST-05-02-07: Gmail returns confirm tier."""
        tier = sensitive_app_tier("gmail")
        assert tier == "confirm"

    def test_banking_is_sensitive(self):
        """Banking apps are sensitive."""
        assert is_sensitive_app("Chase Banking") is True

    def test_password_manager_sensitive(self):
        """Password managers are sensitive."""
        assert is_sensitive_app("1Password") is True
        assert is_sensitive_app("Bitwarden") is True
        assert is_sensitive_app("LastPass") is True

    def test_messaging_sensitive(self):
        """Messaging apps are sensitive."""
        assert is_sensitive_app("WhatsApp") is True
        assert is_sensitive_app("Signal") is True
        assert is_sensitive_app("Telegram") is True
        assert is_sensitive_app("Slack") is True

    def test_terminal_sensitive(self):
        """Terminal apps are sensitive (command execution)."""
        assert is_sensitive_app("cmd") is True
        assert is_sensitive_app("PowerShell") is True
        assert is_sensitive_app("bash") is True

    def test_empty_string_not_sensitive(self):
        """Empty string is not sensitive."""
        assert is_sensitive_app("") is False

    def test_sensitive_reason_exists(self):
        """Sensitive apps have reasons."""
        reason = sensitive_app_reason("outlook")
        assert "email" in reason.lower() or "message" in reason.lower()

    def test_non_sensitive_reason_empty(self):
        """Non-sensitive apps have empty reason."""
        reason = sensitive_app_reason("notepad")
        assert reason == ""

    def test_sensitive_rule_has_tier(self):
        """Sensitive app rules have tier set."""
        for rule in SENSITIVE_APPS:
            assert isinstance(rule.tier, SensitiveTier)
            assert rule.reason  # Every rule has a reason

    def test_auto_tier_for_unknown(self):
        """Unknown apps return auto tier."""
        assert sensitive_app_tier("unknown_app") == "auto"
