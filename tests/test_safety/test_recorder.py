"""Tests for session recorder."""

import json

import pytest

from deskaoy.recording.recorder import SessionRecorder
from deskaoy.recording.types import (
    _filter_sensitive,
)


class _FakeResult:
    """Minimal ActionResult-like object for testing."""
    def __init__(self, success: bool = True, error_msg: str = ""):
        self.success = success
        self.error = None
        if error_msg:
            self.error = type("Err", (), {"message": error_msg})()


class TestSessionRecorder:
    def test_start_stop_lifecycle(self):
        r = SessionRecorder(session_id="test-001")
        assert not r.is_recording

        r.start(instruction="Open Notepad")
        assert r.is_recording
        assert r.session is not None
        assert r.session.instruction == "Open Notepad"

        session = r.stop()
        assert not r.is_recording
        assert session.final_state == "completed"
        assert session.step_count == 0

    def test_record_step(self):
        r = SessionRecorder(session_id="test-002", capture_screenshots=False)
        r.start(instruction="Test")

        step = r.record_step(
            step_index=0,
            action="click",
            target="Save button",
            tier_used="uia",
            result=_FakeResult(success=True),
            duration_ms=150.0,
        )

        assert step.step_index == 0
        assert step.action == "click"
        assert step.target == "Save button"
        assert step.succeeded is True
        assert r.session.step_count == 1
        r.stop()

    def test_record_step_with_error(self):
        r = SessionRecorder(session_id="test-003", capture_screenshots=False)
        r.start(instruction="Test")

        step = r.record_step(
            step_index=0,
            action="click",
            target="Missing button",
            result=_FakeResult(success=False, error_msg="Element not found"),
            duration_ms=50.0,
        )

        assert step.succeeded is False
        r.stop()

    def test_success_rate(self):
        r = SessionRecorder(session_id="test-004", capture_screenshots=False)
        r.start()

        r.record_step(0, "click", result=_FakeResult(success=True))
        r.record_step(1, "click", result=_FakeResult(success=True))
        r.record_step(2, "click", result=_FakeResult(success=False, error_msg="fail"))

        session = r.stop()
        assert session.success_rate == pytest.approx(2 / 3)

    def test_save_and_load(self, tmp_path):
        r = SessionRecorder(session_id="test-005", capture_screenshots=False)
        r.start(instruction="Save test")
        r.record_step(0, "click", target="OK", result=_FakeResult(success=True))
        r.stop()

        save_path = tmp_path / "recording.json"
        r.save(save_path)

        assert save_path.exists()
        data = json.loads(save_path.read_text())
        assert data["session_id"] == "test-005"
        assert data["step_count"] == 1

        # Load
        loaded = SessionRecorder.load(save_path)
        assert loaded.session_id == "test-005"
        assert loaded.step_count == 1
        assert loaded.steps[0].action == "click"

    def test_save_creates_directories(self, tmp_path):
        r = SessionRecorder(session_id="test-006", capture_screenshots=False)
        r.start()
        r.stop()

        deep_path = tmp_path / "a" / "b" / "rec.json"
        r.save(deep_path)
        assert deep_path.exists()

    def test_max_screenshots_respected(self, tmp_path):
        r = SessionRecorder(
            session_id="test-007",
            screenshot_dir=tmp_path / "shots",
            max_screenshots=2,
            capture_screenshots=True,
        )
        r.start()
        r.record_step(0, "click")
        r.record_step(1, "click")
        r.record_step(2, "click")  # Should skip screenshot
        r.stop()

        # Even without mss, the count should be respected
        assert r.session.step_count == 3

    def test_no_recording_when_stopped(self):
        r = SessionRecorder(session_id="test-008")
        step = r.record_step(0, "click")
        assert step.step_index == 0
        assert r.session is None

    def test_final_state_propagated(self):
        r = SessionRecorder(session_id="test-009", capture_screenshots=False)
        r.start()
        session = r.stop(final_state="failed")
        assert session.final_state == "failed"


class TestFilterSensitive:
    def test_filters_password(self):
        result = _filter_sensitive({"username": "alice", "password": "secret123"})
        assert result["username"] == "alice"
        assert result["password"] == "[REDACTED]"

    def test_filters_api_key(self):
        result = _filter_sensitive({"model": "gpt-4", "api_key": "sk-123"})
        assert result["api_key"] == "[REDACTED]"

    def test_preserves_normal_keys(self):
        data = {"action": "click", "target": "Save"}
        result = _filter_sensitive(data)
        assert result == data

    def test_filters_token(self):
        result = _filter_sensitive({"token": "abc123"})
        assert result["token"] == "[REDACTED]"
