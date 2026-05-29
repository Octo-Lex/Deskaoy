"""ActionValidator — validates action parameters before dispatch.

Adopted from OSWorld's formal action space pattern. Each action declares
typed parameter specs with ranges, allowed values, and length limits.
Validation runs *before* the adapter method is called, preventing
out-of-bounds coordinates, invalid button names, oversized strings, etc.

No external deps — pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# URL validation (simple, no external deps)
# ---------------------------------------------------------------------------

_URL_PATTERN = re.compile(
    r"^https?://"            # scheme
    r"(?:\S+)"               # host
    r"(?::\d+)?"             # optional port
    r"(?:/\S*)?$",           # optional path
    re.IGNORECASE,
)


def _looks_like_url(value: str) -> bool:
    """Heuristic URL check — not strict RFC, just sanity."""
    return bool(_URL_PATTERN.match(value))


# ---------------------------------------------------------------------------
# Known keyboard keys (pyautogui / pydirectinput compatible)
# ---------------------------------------------------------------------------

_KEYBOARD_KEYS: frozenset[str] = frozenset({
    # Single characters
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    # Special keys
    "enter", "return", "tab", "space", "backspace", "delete", "insert",
    "escape", "esc",
    # Navigation
    "up", "down", "left", "right", "home", "end",
    "pageup", "pagedown", "page_up", "page_down",
    # Function keys
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    # Modifiers
    "shift", "ctrl", "alt", "meta", "command", "win", "windows",
    # Lock keys
    "capslock", "numlock", "scrolllock",
    "caps_lock", "num_lock", "scroll_lock",
    # Other
    "printscreen", "print_screen", "prtsc", "prtscr",
    "pause", "break", "contextmenu", "apps",
    # Numpad
    "numpad0", "numpad1", "numpad2", "numpad3", "numpad4",
    "numpad5", "numpad6", "numpad7", "numpad8", "numpad9",
    "multiply", "add", "subtract", "divide", "decimal",
    "separator", "clear",
    # Symbols
    "exclamation", "at", "hash", "dollar", "percent",
    "caret", "ampersand", "asterisk", "parenleft", "parenright",
    "minus", "underscore", "plus", "equals",
    "bracketleft", "bracketright", "braceleft", "braceright",
    "semicolon", "colon", "quote", "doublequote",
    "backslash", "pipe", "comma", "period", "slash", "question",
    "grave", "tilde",
})


def _is_valid_key(key: str) -> bool:
    """Check if a key name is recognized."""
    return key.lower() in _KEYBOARD_KEYS or len(key) == 1


# ---------------------------------------------------------------------------
# Parameter specs
# ---------------------------------------------------------------------------

# Max screen resolution we support (8K)
_MAX_X = 7680
_MAX_Y = 4320


@dataclass(frozen=True)
class ParameterSpec:
    """Declares valid ranges for an action parameter."""

    name: str
    type: type = str
    required: bool = True
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: list[Any] | None = None
    max_length: int | None = None

    def validate(self, value: Any) -> list[str]:
        """Validate *value* against this spec. Returns list of error messages."""
        errors: list[str] = []

        # Type check
        if not isinstance(value, self.type):
            # Allow int→float coercion
            if self.type is float and isinstance(value, int):
                pass
            else:
                errors.append(
                    f"Parameter '{self.name}' must be {self.type.__name__}, "
                    f"got {type(value).__name__}"
                )
                return errors

        # Numeric range
        if self.min_value is not None or self.max_value is not None:
            num = float(value)
            if self.min_value is not None and num < self.min_value:
                errors.append(
                    f"Parameter '{self.name}' value {num} is below minimum {self.min_value}"
                )
            if self.max_value is not None and num > self.max_value:
                errors.append(
                    f"Parameter '{self.name}' value {num} exceeds maximum {self.max_value}"
                )

        # Allowed values
        if self.allowed_values is not None and value not in self.allowed_values:
            errors.append(
                f"Parameter '{self.name}' value {value!r} not in "
                f"allowed values: {self.allowed_values}"
            )

        # String length
        if self.max_length is not None and isinstance(value, str):
            if len(value) > self.max_length:
                errors.append(
                    f"Parameter '{self.name}' length {len(value)} exceeds "
                    f"maximum {self.max_length}"
                )

        return errors


# ---------------------------------------------------------------------------
# Action specs — one per CAPABILITIES entry
# ---------------------------------------------------------------------------

ACTION_SPECS: dict[str, list[ParameterSpec]] = {
    "click": [
        ParameterSpec("target", str, required=False, max_length=500),
        ParameterSpec("x", (float, int), required=False, min_value=0, max_value=_MAX_X),
        ParameterSpec("y", (float, int), required=False, min_value=0, max_value=_MAX_Y),
        ParameterSpec("button", str, required=False,
                      allowed_values=["left", "right", "middle"]),
        ParameterSpec("num_clicks", (int, float), required=False,
                      min_value=1, max_value=3),
    ],
    "fill": [
        ParameterSpec("target", str, required=True, max_length=500),
        ParameterSpec("value", str, required=True, max_length=10000),
    ],
    "type_text": [
        ParameterSpec("target", str, required=True, max_length=500),
        ParameterSpec("text", str, required=True, max_length=50000),
    ],
    "key_press": [
        ParameterSpec("key", str, required=True, max_length=50),
    ],
    "scroll": [
        ParameterSpec("direction", str, required=True,
                      allowed_values=["up", "down", "left", "right"]),
        ParameterSpec("amount", (int, float), required=False,
                      min_value=0, max_value=10000),
    ],
    "screenshot": [],
    "snapshot": [],
    "navigate": [
        ParameterSpec("url", str, required=True, max_length=2048),
    ],
    "evaluate": [
        ParameterSpec("expression", str, required=True, max_length=50000),
    ],
    # automate + orchestrate don't have parameter specs (free-form)
    "automate": [],
    "orchestrate": [],
}


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    """A single validation problem."""
    param: str
    message: str
    severity: str = "error"  # "error" | "warning"


@dataclass
class ActionValidationResult:
    """Result of validating action parameters."""
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    sanitized_params: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_action(action: str, params: dict) -> ActionValidationResult:
    """Validate action parameters against specs.

    For actions without specs (e.g. unknown actions), returns valid=True
    with the original params passed through — no validation is better than
    false-blocking.

    Args:
        action: Capability name (e.g. "click", "fill").
        params: Dict of parameters to validate.

    Returns:
        ActionValidationResult with:
        - valid: True if no errors
        - issues: list of ValidationIssue
        - sanitized_params: params with types coerced and defaults applied
    """
    specs = ACTION_SPECS.get(action)

    # No spec → pass through (don't block unknown actions)
    if specs is None:
        return ActionValidationResult(valid=True, sanitized_params=dict(params))

    if not specs:
        # Action has an empty spec list (screenshot, snapshot) → always valid
        return ActionValidationResult(valid=True, sanitized_params=dict(params))

    issues: list[ValidationIssue] = []
    sanitized: dict[str, Any] = {}

    for spec in specs:
        value = params.get(spec.name)

        # Required check
        if value is None:
            if spec.required:
                issues.append(ValidationIssue(
                    param=spec.name,
                    message=f"Required parameter '{spec.name}' is missing",
                    severity="error",
                ))
            continue

        # Coerce types
        coerced = _coerce(value, spec)
        if coerced is not None:
            sanitized[spec.name] = coerced
        else:
            sanitized[spec.name] = value

        # Validate
        spec_errors = spec.validate(coerced if coerced is not None else value)
        for msg in spec_errors:
            issues.append(ValidationIssue(
                param=spec.name,
                message=msg,
                severity="error",
            ))

    # Extra keys validation (warn only)
    known = {s.name for s in specs}
    for key in params:
        if key not in known:
            issues.append(ValidationIssue(
                param=key,
                message=f"Unknown parameter '{key}' for action '{action}'",
                severity="warning",
            ))
            sanitized[key] = params[key]

    # Copy sanitized unknown params
    valid = len([i for i in issues if i.severity == "error"]) == 0
    return ActionValidationResult(
        valid=valid,
        issues=issues,
        sanitized_params=sanitized,
    )


def _coerce(value: Any, spec: ParameterSpec) -> Any:
    """Attempt to coerce *value* to the expected type."""
    if isinstance(value, spec.type):
        return value

    # int → float
    if spec.type is float and isinstance(value, int):
        return float(value)

    # str → numeric
    if isinstance(value, str):
        if spec.type in (int, float) or (isinstance(spec.type, tuple) and int in spec.type):
            try:
                return int(value)
            except (ValueError, TypeError):
                pass
            try:
                return float(value)
            except (ValueError, TypeError):
                pass

    return value
