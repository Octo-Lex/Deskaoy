"""Fact extractor — auto-extract facts from actions and instructions.

Two extraction modes:

1. **Automatic**: scans ``ActionResult`` after execution for extractable info
   (e.g. ``fill("email", "alice@work.com")`` → Fact about user's email).
2. **Instruction-based**: scans user instruction text for explicit self-disclosures
   (e.g. ``"my name is Alice"`` → Fact about user's name).

No external deps — pure pattern matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from deskaoy.memory.facts import Fact

# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------


@dataclass
class ExtractionPattern:
    """Pattern for extracting facts from action results."""

    category: str
    subject_template: str  # literal or "{target}"
    content_template: str  # "User's email is {value}" or literal
    action: str = ""  # match specific action, empty = any
    target_pattern: str = ""  # regex for target name match


# ── Action-based patterns ─────────────────────────────────────────────────

_ACTION_PATTERNS: list[ExtractionPattern] = [
    # Email
    ExtractionPattern(
        category="user_info",
        subject_template="email",
        content_template="User's email is {value}",
        action="fill",
        target_pattern=r"(?i)(email|e-mail|mail)",
    ),
    # Phone
    ExtractionPattern(
        category="user_info",
        subject_template="phone",
        content_template="User's phone is {value}",
        action="fill",
        target_pattern=r"(?i)(phone|tel|mobile|cell)",
    ),
    # Name
    ExtractionPattern(
        category="user_info",
        subject_template="name",
        content_template="User's name is {value}",
        action="fill",
        target_pattern=r"(?i)(name|full.?name|first.?name|last.?name)",
    ),
    # Address
    ExtractionPattern(
        category="user_info",
        subject_template="address",
        content_template="User's address is {value}",
        action="fill",
        target_pattern=r"(?i)(address|street|city|zip|postal)",
    ),
    # Company
    ExtractionPattern(
        category="work",
        subject_template="company",
        content_template="User works at {value}",
        action="fill",
        target_pattern=r"(?i)(company|org|organization|employer)",
    ),
    # URL / website navigation
    ExtractionPattern(
        category="projects",
        subject_template="frequent_url",
        content_template="User visits {value}",
        action="navigate",
    ),
]

# ── Instruction-based patterns ─────────────────────────────────────────────

_INSTRUCTION_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # (category, subject, compiled regex with named group "value")
    ("user_info", "name",
     re.compile(r"(?i)(?:my name is|I'm called|i am)\s+(?P<value>\S+)")),
    ("work", "company",
     re.compile(r"(?i)(?:I work at|i'm at|my company is)\s+(?P<value>.+?)(?:\.|$)")),
    ("preferences", "preference",
     re.compile(r"(?i)(?:I prefer|i like|i love)\s+(?P<value>.+?)(?:\.|$)")),
    ("preferences", "dislike",
     re.compile(r"(?i)(?:I don't like|i hate|i dislike)\s+(?P<value>.+?)(?:\.|$)")),
    ("projects", "current_project",
     re.compile(r"(?i)(?:my project is|i'm working on)\s+(?P<value>.+?)(?:\.|$)")),
]

# ── Skip patterns (don't extract junk) ────────────────────────────────────

_SKIP_VALUES = {
    "", "test", "test@test.com", "password", "123456", "asdf",
    "dummy", "placeholder", "example", "sample", "n/a", "na",
    "none", "null", "undefined", "todo", "tbd",
}


# ---------------------------------------------------------------------------
# FactExtractor
# ---------------------------------------------------------------------------


class FactExtractor:
    """Extract facts from action results and conversation context.

    Two modes:

    1. Automatic: scans ``ActionResult`` after execution for extractable info
    2. Explicit: parses user instruction text for self-disclosures
    """

    def __init__(self, patterns: list[ExtractionPattern] | None = None) -> None:
        self._patterns = patterns or _ACTION_PATTERNS

    def extract_from_result(
        self,
        action: str,
        target: str,
        result_value: str = "",
        params: dict | None = None,
    ) -> list[Fact]:
        """Auto-extract facts from an action result.

        Returns facts that match known extraction patterns.
        """
        facts: list[Fact] = []
        params = params or {}

        for pattern in self._patterns:
            # Filter by action
            if pattern.action and pattern.action != action:
                continue

            # Filter by target pattern
            if pattern.target_pattern and not re.search(pattern.target_pattern, target):
                continue

            # Get value
            value = result_value or params.get("value", "")
            if not value or value.lower().strip() in _SKIP_VALUES:
                continue

            # Build fact
            subject = pattern.subject_template.replace("{target}", target)
            content = pattern.content_template.replace("{value}", value)

            facts.append(Fact(
                category=pattern.category,
                subject=subject,
                content=content,
                source="action_observation",
                confidence=0.8,
            ))

        return facts

    def extract_from_instruction(
        self,
        instruction: str,
    ) -> list[Fact]:
        """Extract explicit facts from user instruction text.

        Matches patterns like "my name is X", "I work at X", etc.
        """
        facts: list[Fact] = []

        for category, subject, regex in _INSTRUCTION_PATTERNS:
            m = regex.search(instruction)
            if m:
                value = m.group("value").strip()
                if value.lower() not in _SKIP_VALUES:
                    facts.append(Fact(
                        category=category,
                        subject=subject,
                        content=value,
                        source="conversation",
                        confidence=0.9,
                    ))

        return facts
