"""Tests for CheckpointManager — H6: real implementation tests."""

import asyncio
from pathlib import Path

import pytest

from deskaoy.recovery.checkpoint import CheckpointManager


class TestCheckpointManagerInit:
    def test_initialize_creates_directory(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        assert (tmp_path / ".deskaoy" / "checkpoints").is_dir()

    def test_initialize_idempotent(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        asyncio.run(mgr.initialize())  # should not raise
        assert (tmp_path / ".deskaoy" / "checkpoints").is_dir()

    def test_custom_checkpoint_dir(self, tmp_path):
        custom = tmp_path / "custom-cp"
        mgr = CheckpointManager(tmp_path, checkpoint_dir=custom)
        asyncio.run(mgr.initialize())
        assert custom.is_dir()


class TestCheckpointManagerCreate:
    def test_create_returns_checkpoint(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        cp = asyncio.run(mgr.create_checkpoint("test checkpoint"))
        assert cp.checkpoint_id
        assert cp.message == "test checkpoint"
        assert cp.created_at > 0

    def test_create_with_state(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        cp = asyncio.run(mgr.create_checkpoint(
            "page state",
            url="https://example.com",
            title="Example",
            scroll_y=500,
            action_history=[{"action": "click", "target": "#btn"}],
        ))
        assert cp.checkpoint_id

    def test_create_persists_to_disk(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        cp = asyncio.run(mgr.create_checkpoint(
            "persist test",
            url="https://example.com",
        ))
        data = mgr.load_checkpoint_data(cp.checkpoint_id)
        assert data is not None
        assert data["url"] == "https://example.com"
        assert data["message"] == "persist test"

    def test_create_multiple(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        asyncio.run(mgr.create_checkpoint("cp1"))
        asyncio.run(mgr.create_checkpoint("cp2"))
        asyncio.run(mgr.create_checkpoint("cp3"))
        assert len(mgr.list_checkpoints()) == 3


class TestCheckpointManagerRollback:
    def test_rollback_existing(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        cp = asyncio.run(mgr.create_checkpoint("rollback test"))
        assert asyncio.run(mgr.rollback(cp.checkpoint_id)) is True

    def test_rollback_nonexistent(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        assert asyncio.run(mgr.rollback("nonexistent")) is False

    def test_load_data_nonexistent(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        assert mgr.load_checkpoint_data("nonexistent") is None


class TestCheckpointManagerList:
    def test_list_empty_after_init(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        assert mgr.list_checkpoints() == []

    def test_list_returns_all(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        asyncio.run(mgr.create_checkpoint("a"))
        asyncio.run(mgr.create_checkpoint("b"))
        checkpoints = mgr.list_checkpoints()
        assert len(checkpoints) == 2

    def test_list_respects_limit(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())
        for i in range(10):
            asyncio.run(mgr.create_checkpoint(f"cp{i}"))
        assert len(mgr.list_checkpoints(limit=3)) == 3


class TestCheckpointManagerPersistence:
    def test_persists_across_instances(self, tmp_path):
        mgr1 = CheckpointManager(tmp_path)
        asyncio.run(mgr1.initialize())
        cp = asyncio.run(mgr1.create_checkpoint("survive restart", url="https://test.com"))

        # New instance loads from disk
        mgr2 = CheckpointManager(tmp_path)
        asyncio.run(mgr2.initialize())
        checkpoints = mgr2.list_checkpoints()
        assert len(checkpoints) == 1
        assert checkpoints[0].message == "survive restart"

        # Data is still accessible
        data = mgr2.load_checkpoint_data(cp.checkpoint_id)
        assert data["url"] == "https://test.com"

    def test_ignores_corrupt_files(self, tmp_path):
        mgr = CheckpointManager(tmp_path)
        asyncio.run(mgr.initialize())

        # Write a corrupt checkpoint file
        cp_dir = tmp_path / ".deskaoy" / "checkpoints"
        (cp_dir / "corrupt123.json").write_text("not valid json{{{", encoding="utf-8")

        # Should not crash when loading
        mgr2 = CheckpointManager(tmp_path)
        asyncio.run(mgr2.initialize())
        assert mgr2.list_checkpoints() == []
