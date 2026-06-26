"""Security audit tests — BATCH-35, TASK-02.

Tests cover:
  1. Credential leak scan (source grep patterns)
  2. CLI input validation
  3. Snapshot path traversal protection
  4. Rate limiting on transport endpoints
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =================================================================
# 1. Credential Leak Scan
# =================================================================

# Patterns that should NOT appear in source code with literal values
_CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("hardcoded api_key", re.compile(r'''api_key\s*=\s*['"][^'"]{8,}['"]''', re.IGNORECASE)),
    ("hardcoded secret", re.compile(r'''secret\s*=\s*['"][^'"]{8,}['"]''', re.IGNORECASE)),
    ("hardcoded password", re.compile(r'''password\s*=\s*['"][^'"]{3,}['"]''', re.IGNORECASE)),
    ("hardcoded token", re.compile(r'''token\s*=\s*['"][a-zA-Z0-9]{20,}['"]''', re.IGNORECASE)),
    ("hardcoded bearer", re.compile(r'''Bearer\s+[a-zA-Z0-9._-]{20,}''', re.IGNORECASE)),
    # Allow patterns in tests, comments, defaults, and env-var lookups
]

_EXEMPT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'#', re.IGNORECASE),           # comment lines
    re.compile(r'"""', re.IGNORECASE),          # docstrings
    re.compile(r"'''", re.IGNORECASE),
    re.compile(r'test_', re.IGNORECASE),        # test files
    re.compile(r'env|environ|getenv', re.IGNORECASE),  # env lookups
    re.compile(r'DEFAULT_|_DEFAULT|_EXAMPLE', re.IGNORECASE),  # defaults/examples
    re.compile(r'BLOCKED_KEYS|SENSITIVE_APPS', re.IGNORECASE),  # blocklist constants
]

_SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent / "src"


def _scan_source_for_leaks() -> list[tuple[str, int, str]]:
    """Scan all Python source for credential leak patterns."""
    findings = []
    for py_file in _SOURCE_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_SOURCE_ROOT.parent)
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            # Skip comments and docstrings
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Skip security/types.py enum definitions (not real credentials)
            if 'security' + ('/') + 'types.py' in str(rel).replace('\\', '/'):
                continue
            for name, pattern in _CREDENTIAL_PATTERNS:
                if pattern.search(line):
                    findings.append((str(rel), line_no, f"{name}: {stripped[:120]}"))
    return findings


class TestCredentialLeakScan:
    """Verify no hardcoded credentials in source code."""

    def test_no_hardcoded_api_keys(self):
        """Source should not contain hardcoded api_key values."""
        findings = _scan_source_for_leaks()
        # Filter to just api_key findings
        api_leaks = [f for f in findings if "api_key" in f[2]]
        assert len(api_leaks) == 0, (
            f"Found {len(api_leaks)} potential hardcoded api_key(s):\n"
            + "\n".join(f"  {f[0]}:{f[1]} — {f[2]}" for f in api_leaks)
        )

    def test_no_hardcoded_passwords(self):
        """Source should not contain hardcoded password values."""
        findings = _scan_source_for_leaks()
        pw_leaks = [f for f in findings if "password" in f[2]]
        assert len(pw_leaks) == 0, (
            f"Found {len(pw_leaks)} potential hardcoded password(s):\n"
            + "\n".join(f"  {f[0]}:{f[1]} — {f[2]}" for f in pw_leaks)
        )


# =================================================================
# 2. CLI Input Validation
# =================================================================

class TestCLIInputValidation:
    """Verify CLI inputs are sanitized."""

    def test_cli_instruction_rejected_when_empty(self):
        """execute automate with no instruction must fail.

        Since instruction is now optional (nargs='?') to support single-action
        capabilities like `--capability click --target X`, the empty-instruction
        check moved from argparse to _build_goal, which raises SystemExit for
        automate without an instruction.
        """
        from deskaoy.cli.main import _build_parser, _build_goal

        parser = _build_parser()
        # Parsing succeeds (instruction is optional)
        args = parser.parse_args(["execute"])
        # But _build_goal must reject automate without instruction
        with pytest.raises(SystemExit):
            _build_goal(args)

    def test_cli_timeout_accepts_positive_int(self):
        """Timeout must be a positive integer."""
        from deskaoy.cli.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--timeout", "30", "version"])
        assert args.timeout == 30

    def test_cli_port_accepts_valid_range(self):
        """Port must be an integer."""
        from deskaoy.cli.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["serve", "--port", "8080"])
        assert args.port == 8080


# =================================================================
# 3. Snapshot Path Traversal Protection
# =================================================================

class TestSnapshotPathTraversal:
    """Snapshot paths must not allow directory traversal."""

    def test_snapshot_store_rejects_traversal_id(self):
        """Snapshot IDs with '..' should not traverse out of storage."""
        from deskaoy.cascade.snapshot_store import SnapshotStore

        store = SnapshotStore()
        # Attempt to get a snapshot with path traversal
        result = asyncio_run(store.get("../../../etc/passwd"))
        # Should return None, not raise or return file data
        assert result is None

    def test_snapshot_store_rejects_absolute_path_id(self):
        """Snapshot IDs with absolute paths should not escape storage."""
        from deskaoy.cascade.snapshot_store import SnapshotStore

        store = SnapshotStore()
        result = asyncio_run(store.get("/etc/passwd"))
        assert result is None


# =================================================================
# 4. Rate Limiting on Transport
# =================================================================

class TestRateLimiting:
    """Rate governor blocks excessive actions."""

    def test_rate_governor_allows_normal_load(self):
        """Actions within limits are allowed."""
        from deskaoy.safety.rate_governor import ActionRateGovernor

        gov = ActionRateGovernor()
        assert gov.check("click") is True

    def test_rate_governor_blocks_excess(self):
        """Actions exceeding limits are blocked."""
        from deskaoy.safety.rate_governor import ActionRateGovernor, RateLimit

        # Very tight limit for testing
        limits = {"click": RateLimit(max_actions=3, window_seconds=1.0, cooldown_seconds=0.5)}
        gov = ActionRateGovernor(limits=limits)

        for _ in range(3):
            assert gov.check("click") is True
            gov.record("click")

        # 4th click should be blocked
        assert gov.check("click") is False

    def test_rate_governor_resets(self):
        """Reset clears limits."""
        from deskaoy.safety.rate_governor import ActionRateGovernor, RateLimit

        limits = {"click": RateLimit(max_actions=1, window_seconds=10.0, cooldown_seconds=5.0)}
        gov = ActionRateGovernor(limits=limits)
        gov.record("click")
        assert gov.check("click") is False

        gov.reset("click")
        assert gov.check("click") is True

    def test_rate_governor_stats(self):
        """Stats endpoint returns structured data."""
        from deskaoy.safety.rate_governor import ActionRateGovernor

        gov = ActionRateGovernor()
        gov.record("click")
        stats = gov.stats
        assert "click" in stats
        assert stats["click"]["count"] == 1


# =================================================================
# Helpers
# =================================================================

def asyncio_run(coro):
    """Run an async coroutine synchronously (for non-async test methods)."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # If already in an async context, use nest_asyncio-style fallback
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)
