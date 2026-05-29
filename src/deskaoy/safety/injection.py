"""PromptInjectionDetector — regex + Unicode injection scanning.

Ported from SUPER-BROWSER security/injection.py pattern.
Scans text for prompt injection patterns, role manipulation,
data exfiltration attempts, jailbreaks, and Unicode obfuscation.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum


class InjectionPattern(StrEnum):
    SYSTEM_OVERRIDE = "system_override"
    ROLE_MANIPULATION = "role_manipulation"
    DATA_EXFILTRATION = "data_exfiltration"
    JAILBREAK = "jailbreak"
    INSTRUCTION_INJECTION = "instruction_injection"
    UNICODE_OBFUSCATION = "unicode_obfuscation"
    CONTEXT_POISONING = "context_poisoning"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class InjectionMatch:
    pattern: InjectionPattern
    pattern_name: str
    matched_text: str
    position: int
    risk_level: RiskLevel


@dataclass
class InjectionVerdict:
    blocked: bool
    matches: list[InjectionMatch] = field(default_factory=list)
    sanitized_text: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    scan_time_ms: float = 0.0

    @property
    def match_count(self) -> int:
        return len(self.matches)


# --- Built-in patterns ---
_BUILTIN_PATTERNS: list[tuple[InjectionPattern, str, str, RiskLevel]] = [
    (InjectionPattern.SYSTEM_OVERRIDE, "system_override_1",
     r"ignore\s+(all\s+)?previous\s+instructions", RiskLevel.CRITICAL),
    (InjectionPattern.SYSTEM_OVERRIDE, "system_override_2",
     r"disregard\s+(all\s+)?(above|previous)", RiskLevel.CRITICAL),
    (InjectionPattern.SYSTEM_OVERRIDE, "system_override_3",
     r"forget\s+(all\s+)?(your\s+)?(previous\s+)?instructions", RiskLevel.CRITICAL),
    (InjectionPattern.ROLE_MANIPULATION, "role_manipulation_1",
     r"you\s+are\s+now\s+", RiskLevel.HIGH),
    (InjectionPattern.ROLE_MANIPULATION, "role_manipulation_2",
     r"new\s+instruction", RiskLevel.HIGH),
    (InjectionPattern.ROLE_MANIPULATION, "role_manipulation_3",
     r"act\s+as\s+(if\s+)?you\s+(are|were)\s+", RiskLevel.HIGH),
    (InjectionPattern.DATA_EXFILTRATION, "data_exfiltration_1",
     r"send\s+(your\s+)?(prompt|system\s+message|instructions)", RiskLevel.CRITICAL),
    (InjectionPattern.DATA_EXFILTRATION, "data_exfiltration_2",
     r"reveal\s+your\s+(system|hidden|internal)\s+", RiskLevel.HIGH),
    (InjectionPattern.DATA_EXFILTRATION, "data_exfiltration_3",
     r"repeat\s+(back\s+)?(everything|your\s+instructions)", RiskLevel.HIGH),
    (InjectionPattern.JAILBREAK, "jailbreak_1",
     r"\bDAN\b", RiskLevel.CRITICAL),
    (InjectionPattern.JAILBREAK, "jailbreak_2",
     r"do\s+anything\s+now", RiskLevel.CRITICAL),
    (InjectionPattern.JAILBREAK, "jailbreak_3",
     r"jailbreak", RiskLevel.HIGH),
    (InjectionPattern.INSTRUCTION_INJECTION, "instruction_injection_1",
     r"hidden\s+instruction", RiskLevel.MEDIUM),
    (InjectionPattern.INSTRUCTION_INJECTION, "instruction_injection_2",
     r"execute\s+this", RiskLevel.MEDIUM),
    (InjectionPattern.INSTRUCTION_INJECTION, "instruction_injection_3",
     r"system\s*:\s*", RiskLevel.HIGH),
    (InjectionPattern.CONTEXT_POISONING, "context_poisoning_1",
     r"adversarial\s+context", RiskLevel.MEDIUM),
    (InjectionPattern.CONTEXT_POISONING, "context_poisoning_2",
     r"injected\s+(content|payload|text)", RiskLevel.MEDIUM),
]

# Unicode ranges to flag
_UNICODE_RANGES: list[tuple[int, int, str]] = [
    (0x200B, 0x200B, "zero-width space"),
    (0x200C, 0x200C, "zero-width non-joiner"),
    (0x200D, 0x200D, "zero-width joiner"),
    (0x202A, 0x202E, "bidirectional override"),
    (0x00AD, 0x00AD, "soft hyphen"),
    (0x2060, 0x2060, "word joiner"),
    (0xFEFF, 0xFEFF, "BOM/zero-width no-break"),
]

# Cyrillic homoglyphs
_HOMOGLYPHS: dict[int, str] = {
    0x0430: "Cyrillic a",
    0x0435: "Cyrillic e",
    0x043E: "Cyrillic o",
    0x0440: "Cyrillic p",
    0x0441: "Cyrillic c",
    0x0456: "Cyrillic i",
}


class PromptInjectionDetector:
    """Scans text for prompt injection patterns."""

    def __init__(self, *, enable_unicode: bool = True) -> None:
        self._enable_unicode = enable_unicode
        self._patterns: list[tuple[InjectionPattern, str, re.Pattern, RiskLevel]] = [
            (ptype, name, re.compile(regex, re.IGNORECASE), risk)
            for ptype, name, regex, risk in _BUILTIN_PATTERNS
        ]

    def scan(self, text: str) -> InjectionVerdict:
        """Scan text for injection patterns.

        Returns an InjectionVerdict with blocked=True if HIGH/CRITICAL risk found.
        """
        start = time.perf_counter()
        matches = self._scan_regex(text)

        if self._enable_unicode:
            matches.extend(self._scan_unicode(text))

        matches.sort(key=lambda m: m.position)

        # Determine max risk
        max_risk = RiskLevel.LOW
        for m in matches:
            if m.risk_level == RiskLevel.CRITICAL:
                max_risk = RiskLevel.CRITICAL
                break
            if m.risk_level == RiskLevel.HIGH:
                max_risk = RiskLevel.HIGH

        blocked = max_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        sanitized = self._sanitize(text, matches) if matches else text
        elapsed = (time.perf_counter() - start) * 1000

        return InjectionVerdict(
            blocked=blocked,
            matches=matches,
            sanitized_text=sanitized,
            risk_level=max_risk,
            scan_time_ms=elapsed,
        )

    @property
    def pattern_count(self) -> int:
        return len(self._patterns)

    # -- Internals --

    def _scan_regex(self, text: str) -> list[InjectionMatch]:
        matches: list[InjectionMatch] = []
        for ptype, name, compiled, risk in self._patterns:
            for m in compiled.finditer(text):
                matches.append(InjectionMatch(
                    pattern=ptype,
                    pattern_name=name,
                    matched_text=m.group(),
                    position=m.start(),
                    risk_level=risk,
                ))
        return matches

    def _scan_unicode(self, text: str) -> list[InjectionMatch]:
        matches: list[InjectionMatch] = []
        for i, ch in enumerate(text):
            cp = ord(ch)
            for lo, hi, desc in _UNICODE_RANGES:
                if lo <= cp <= hi:
                    matches.append(InjectionMatch(
                        pattern=InjectionPattern.UNICODE_OBFUSCATION,
                        pattern_name=desc,
                        matched_text=ch,
                        position=i,
                        risk_level=RiskLevel.HIGH,
                    ))
                    break
            else:
                glyph = _HOMOGLYPHS.get(cp)
                if glyph is not None:
                    matches.append(InjectionMatch(
                        pattern=InjectionPattern.UNICODE_OBFUSCATION,
                        pattern_name=glyph,
                        matched_text=ch,
                        position=i,
                        risk_level=RiskLevel.MEDIUM,
                    ))
        return matches

    def _sanitize(self, text: str, matches: list[InjectionMatch]) -> str:
        result = list(text)
        offset = 0
        for m in sorted(matches, key=lambda x: x.position):
            start = m.position + offset
            end = start + len(m.matched_text)
            replacement = "[BLOCKED]"
            result[start:end] = list(replacement)
            offset += len(replacement) - len(m.matched_text)
        return "".join(result)
