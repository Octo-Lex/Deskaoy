"""Sensitive app detection — apps that require elevated safety tiers.

Apps like email clients, banking, password managers, and messaging
are classified as sensitive. Actions targeting these apps are
automatically elevated to Confirm tier regardless of action type.

Inspired by Clawd Cursor's CONFIRM_LABEL_PATTERNS + SENSITIVE_APPS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class SensitiveTier(StrEnum):
    """Safety tier elevation for sensitive apps."""
    CONFIRM = "confirm"       # Requires user approval
    AUTO = "auto"             # Normal operation
    BLOCK = "block"           # Completely blocked


@dataclass(frozen=True)
class SensitiveAppRule:
    """Rule for detecting a sensitive app."""
    name: str                          # Human-readable name
    patterns: tuple[str, ...]          # Process name patterns (lowercase)
    tier: SensitiveTier                # What tier to elevate to
    reason: str                        # Why this app is sensitive


# Registry of sensitive apps
SENSITIVE_APPS: tuple[SensitiveAppRule, ...] = (
    # Email clients
    SensitiveAppRule(
        name="Outlook",
        patterns=("outlook", "olk", "winmail", "mail"),
        tier=SensitiveTier.CONFIRM,
        reason="Email client — actions may send messages or modify inbox",
    ),
    SensitiveAppRule(
        name="Gmail",
        patterns=("gmail", "google-mail", "googlemail"),
        tier=SensitiveTier.CONFIRM,
        reason="Email client — actions may send messages",
    ),
    SensitiveAppRule(
        name="Apple Mail",
        patterns=("mail", "apple mail", "com.apple.mail"),
        tier=SensitiveTier.CONFIRM,
        reason="Email client — actions may send messages",
    ),
    # Banking / Finance
    SensitiveAppRule(
        name="Banking",
        patterns=("banking", "bank", "chase", "wellsfargo", "citibank",
                  "hsbc", "paypal", "venmo", "transferwise", "wise"),
        tier=SensitiveTier.CONFIRM,
        reason="Financial application — actions may involve money transfers",
    ),
    # Password managers
    SensitiveAppRule(
        name="1Password",
        patterns=("1password", "onepassword", "op"),
        tier=SensitiveTier.CONFIRM,
        reason="Password manager — may expose credentials",
    ),
    SensitiveAppRule(
        name="Bitwarden",
        patterns=("bitwarden", "bw"),
        tier=SensitiveTier.CONFIRM,
        reason="Password manager — may expose credentials",
    ),
    SensitiveAppRule(
        name="LastPass",
        patterns=("lastpass", "lp"),
        tier=SensitiveTier.CONFIRM,
        reason="Password manager — may expose credentials",
    ),
    SensitiveAppRule(
        name="KeePass",
        patterns=("keepass", "keepassxc"),
        tier=SensitiveTier.CONFIRM,
        reason="Password manager — may expose credentials",
    ),
    # Messaging
    SensitiveAppRule(
        name="WhatsApp",
        patterns=("whatsapp", "wa"),
        tier=SensitiveTier.CONFIRM,
        reason="Messaging app — actions may send messages",
    ),
    SensitiveAppRule(
        name="Signal",
        patterns=("signal",),
        tier=SensitiveTier.CONFIRM,
        reason="Messaging app — actions may send messages",
    ),
    SensitiveAppRule(
        name="Telegram",
        patterns=("telegram", "tdesktop"),
        tier=SensitiveTier.CONFIRM,
        reason="Messaging app — actions may send messages",
    ),
    SensitiveAppRule(
        name="Slack",
        patterns=("slack",),
        tier=SensitiveTier.CONFIRM,
        reason="Messaging app — actions may send messages",
    ),
    SensitiveAppRule(
        name="Discord",
        patterns=("discord",),
        tier=SensitiveTier.CONFIRM,
        reason="Messaging app — actions may send messages",
    ),
    # System tools
    SensitiveAppRule(
        name="Terminal",
        patterns=("cmd", "powershell", "pwsh", "bash", "zsh", "sh",
                  "terminal", "iterm2", "alacritty", "conhost"),
        tier=SensitiveTier.CONFIRM,
        reason="Terminal — keystrokes may execute arbitrary commands",
    ),
)

# Build a flat lookup for fast matching
_PATTERN_MAP: dict[re.Pattern, SensitiveAppRule] = {
    re.compile(rf'\b{re.escape(p)}\b', re.IGNORECASE): rule
    for rule in SENSITIVE_APPS
    for p in rule.patterns
}


def is_sensitive_app(app_name: str) -> bool:
    """Check if an app name matches a sensitive app pattern."""
    return get_sensitive_app_rule(app_name) is not None


def get_sensitive_app_rule(app_name: str) -> SensitiveAppRule | None:
    """Get the sensitive app rule for an app name, or None if not sensitive."""
    if not app_name:
        return None
    for pattern, rule in _PATTERN_MAP.items():
        if pattern.search(app_name):
            return rule
    return None


def sensitive_app_tier(app_name: str) -> str:
    """Get the safety tier for a sensitive app.

    Returns 'auto' if the app is not in the sensitive registry.
    """
    rule = get_sensitive_app_rule(app_name)
    if rule is None:
        return SensitiveTier.AUTO
    return rule.tier


def sensitive_app_reason(app_name: str) -> str:
    """Get the reason an app is sensitive.

    Returns empty string if the app is not sensitive.
    """
    rule = get_sensitive_app_rule(app_name)
    if rule is None:
        return ""
    return rule.reason
