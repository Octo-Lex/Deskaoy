"""CrashRecovery — persist and restore agent state across process crashes.

Saves minimal agent state (session ID, instruction, completed steps,
action history, memory snapshot, circuit breaker state) to disk after
every step. On restart, loads the latest checkpoint and resumes.

Storage: JSON file per session in {AIOS_HOME}/checkpoints/{session_id}.json

Wire into AgentLoop._run_loop() (save after every step) and
DesktopAgent.execute() (check for resumable sessions on startup).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CHECKPOINT_VERSION = 1


@dataclass
class AgentCheckpoint:
    """Minimal state needed to resume an agent session."""

    session_id: str
    instruction: str
    completed_steps: int
    total_steps: int
    last_action: str
    last_result: str
    errors: list[str] = field(default_factory=list)
    plan_items: list[dict] = field(default_factory=list)
    memory_snapshot: dict = field(default_factory=dict)
    circuit_breaker_state: str = "closed"
    timestamp: float = 0.0
    version: int = CHECKPOINT_VERSION

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        d = asdict(self)
        d["version"] = CHECKPOINT_VERSION
        return d

    @classmethod
    def from_dict(cls, data: dict) -> AgentCheckpoint:
        """Deserialize from a dict, ignoring unknown keys."""
        known_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_keys}
        return cls(**filtered)


class CrashRecovery:
    """Persist and restore agent state for crash recovery.

    Each session gets one JSON file. Saving overwrites the previous
    checkpoint for that session (always the latest state).
    """

    def __init__(self, checkpoint_dir: Path | None = None) -> None:
        self._checkpoint_dir = checkpoint_dir
        self._initialized = False

    def _ensure_dir(self) -> Path:
        """Ensure checkpoint directory exists and return it."""
        if self._checkpoint_dir is None:
            # Default: use AIOS_HOME or cwd
            try:
                from deskaoy.storage import StorageResolver
                resolver = StorageResolver()
                base = resolver.resolve()
                self._checkpoint_dir = base / "checkpoints"
            except Exception:
                self._checkpoint_dir = Path.cwd() / ".deskaoy" / "checkpoints"

        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._initialized = True
        return self._checkpoint_dir

    async def save(self, checkpoint: AgentCheckpoint) -> str:
        """Save a checkpoint. Returns the checkpoint ID (session_id).

        Overwrites any previous checkpoint for the same session.
        """
        checkpoint.timestamp = time.monotonic()
        checkpoint.version = CHECKPOINT_VERSION

        d = self._ensure_dir()
        path = d / f"{checkpoint.session_id}.json"

        try:
            path.write_text(
                json.dumps(checkpoint.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            return checkpoint.session_id
        except Exception as exc:
            logger.error("Failed to save checkpoint for %s: %s", checkpoint.session_id, exc)
            raise

    async def load(self, session_id: str) -> AgentCheckpoint | None:
        """Load the latest checkpoint for a session.

        Returns None if no checkpoint exists or if the file is corrupted.
        """
        d = self._ensure_dir()
        path = d / f"{session_id}.json"

        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("Corrupted checkpoint for %s: expected dict, got %s", session_id, type(data).__name__)
                return None
            return AgentCheckpoint.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("Corrupted checkpoint for %s: %s", session_id, exc)
            return None

    async def list_sessions(self) -> list[str]:
        """List all sessions with saved checkpoints."""
        d = self._ensure_dir()
        sessions = []
        for path in sorted(d.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(data.get("session_id", path.stem))
            except (json.JSONDecodeError, OSError):
                sessions.append(path.stem)
        return sessions

    async def resume(
        self,
        session_id: str,
        agent: Any,
    ) -> Any:
        """Resume a previously interrupted session.

        Loads the checkpoint, reconstructs the agent state, and
        re-executes from the next unfinished step.

        Returns an AgentResult from the resumed execution.
        """
        checkpoint = await self.load(session_id)
        if checkpoint is None:
            raise ValueError(f"No recoverable checkpoint for session: {session_id}")

        # Restore circuit breaker state if available
        if checkpoint.circuit_breaker_state in ("closed", "half_open"):
            try:
                cb = agent._recovery_bridge.circuit_breaker
                cb.reset()
            except Exception:
                pass

        # Restore memory snapshot if available
        if checkpoint.memory_snapshot and hasattr(agent, "_memory"):
            try:
                await agent._memory.load_snapshot(checkpoint.memory_snapshot)
            except Exception:
                logger.debug("Could not restore memory snapshot", exc_info=True)

        # Re-execute with remaining steps
        from deskaoy.os_types import (
            AgentContext,
            AgentGoal,
        )

        remaining = checkpoint.total_steps - checkpoint.completed_steps
        if remaining <= 0:
            # Already completed — nothing to resume
            from deskaoy.os_types import AgentResult, Confidence, ResultStatus
            return AgentResult(
                execution_id=session_id,
                status=ResultStatus.SUCCESS,
                summary="Session already completed — nothing to resume",
                data={"completed_steps": checkpoint.completed_steps},
                confidence=Confidence(score=1.0, reason="Previously completed"),
            )

        # Build a new goal for the remaining work
        goal = AgentGoal(
            capability="automate",
            params={"instruction": checkpoint.instruction},
        )
        context = AgentContext(
            execution_id=session_id,
            idempotency_key=f"resume-{session_id}",
            task_id="resume",
            user_id="system",
            session_id=session_id,
        )

        return await agent.execute(goal, context)

    async def cleanup(self, max_age_hours: int = 24) -> int:
        """Remove checkpoints older than *max_age_hours*.

        Returns the number of checkpoints removed.
        """
        d = self._ensure_dir()
        cutoff = time.monotonic() - (max_age_hours * 3600)
        removed = 0

        for path in d.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ts = data.get("timestamp", 0.0)
                if ts < cutoff:
                    path.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError):
                # Remove corrupted files too
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass

        return removed
