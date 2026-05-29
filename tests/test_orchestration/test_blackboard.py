"""Tests for Blackboard — shared key-value store."""

import asyncio

import pytest

from deskaoy.orchestration.blackboard import Blackboard


class TestBlackboard:
    def test_write_and_read(self):
        bb = Blackboard()
        bb.write("email.subject", "Q3 Report", writer="outlook")
        assert bb.read("email.subject") == "Q3 Report"

    def test_read_nonexistent_returns_none(self):
        bb = Blackboard()
        assert bb.read("missing.key") is None

    def test_write_overwrites(self):
        bb = Blackboard()
        bb.write("key", "v1", writer="a")
        bb.write("key", "v2", writer="b")
        assert bb.read("key") == "v2"

    def test_version_increments_on_overwrite(self):
        bb = Blackboard()
        bb.write("key", "v1", writer="a")
        bb.write("key", "v2", writer="a")
        meta = bb.snapshot_with_meta()
        assert meta["key"]["version"] == 2

    def test_writer_tracking(self):
        bb = Blackboard()
        bb.write("key", "val", writer="outlook_agent")
        meta = bb.snapshot_with_meta()
        assert meta["key"]["writer"] == "outlook_agent"

    def test_snapshot(self):
        bb = Blackboard()
        bb.write("a", 1, writer="x")
        bb.write("b", 2, writer="y")
        snap = bb.snapshot()
        assert snap == {"a": 1, "b": 2}

    def test_keys(self):
        bb = Blackboard()
        bb.write("x", 1, writer="a")
        bb.write("y", 2, writer="a")
        assert sorted(bb.keys()) == ["x", "y"]

    def test_has(self):
        bb = Blackboard()
        assert bb.has("key") is False
        bb.write("key", "val", writer="a")
        assert bb.has("key") is True

    def test_contains_dunder(self):
        bb = Blackboard()
        assert "key" not in bb
        bb.write("key", "val", writer="a")
        assert "key" in bb

    def test_len(self):
        bb = Blackboard()
        assert len(bb) == 0
        bb.write("a", 1, writer="x")
        bb.write("b", 2, writer="x")
        assert len(bb) == 2

    def test_clear(self):
        bb = Blackboard()
        bb.write("a", 1, writer="x")
        bb.write("b", 2, writer="x")
        bb.clear()
        assert len(bb) == 0
        assert bb.read("a") is None

    @pytest.mark.asyncio
    async def test_read_or_wait_immediate(self):
        bb = Blackboard()
        bb.write("key", "value", writer="a")
        result = await bb.read_or_wait("key", timeout=1.0)
        assert result == "value"

    @pytest.mark.asyncio
    async def test_read_or_wait_waits_for_write(self):
        bb = Blackboard()

        async def delayed_write():
            await asyncio.sleep(0.1)
            bb.write("key", "delayed_value", writer="late")

        write_task = asyncio.create_task(delayed_write())
        result = await bb.read_or_wait("key", timeout=2.0)
        await write_task
        assert result == "delayed_value"

    @pytest.mark.asyncio
    async def test_read_or_wait_timeout(self):
        bb = Blackboard()
        with pytest.raises(TimeoutError):
            await bb.read_or_wait("never_written", timeout=0.2)

    def test_multiple_keys_isolated(self):
        bb = Blackboard()
        bb.write("app1.key", "v1", writer="app1")
        bb.write("app2.key", "v2", writer="app2")
        assert bb.read("app1.key") == "v1"
        assert bb.read("app2.key") == "v2"

    def test_snapshot_with_meta(self):
        bb = Blackboard()
        bb.write("key", "val", writer="test_writer")
        meta = bb.snapshot_with_meta()
        assert "key" in meta
        assert meta["key"]["value"] == "val"
        assert meta["key"]["writer"] == "test_writer"
        assert meta["key"]["version"] == 1
        assert meta["key"]["timestamp"] > 0
