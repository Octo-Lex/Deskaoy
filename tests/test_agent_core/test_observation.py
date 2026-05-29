"""Tests for DesktopObservation (v0.16.0 — OSWorld pattern)."""

from __future__ import annotations

import base64
import time

import pytest

from deskaoy.observation import DesktopObservation


class TestDesktopObservation:
    def test_construction_all_fields(self):
        obs = DesktopObservation(
            screenshot=b"PNG_DATA",
            accessibility_tree=[{"role": "button", "name": "OK"}],
            active_window="Notepad",
            focused_element="text area",
            instruction="Type hello",
            step_count=3,
        )
        assert obs.screenshot == b"PNG_DATA"
        assert obs.active_window == "Notepad"
        assert obs.step_count == 3

    def test_defaults(self):
        obs = DesktopObservation()
        assert obs.screenshot is None
        assert obs.accessibility_tree is None
        assert obs.active_window == ""
        assert obs.step_count == 0
        assert obs.extra == {}

    def test_timestamp_auto_populated(self):
        before = time.time()
        obs = DesktopObservation()
        after = time.time()
        assert before <= obs.timestamp <= after

    def test_extra_dict_preserved(self):
        obs = DesktopObservation(extra={"foo": "bar"})
        assert obs.extra == {"foo": "bar"}


class TestToContextString:
    def test_full_context(self):
        obs = DesktopObservation(
            active_window="Chrome",
            focused_element="address bar",
            instruction="Search for cats",
            step_count=5,
            accessibility_tree=[{"a": 1}, {"b": 2}],
            screenshot=b"data",
        )
        ctx = obs.to_context_string()
        assert "Chrome" in ctx
        assert "address bar" in ctx
        assert "Search for cats" in ctx
        assert "Step: 5" in ctx
        assert "2 nodes" in ctx
        assert "Screenshot: yes" in ctx

    def test_minimal_context(self):
        obs = DesktopObservation(step_count=0)
        ctx = obs.to_context_string()
        assert "Step: 0" in ctx
        assert "Screenshot: no" in ctx

    def test_dict_tree(self):
        obs = DesktopObservation(accessibility_tree={"root": {"children": []}})
        ctx = obs.to_context_string()
        assert "1 nodes" in ctx


class TestToDict:
    def test_with_screenshot(self):
        obs = DesktopObservation(screenshot=b"hello")
        d = obs.to_dict()
        assert d["screenshot_b64"] == base64.b64encode(b"hello").decode()
        assert d["screenshot_bytes"] == 5

    def test_without_screenshot(self):
        obs = DesktopObservation()
        d = obs.to_dict()
        assert d["screenshot_b64"] is None
        assert d["screenshot_bytes"] == 0

    def test_with_tree(self):
        tree = [{"role": "button"}]
        obs = DesktopObservation(accessibility_tree=tree)
        d = obs.to_dict()
        assert d["accessibility_tree"] == tree

    def test_without_tree(self):
        obs = DesktopObservation()
        d = obs.to_dict()
        assert d["accessibility_tree"] is None

    def test_extra_included(self):
        obs = DesktopObservation(extra={"key": "value"})
        d = obs.to_dict()
        assert d["extra"] == {"key": "value"}

    def test_no_extra_when_empty(self):
        obs = DesktopObservation()
        d = obs.to_dict()
        assert "extra" not in d


class TestFromActionResult:
    def test_extracts_from_data(self):
        """Should extract screenshot, tree, title from ActionResult.data."""

        class FakeResult:
            data = {
                "screenshot": b"PNG",
                "accessibility_tree": [{"role": "window"}],
                "window_title": "Notepad",
                "focused_element": "text area",
            }

        obs = DesktopObservation.from_action_result(
            FakeResult(), instruction="Type hello", step_count=2,
        )
        assert obs.screenshot == b"PNG"
        assert obs.accessibility_tree == [{"role": "window"}]
        assert obs.active_window == "Notepad"
        assert obs.focused_element == "text area"
        assert obs.instruction == "Type hello"
        assert obs.step_count == 2

    def test_base64_screenshot(self):
        """Should decode base64 screenshot strings."""

        class FakeResult:
            data = {"screenshot": base64.b64encode(b"PNG").decode()}

        obs = DesktopObservation.from_action_result(FakeResult())
        assert obs.screenshot == b"PNG"

    def test_none_data(self):
        """Should handle None data gracefully."""

        class FakeResult:
            data = None

        obs = DesktopObservation.from_action_result(FakeResult())
        assert obs.screenshot is None
        assert obs.active_window == ""

    def test_title_fallback(self):
        """Should use 'title' if 'window_title' not present."""

        class FakeResult:
            data = {"title": "Chrome"}

        obs = DesktopObservation.from_action_result(FakeResult())
        assert obs.active_window == "Chrome"

    def test_ax_snapshot_alias(self):
        """Should use 'ax_snapshot' if 'accessibility_tree' not present."""

        class FakeResult:
            data = {"ax_snapshot": [1, 2, 3]}

        obs = DesktopObservation.from_action_result(FakeResult())
        assert obs.accessibility_tree == [1, 2, 3]

    def test_extra_excludes_known_keys(self):
        """Extra should not contain screenshot/tree/title keys."""

        class FakeResult:
            data = {
                "screenshot": b"P",
                "window_title": "App",
                "custom_key": "value",
            }

        obs = DesktopObservation.from_action_result(FakeResult())
        assert "custom_key" in obs.extra
        assert "screenshot" not in obs.extra
        assert "window_title" not in obs.extra
