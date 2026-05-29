"""Tests for deskaoy.utils.shape — G7 Shape Inference."""

from __future__ import annotations

import pytest

from deskaoy.utils.shape import infer_shape


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

class TestPrimitives:

    def test_none(self):
        assert infer_shape(None) == {"$": "null"}

    def test_bool(self):
        assert infer_shape(True) == {"$": "boolean"}

    def test_int(self):
        assert infer_shape(42) == {"$": "number"}

    def test_float(self):
        assert infer_shape(3.14) == {"$": "number"}

    def test_string(self):
        assert infer_shape("hello") == {"$": "string(len=5)"}

    def test_long_string(self):
        s = "x" * 200
        result = infer_shape(s)
        assert result["$"] == "string"  # omit len for long strings


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------

class TestObjects:

    def test_flat_object(self):
        result = infer_shape({"name": "Alice", "age": 30})
        assert result == {
            "$": "object(2)",
            "$.name": "string(len=5)",
            "$.age": "number",
        }

    def test_nested_object(self):
        result = infer_shape({"user": {"name": "Bob"}})
        assert result == {
            "$": "object(1)",
            "$.user": "object(1)",
            "$.user.name": "string(len=3)",
        }

    def test_empty_object(self):
        result = infer_shape({})
        assert result == {"$": "object(0)"}


# ---------------------------------------------------------------------------
# Arrays
# ---------------------------------------------------------------------------

class TestArrays:

    def test_empty_array(self):
        assert infer_shape([]) == {"$": "array(0)"}

    def test_short_array(self):
        result = infer_shape([1, 2, 3])
        assert result == {
            "$": "array(3)",
            "$[0]": "number",
            "$[1]": "number",
            "$[2]": "number",
        }

    def test_long_array_samples_first_and_last(self):
        """Arrays >5 elements only expand [0] and [N-1]."""
        items = [{"title": f"item{i}"} for i in range(10)]
        result = infer_shape(items)
        assert "$" in result
        assert result["$"] == "array(10)"
        assert "$[0].title" in result
        assert "$[9].title" in result
        # Middle items should NOT be expanded
        assert "$[5].title" not in result

    def test_mixed_array(self):
        result = infer_shape([1, "hello", True])
        assert "$" in result
        assert result["$"] == "array(3)"
        # Short array: all indices expanded
        assert "$[0]" in result
        assert "$[1]" in result
        assert "$[2]" in result


# ---------------------------------------------------------------------------
# Depth limit
# ---------------------------------------------------------------------------

class TestDepthLimit:

    def test_max_depth_stops_expansion(self):
        data = {"a": {"b": {"c": {"d": "deep"}}}}
        result = infer_shape(data, max_depth=2)
        assert "$.a" in result
        assert "$.a.b" in result
        # Should not expand beyond depth 2
        assert "$.a.b.c" not in result


# ---------------------------------------------------------------------------
# Byte budget
# ---------------------------------------------------------------------------

class TestByteBudget:

    def test_truncation_on_budget(self):
        # Create a huge dict that will exceed budget
        data = {f"key_{i}": f"value_{i}" * 50 for i in range(100)}
        result = infer_shape(data, max_bytes=200)
        assert "(truncated)" in result

    def test_no_truncation_under_budget(self):
        data = {"a": 1, "b": "hello"}
        result = infer_shape(data, max_bytes=10000)
        assert "(truncated)" not in result

    def test_zero_budget_means_unlimited(self):
        """max_bytes=0 disables budget check."""
        data = {"a": 1, "b": 2, "c": 3}
        result = infer_shape(data, max_bytes=0)
        assert "(truncated)" not in result
        assert len(result) >= 4


# ---------------------------------------------------------------------------
# Complex structures
# ---------------------------------------------------------------------------

class TestComplex:

    def test_typical_api_response(self):
        data = {
            "items": [{"title": "Hello", "score": 42}],
            "pagination": {"next": "abc", "total": 100},
        }
        result = infer_shape(data)
        assert result["$"] == "object(2)"
        assert result["$.items"] == "array(1)"
        assert result["$.items[0].title"] == "string(len=5)"
        assert result["$.items[0].score"] == "number"
        assert result["$.pagination"] == "object(2)"
        assert result["$.pagination.next"] == "string(len=3)"

    def test_null_value_in_object(self):
        result = infer_shape({"value": None})
        assert result["$.value"] == "null"
