"""Tests for CrashRecovery — agent state persistence across crashes."""

import json
import time

import pytest

from deskaoy.recovery.crash_recovery import (
    CHECKPOINT_VERSION,
    AgentCheckpoint,
    CrashRecovery,
)


@pytest.fixture
def tmp_checkpoint_dir(tmp_path):
    """Provide a temporary directory for checkpoint storage."""
    return tmp_path / "checkpoints"


class TestAgentCheckpoint:
    def test_construction(self):
        cp = AgentCheckpoint(
            session_id="sess-1",
            instruction="Open Notepad",
            completed_steps=3,
            total_steps=10,
            last_action="click",
            last_result="ok",
        )
        assert cp.session_id == "sess-1"
        assert cp.version == CHECKPOINT_VERSION

    def test_to_dict(self):
        cp = AgentCheckpoint(
            session_id="sess-1", instruction="test",
            completed_steps=0, total_steps=5,
            last_action="", last_result="",
        )
        d = cp.to_dict()
        assert d["session_id"] == "sess-1"
        assert d["version"] == CHECKPOINT_VERSION
        assert isinstance(d["errors"], list)

    def test_from_dict(self):
        data = {
            "session_id": "sess-1",
            "instruction": "test",
            "completed_steps": 2,
            "total_steps": 5,
            "last_action": "click",
            "last_result": "ok",
            "errors": ["err1"],
            "plan_items": [],
            "memory_snapshot": {},
            "circuit_breaker_state": "closed",
            "timestamp": 100.0,
            "version": CHECKPOINT_VERSION,
        }
        cp = AgentCheckpoint.from_dict(data)
        assert cp.session_id == "sess-1"
        assert cp.completed_steps == 2
        assert cp.errors == ["err1"]

    def test_from_dict_ignores_unknown_keys(self):
        data = {
            "session_id": "s", "instruction": "i",
            "completed_steps": 0, "total_steps": 1,
            "last_action": "", "last_result": "",
            "unknown_key": "should be ignored",
        }
        cp = AgentCheckpoint.from_dict(data)
        assert cp.session_id == "s"
        assert not hasattr(cp, "unknown_key")

    def test_round_trip(self):
        cp = AgentCheckpoint(
            session_id="sess-rt",
            instruction="Open Chrome",
            completed_steps=5,
            total_steps=10,
            last_action="fill",
            last_result="success",
            errors=["e1", "e2"],
            plan_items=[{"step": 1}],
            memory_snapshot={"key": "value"},
            circuit_breaker_state="open",
            timestamp=123.456,
        )
        d = cp.to_dict()
        cp2 = AgentCheckpoint.from_dict(d)
        assert cp2.session_id == cp.session_id
        assert cp2.completed_steps == cp.completed_steps
        assert cp2.errors == cp.errors
        assert cp2.memory_snapshot == cp.memory_snapshot
        assert cp2.circuit_breaker_state == cp.circuit_breaker_state


