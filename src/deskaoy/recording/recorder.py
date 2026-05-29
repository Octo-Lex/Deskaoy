"""SessionRecorder — records desktop automation steps with optional screenshots.

Pattern source: SUPER-BROWSER recording/recorder.py
Adapted for Deskaoy: uses mss screenshots + filesystem persistence.

Hard Boundary: Screenshot capture failures MUST NOT block the action.
Hard Boundary: Recorded params MUST NOT contain API keys or credentials.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deskaoy.recording.types import (
    RecordingSession,
    StepRecord,
    _filter_sensitive,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SessionRecorder:
    """Records desktop automation steps with optional screenshot capture.

    Usage::

        recorder = SessionRecorder(session_id="run-001")
        recorder.start(instruction="Open Notepad and type Hello")

        # After each step:
        recorder.record_step(
            step_index=0,
            action="click",
            target="Notepad.exe",
            result=action_result,
        )

        session = recorder.stop()
        recorder.save(Path("recordings/run-001.json"))
    """

    def __init__(
        self,
        session_id: str = "",
        *,
        screenshot_dir: Path | None = None,
        max_screenshots: int = 100,
        capture_screenshots: bool = True,
    ) -> None:
        self._session_id = session_id or f"rec-{int(time.time())}"
        self._screenshot_dir = screenshot_dir
        self._max_screenshots = max_screenshots
        self._capture_screenshots = capture_screenshots
        self._session: RecordingSession | None = None
        self._screenshot_count: int = 0
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def session(self) -> RecordingSession | None:
        return self._session

    # -- Lifecycle --

    def start(self, instruction: str = "") -> None:
        """Begin recording a new session."""
        if self._recording:
            return
        self._session = RecordingSession(
            session_id=self._session_id,
            instruction=instruction,
        )
        self._recording = True
        self._screenshot_count = 0
        logger.info("Recording started: %s", self._session_id)

    def stop(self, final_state: str = "completed") -> RecordingSession:
        """Stop recording and return the session."""
        if not self._recording or self._session is None:
            return RecordingSession()
        self._session.final_state = final_state
        self._session.stopped_at = time.monotonic()
        self._recording = False
        logger.info(
            "Recording stopped: %s (%d steps, %.1fs)",
            self._session_id,
            self._session.step_count,
            self._session.duration_s,
        )
        return self._session

    # -- Step Recording --

    def record_step(
        self,
        step_index: int,
        action: str,
        target: str = "",
        value: str = "",
        tier_used: str = "uia",
        result: Any | None = None,
        duration_ms: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> StepRecord:
        """Record a single automation step.

        Screenshot capture failures are logged but do NOT block recording.
        """
        if not self._recording or self._session is None:
            return StepRecord(step_index=step_index, action=action)

        succeeded = True
        error_message = ""
        if result is not None:
            succeeded = getattr(result, "success", True)
            error_obj = getattr(result, "error", None)
            if error_obj:
                error_message = str(getattr(error_obj, "message", str(error_obj)))

        # Capture screenshot (best-effort)
        screenshot_path = ""
        if self._capture_screenshots and self._screenshot_count < self._max_screenshots:
            screenshot_path = self._try_capture_screenshot(step_index)

        record = StepRecord(
            step_index=step_index,
            action=action,
            target=target,
            value=value,
            tier_used=tier_used,
            succeeded=succeeded,
            error_message=error_message,
            screenshot_path=screenshot_path,
            timestamp=time.monotonic(),
            duration_ms=duration_ms,
            metadata=_filter_sensitive(extra) if extra else {},
        )

        self._session.steps.append(record)
        return record

    # -- Persistence --

    def save(self, path: Path) -> None:
        """Save recording session to JSON file."""
        if self._session is None:
            return

        data = {
            "session_id": self._session.session_id,
            "instruction": self._session.instruction,
            "started_at": self._session.started_at,
            "stopped_at": self._session.stopped_at,
            "final_state": self._session.final_state,
            "step_count": self._session.step_count,
            "success_rate": self._session.success_rate,
            "duration_s": self._session.duration_s,
            "steps": [
                {
                    "step_index": s.step_index,
                    "action": s.action,
                    "target": s.target,
                    "value": s.value,
                    "tier_used": s.tier_used,
                    "succeeded": s.succeeded,
                    "error_message": s.error_message,
                    "screenshot_path": s.screenshot_path,
                    "timestamp": s.timestamp,
                    "duration_ms": s.duration_ms,
                }
                for s in self._session.steps
            ],
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Recording saved: %s (%d steps)", path, self._session.step_count)

    @classmethod
    def load(cls, path: Path) -> RecordingSession:
        """Load a recording session from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        session = RecordingSession(
            session_id=data.get("session_id", ""),
            instruction=data.get("instruction", ""),
            started_at=data.get("started_at", 0),
            stopped_at=data.get("stopped_at", 0),
            final_state=data.get("final_state", "unknown"),
        )
        for s_data in data.get("steps", []):
            session.steps.append(StepRecord(
                step_index=s_data["step_index"],
                action=s_data["action"],
                target=s_data.get("target", ""),
                value=s_data.get("value", ""),
                tier_used=s_data.get("tier_used", "uia"),
                succeeded=s_data.get("succeeded", True),
                error_message=s_data.get("error_message", ""),
                screenshot_path=s_data.get("screenshot_path", ""),
                timestamp=s_data.get("timestamp", 0),
                duration_ms=s_data.get("duration_ms", 0),
            ))
        return session

    # -- Internals --

    def _try_capture_screenshot(self, step_index: int) -> str:
        """Best-effort screenshot capture. Returns path or empty string."""
        if self._screenshot_dir is None:
            return ""

        try:
            import mss
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)
            filename = f"step_{step_index:04d}.png"
            filepath = self._screenshot_dir / filename

            with mss.MSS() as sct:
                sct.shot(output=str(filepath))

            self._screenshot_count += 1
            return str(filepath)
        except Exception as exc:
            logger.debug("Screenshot capture failed (step %d): %s", step_index, exc)
            return ""
