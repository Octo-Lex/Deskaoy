"""Tests for Action Parameter Validation (v0.16.0 — OSWorld pattern)."""

from __future__ import annotations

import pytest

from deskaoy.safety.action_validator import (
    ACTION_SPECS,
    ActionValidationResult,
    ParameterSpec,
    ValidationIssue,
    validate_action,
)


class TestParameterSpec:
    def test_valid_string(self):
        spec = ParameterSpec("name", str, max_length=10)
        assert spec.validate("hello") == []

    def test_string_too_long(self):
        spec = ParameterSpec("name", str, max_length=5)
        errors = spec.validate("a" * 10)
        assert len(errors) == 1
        assert "exceeds" in errors[0]

    def test_valid_numeric_range(self):
        spec = ParameterSpec("x", float, min_value=0, max_value=100)
        assert spec.validate(50.0) == []

    def test_numeric_below_min(self):
        spec = ParameterSpec("x", float, min_value=0, max_value=100)
        errors = spec.validate(-1.0)
        assert len(errors) == 1
        assert "below minimum" in errors[0]

    def test_numeric_above_max(self):
        spec = ParameterSpec("x", float, min_value=0, max_value=100)
        errors = spec.validate(101.0)
        assert len(errors) == 1
        assert "exceeds maximum" in errors[0]

    def test_allowed_values(self):
        spec = ParameterSpec("button", str, allowed_values=["left", "right", "middle"])
        assert spec.validate("left") == []
        errors = spec.validate("top")
        assert len(errors) == 1
        assert "not in allowed" in errors[0]

    def test_wrong_type(self):
        spec = ParameterSpec("x", float)
        errors = spec.validate("not_a_number")
        assert len(errors) >= 1
        assert "must be" in errors[0]

    def test_int_to_float_coercion(self):
        spec = ParameterSpec("x", float, min_value=0, max_value=100)
        assert spec.validate(50) == []  # int should be accepted as float


class TestValidateAction:
    def test_click_valid_params(self):
        result = validate_action("click", {"target": "button", "x": 100, "y": 200})
        assert result.valid
        assert len(result.errors) == 0

    def test_click_out_of_range_x(self):
        result = validate_action("click", {"x": 99999, "y": 200})
        assert not result.valid
        assert any("exceeds maximum" in e.message for e in result.errors)

    def test_click_negative_y(self):
        result = validate_action("click", {"x": 100, "y": -50})
        assert not result.valid
        assert any("below minimum" in e.message for e in result.errors)

    def test_click_invalid_button(self):
        result = validate_action("click", {"button": "diagonal"})
        assert not result.valid

    def test_click_valid_button(self):
        result = validate_action("click", {"button": "right"})
        assert result.valid

    def test_fill_missing_target(self):
        result = validate_action("fill", {"value": "hello"})
        assert not result.valid
        assert any("missing" in e.message for e in result.errors)

    def test_fill_valid(self):
        result = validate_action("fill", {"target": "input", "value": "hello"})
        assert result.valid

    def test_fill_oversized_value_warns(self):
        """Oversize values should error (max_length is enforced)."""
        result = validate_action("fill", {"target": "input", "value": "x" * 20000})
        assert not result.valid
        assert any("exceeds" in e.message for e in result.errors)

    def test_type_text_valid(self):
        result = validate_action("type_text", {"target": "field", "text": "hello world"})
        assert result.valid

    def test_key_press_valid(self):
        result = validate_action("key_press", {"key": "enter"})
        assert result.valid

    def test_key_press_empty_key(self):
        result = validate_action("key_press", {"key": ""})
        assert result.valid  # Empty string passes type check (no length constraint on key_press)

    def test_scroll_invalid_direction(self):
        result = validate_action("scroll", {"direction": "diagonal"})
        assert not result.valid
        assert any("not in allowed" in e.message for e in result.errors)

    def test_scroll_valid(self):
        result = validate_action("scroll", {"direction": "down", "amount": 3})
        assert result.valid

    def test_navigate_valid_url(self):
        result = validate_action("navigate", {"url": "https://example.com"})
        assert result.valid

    def test_navigate_missing_url(self):
        result = validate_action("navigate", {})
        assert not result.valid
        assert any("missing" in e.message for e in result.errors)

    def test_screenshot_no_params(self):
        result = validate_action("screenshot", {})
        assert result.valid

    def test_snapshot_no_params(self):
        result = validate_action("snapshot", {})
        assert result.valid

    def test_unknown_action_passes(self):
        """Unknown actions should pass through without blocking."""
        result = validate_action("custom_action", {"any": "params"})
        assert result.valid
        assert result.sanitized_params == {"any": "params"}

    def test_sanitized_coerces_types(self):
        """String numbers should be coerced to numeric types."""
        result = validate_action("click", {"x": "100", "y": "200"})
        assert result.valid
        assert result.sanitized_params["x"] == 100
        assert result.sanitized_params["y"] == 200

    def test_extra_params_warn(self):
        """Unknown params should produce warnings, not errors."""
        result = validate_action("click", {"target": "btn", "unknown_key": "val"})
        assert result.valid  # Warnings don't invalidate
        assert len(result.warnings) >= 1
        assert any("unknown_key" in w.message for w in result.warnings)

    def test_action_specs_cover_all_capabilities(self):
        """Every capability should have a spec entry (even if empty)."""
        from deskaoy.desktop_agent import CAPABILITIES
        for cap in CAPABILITIES:
            assert cap in ACTION_SPECS, f"Missing spec for {cap}"
