"""HB-03 enforcement — OTel SDK must not be imported at deskaoy level.

TEST-43-01-11.
"""

from __future__ import annotations

import sys


def test_otel_sdk_not_imported_at_deskaoy_level():
    """HB-03: opentelemetry SDK must not be in sys.modules after deskaoy import."""
    # Remove any pre-existing OTel SDK modules from the import cache
    # (other tests in this session may have imported them).
    for key in list(sys.modules.keys()):
        if key.startswith("opentelemetry.sdk"):
            del sys.modules[key]

    import deskaoy  # noqa: F401

    assert "opentelemetry.sdk" not in sys.modules, (
        "HB-03 violation: opentelemetry.sdk was imported at deskaoy module level"
    )