class TestCrashRecovery:
    @pytest.mark.asyncio
    async def test_save_and_load_round_trip(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        cp = AgentCheckpoint(
            session_id="sess-1", instruction="test",
            completed_steps=3, total_steps=10,
            last_action="click", last_result="ok",
        )
        await cr.save(cp)
        loaded = await cr.load("sess-1")
        assert loaded is not None
        assert loaded.session_id == "sess-1"
        assert loaded.completed_steps == 3

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        result = await cr.load("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        for i in range(3):
            cp = AgentCheckpoint(
                session_id=f"sess-{i}", instruction=f"task-{i}",
                completed_steps=0, total_steps=1,
                last_action="", last_result="",
            )
            await cr.save(cp)
        sessions = await cr.list_sessions()
        assert len(sessions) == 3
        assert "sess-0" in sessions

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_checkpoints(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        # Save a checkpoint
        cp = AgentCheckpoint(
            session_id="old", instruction="old task",
            completed_steps=0, total_steps=1,
            last_action="", last_result="",
        )
        await cr.save(cp)

        # Manually backdate the timestamp in the file
        path = tmp_checkpoint_dir / "old.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["timestamp"] = time.monotonic() - (25 * 3600)  # 25h ago
        path.write_text(json.dumps(data), encoding="utf-8")

        # Cleanup with 24h max age
        removed = await cr.cleanup(max_age_hours=24)
        assert removed == 1
        assert await cr.load("old") is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_fresh_checkpoints(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        cp = AgentCheckpoint(
            session_id="fresh", instruction="fresh task",
            completed_steps=0, total_steps=1,
            last_action="", last_result="",
        )
        await cr.save(cp)
        removed = await cr.cleanup(max_age_hours=24)
        assert removed == 0
        assert await cr.load("fresh") is not None

    @pytest.mark.asyncio
    async def test_corrupted_file_handled_gracefully(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        # Ensure the directory exists
        tmp_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        # Write a corrupted file
        path = tmp_checkpoint_dir / "corrupt.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        result = await cr.load("corrupt")
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_sessions_coexist(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        for i in range(5):
            cp = AgentCheckpoint(
                session_id=f"multi-{i}", instruction=f"task-{i}",
                completed_steps=i, total_steps=5,
                last_action=f"action-{i}", last_result="ok",
            )
            await cr.save(cp)
        for i in range(5):
            loaded = await cr.load(f"multi-{i}")
            assert loaded is not None
            assert loaded.completed_steps == i

    @pytest.mark.asyncio
    async def test_save_overwrites_previous(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        cp1 = AgentCheckpoint(
            session_id="overwrite", instruction="first",
            completed_steps=1, total_steps=5,
            last_action="a", last_result="r",
        )
        await cr.save(cp1)

        cp2 = AgentCheckpoint(
            session_id="overwrite", instruction="second",
            completed_steps=3, total_steps=5,
            last_action="b", last_result="r",
        )
        await cr.save(cp2)

        loaded = await cr.load("overwrite")
        assert loaded.instruction == "second"
        assert loaded.completed_steps == 3

    @pytest.mark.asyncio
    async def test_empty_errors_list(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        cp = AgentCheckpoint(
            session_id="no-errors", instruction="test",
            completed_steps=0, total_steps=1,
            last_action="", last_result="",
            errors=[],
        )
        await cr.save(cp)
        loaded = await cr.load("no-errors")
        assert loaded.errors == []

    @pytest.mark.asyncio
    async def test_large_plan_serializes(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        big_plan = [{"step": i, "action": f"act-{i}", "params": {"x": i * 100}} for i in range(50)]
        cp = AgentCheckpoint(
            session_id="big-plan", instruction="big task",
            completed_steps=0, total_steps=50,
            last_action="", last_result="",
            plan_items=big_plan,
        )
        await cr.save(cp)
        loaded = await cr.load("big-plan")
        assert loaded is not None
        assert len(loaded.plan_items) == 50

    @pytest.mark.asyncio
    async def test_memory_snapshot_round_trip(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        snapshot = {
            "targets": {"button1": {"selector": "#btn", "tier": "selector"}},
            "stats": {"hits": 10, "misses": 2},
        }
        cp = AgentCheckpoint(
            session_id="mem-snap", instruction="test",
            completed_steps=0, total_steps=1,
            last_action="", last_result="",
            memory_snapshot=snapshot,
        )
        await cr.save(cp)
        loaded = await cr.load("mem-snap")
        assert loaded.memory_snapshot == snapshot

    @pytest.mark.asyncio
    async def test_circuit_breaker_state_preserved(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        for state in ("closed", "open", "half_open"):
            cp = AgentCheckpoint(
                session_id=f"cb-{state}", instruction="test",
                completed_steps=0, total_steps=1,
                last_action="", last_result="",
                circuit_breaker_state=state,
            )
            await cr.save(cp)
            loaded = await cr.load(f"cb-{state}")
            assert loaded.circuit_breaker_state == state

    @pytest.mark.asyncio
    async def test_version_field(self, tmp_checkpoint_dir):
        cr = CrashRecovery(checkpoint_dir=tmp_checkpoint_dir)
        cp = AgentCheckpoint(
            session_id="v-test", instruction="test",
            completed_steps=0, total_steps=1,
            last_action="", last_result="",
        )
        await cr.save(cp)
        loaded = await cr.load("v-test")
        assert loaded.version == CHECKPOINT_VERSION
