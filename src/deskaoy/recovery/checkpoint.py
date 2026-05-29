"""CheckpointManager — action-based checkpoint save/restore for recovery.

H6: Replaces stub with JSON-file-based implementation. Each checkpoint captures
browser state (URL, title, scroll position) and action history for rollback.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from deskaoy.recovery.types import Checkpoint


class CheckpointManager:
    """Manages action checkpoints for recovery rollback.

    Each checkpoint is stored as a JSON file in the checkpoint directory,
    containing browser state (URL, title, scroll position) and a list
    of actions that can be replayed after rollback.
    """

    def __init__(self, workspace: Path, checkpoint_dir: Path | None = None) -> None:
        self._workspace = workspace
        self._checkpoint_dir = checkpoint_dir or workspace / ".deskaoy" / "checkpoints"
        self._checkpoints: dict[str, Checkpoint] = {}

    async def initialize(self) -> None:
        """Create checkpoint directory and load any existing checkpoints."""
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    async def create_checkpoint(
        self,
        message: str,
        *,
        url: str = "",
        title: str = "",
        scroll_y: int = 0,
        action_history: list[dict] | None = None,
    ) -> Checkpoint:
        """Create a new checkpoint with browser state and action history."""
        checkpoint_id = hashlib.sha256(
            f"{time.monotonic()}|{message}".encode()
        ).hexdigest()[:12]

        data = {
            "url": url,
            "title": title,
            "scroll_y": scroll_y,
            "actions": action_history or [],
            "message": message,
            "created_at": time.monotonic(),
        }

        file_path = self._checkpoint_dir / f"{checkpoint_id}.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        cp = Checkpoint(
            checkpoint_id=checkpoint_id,
            message=message,
            created_at=data["created_at"],
            file_count=1,
            commit_hash=checkpoint_id,
        )
        self._checkpoints[checkpoint_id] = cp
        return cp

    async def rollback(self, checkpoint_id: str) -> bool:
        """Validate that a checkpoint exists and can be restored.

        Returns True if the checkpoint exists, False otherwise.
        The actual browser state restoration is handled by RecoveryCoordinator,
        which calls load_checkpoint_data() to get the state to restore.
        """
        if checkpoint_id not in self._checkpoints:
            return False
        file_path = self._checkpoint_dir / f"{checkpoint_id}.json"
        return file_path.exists()

    def load_checkpoint_data(self, checkpoint_id: str) -> dict | None:
        """Load the raw checkpoint data for a given ID."""
        file_path = self._checkpoint_dir / f"{checkpoint_id}.json"
        if not file_path.exists():
            return None
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def list_checkpoints(self, limit: int = 20) -> list[Checkpoint]:
        """List recent checkpoints, most recent last."""
        return list(self._checkpoints.values())[-limit:]

    def _load_existing(self) -> None:
        """Load checkpoint metadata from disk."""
        for path in sorted(self._checkpoint_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                cp = Checkpoint(
                    checkpoint_id=path.stem,
                    message=data.get("message", ""),
                    created_at=data.get("created_at", 0.0),
                    file_count=1,
                    commit_hash=path.stem,
                )
                self._checkpoints[cp.checkpoint_id] = cp
            except (json.JSONDecodeError, KeyError):
                pass
