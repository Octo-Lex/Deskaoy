"""Key blocklist — dangerous keyboard shortcuts that must never be injected.

Prevents the agent from sending system-critical key combinations that
could disrupt the user's session, damage data, or bypass security.

The blocklist is a frozenset of normalised key-combo strings.  Every
combo is stored in **sorted order** (e.g. ``alt+f4``, ``alt+ctrl+delete``)
so that lookups are order-independent — ``ctrl+alt+f4`` and ``alt+ctrl+f4``
both match.
"""

from __future__ import annotations

# ── Normalisation helpers ──────────────────────────────────────────────

_SEPARATOR = "+"

# Canonical aliases — multiple spellings map to the same canonical name.
_KEY_ALIASES: dict[str, str] = {
    "del": "delete",
    "esc": "escape",
    "cmd": "meta",
    "win": "meta",
    "super": "meta",
    "return": "enter",
    "opt": "option",
}


def _normalise_combo(combo: str) -> str:
    """Lower-case and sort the parts of a ``+``-separated key combo.

    >>> _normalise_combo("Ctrl+Alt+Del")
    'alt+ctrl+del'
    >>> _normalise_combo("f4+alt")
    'alt+f4'
    """
    parts = [_KEY_ALIASES.get(p.strip().lower(), p.strip().lower())
              for p in combo.split(_SEPARATOR)]
    return _SEPARATOR.join(sorted(parts))


# ── Blocked keys registry ─────────────────────────────────────────────

# All entries are stored in **pre-normalised** (sorted, lower-cased) form
# so that ``in BLOCKED_KEYS`` is a simple set-membership test.

_BLOCKED_RAW: dict[str, str] = {
    # Window / session control
    "Alt+F4":             "Closing windows — may lose unsaved work",
    "Ctrl+W":             "Closing tabs/windows",
    "Ctrl+Alt+Delete":    "System interrupt — reserved by OS",
    "Cmd+Q":              "macOS quit — may lose unsaved work",
    # Permanent delete
    "Shift+Delete":       "Permanent delete — bypasses Recycle Bin",
    # System-level shortcuts
    "Ctrl+Shift+Esc":     "Opens Task Manager — system diagnostic tool",
    "Win+L":              "Locks the workstation",
    "Win+D":              "Shows desktop — hides all windows",
    "Ctrl+Alt+End":       "Remote Desktop Ctrl+Alt+Del equivalent",
    "Alt+Tab":            "Switches active window — disorienting",
    "Win+Tab":            "Task View — disorienting",
    "Alt+Enter":          "Toggles fullscreen — may confuse agent",
    # Security-critical
    "Ctrl+Shift+Delete":  "Browser clear-data dialog",
    "Ctrl+Alt+F4":        "Force-kill on some Linux DEs",
}

BLOCKED_KEYS: frozenset[str] = frozenset(
    _normalise_combo(k) for k in _BLOCKED_RAW
)

# Map normalised combo → human-readable reason (for block_reason())
_REASON_MAP: dict[str, str] = {
    _normalise_combo(k): v for k, v in _BLOCKED_RAW.items()
}


# ── Public API ────────────────────────────────────────────────────────

def is_blocked_key(combo: str) -> bool:
    """Return *True* if the key combo is on the blocklist.

    Matching is **order-independent** and **case-insensitive**:
    ``"Ctrl+Alt+Delete"`` and ``"alt+ctrl+delete"`` both match.

    >>> is_blocked_key("Alt+F4")
    True
    >>> is_blocked_key("a")
    False
    """
    return _normalise_combo(combo) in BLOCKED_KEYS


def block_reason(combo: str) -> str:
    """Return the human-readable reason a combo is blocked.

    If the combo is not on the blocklist, returns a generic message.
    """
    norm = _normalise_combo(combo)
    if norm in _REASON_MAP:
        return _REASON_MAP[norm]
    return "Key combo blocked by safety policy"
