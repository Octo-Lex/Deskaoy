"""Tests for deskaoy.results.types — G11 Error Envelopes."""

from __future__ import annotations

from deskaoy.results.types import (
    ActionError,
    ErrorCategory,
    make_error,
)

# ---------------------------------------------------------------------------
# ActionError — new fields
# ---------------------------------------------------------------------------

class TestActionErrorNewFields:
    """G11: ActionError has code, hint, candidates, matches_n."""

    def test_default_new_fields(self):
        err = ActionError(category=ErrorCategory.SELECTOR_NOT_FOUND, message="not found")
        assert err.code == ""
        assert err.hint == ""
        assert err.candidates == []
        assert err.matches_n == 0

    def test_set_all_fields(self):
        err = ActionError(
            category=ErrorCategory.VALIDATION,
            message="multiple matches",
            code="ambiguous",
            hint="Narrow target",
            candidates=["btn1", "btn2", "btn3"],
            matches_n=3,
        )
        assert err.code == "ambiguous"
        assert err.hint == "Narrow target"
        assert err.candidates == ["btn1", "btn2", "btn3"]
        assert err.matches_n == 3

    def test_to_dict_includes_new_fields(self):
        err = ActionError(
            category=ErrorCategory.TIMEOUT,
            message="timed out",
            code="timeout",
            hint="Retry later",
            candidates=[],
            matches_n=0,
        )
        d = err.to_dict()
        assert d["code"] == "timeout"
        assert d["hint"] == "Retry later"
        assert d["candidates"] == []
        assert d["matches_n"] == 0

    def test_from_dict_backward_compat(self):
        """Old serializations without new fields still deserialize."""
        d = {
            "category": "selector_not_found",
            "message": "gone",
            "selector": None,
            "recoverable": True,
            "retry_hint": None,
        }
        err = ActionError.from_dict(d)
        assert err.code == ""
        assert err.hint == ""
        assert err.candidates == []
        assert err.matches_n == 0

    def test_from_dict_roundtrip(self):
        err = ActionError(
            category=ErrorCategory.SECURITY,
            message="denied",
            code="access_denied",
            hint="blocked",
            candidates=["alt1"],
            matches_n=1,
        )
        restored = ActionError.from_dict(err.to_dict())
        assert restored.code == "access_denied"
        assert restored.hint == "blocked"
        assert restored.candidates == ["alt1"]
        assert restored.matches_n == 1


# ---------------------------------------------------------------------------
# make_error factory
# ---------------------------------------------------------------------------

class TestMakeError:
    """G11: make_error builds from canonical codes."""

    def test_known_code(self):
        err = make_error("not_found")
        assert err.category == ErrorCategory.SELECTOR_NOT_FOUND
        assert err.code == "not_found"
        assert "snapshot" in err.hint.lower()

    def test_stale_ref_code(self):
        err = make_error("stale_ref", message="ref 42 gone")
        assert err.category == ErrorCategory.SELECTOR_NOT_FOUND
        assert err.code == "stale_ref"
        assert err.message == "ref 42 gone"

    def test_ambiguous_with_candidates(self):
        err = make_error(
            "ambiguous",
            message="3 matches",
            candidates=["a", "b", "c"],
            matches_n=3,
        )
        assert err.candidates == ["a", "b", "c"]
        assert err.matches_n == 3

    def test_unknown_code(self):
        err = make_error("custom_error")
        assert err.category == ErrorCategory.UNKNOWN
        assert err.code == "custom_error"

    def test_overrides(self):
        err = make_error("timeout", recoverable=False, retry_hint="wait 5s")
        assert err.recoverable is False
        assert err.retry_hint == "wait 5s"

    def test_all_codes(self):
        """Every code in the catalog produces a valid ActionError."""
        from deskaoy.results.types import ERROR_CODES
        for code in ERROR_CODES:
            err = make_error(code)
            assert err.code == code
            assert err.category != ErrorCategory.UNKNOWN or code == "unknown"
