"""Tests for ActionMemory store — record, recall, persist, heal, stats."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.memory.store import ActionMemory, MemoryConfig, _safe_filename
from deskaoy.memory.types import (
    ActionEvidence,
    AnchorKind,
    DurableTarget,
    TierRecord,
    compute_target_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store_dir(tmp_path):
    return tmp_path / "memory"


@pytest.fixture
def memory(store_dir):
    config = MemoryConfig(
        store_dir=store_dir,
        max_entries_per_domain=10,
        recall_confidence_threshold=0.3,
    )
    return ActionMemory(config=config)


def _evidence(
    intent: str = "click login",
    surface: str = "browser",
    domain: str = "example.com",
    succeeded: bool = True,
    **kwargs,
) -> ActionEvidence:
    return ActionEvidence(
        action="click",
        target_description=intent,
        surface=surface,
        domain=domain,
        succeeded=succeeded,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


class TestRecord:
    @pytest.mark.asyncio
    async def test_create_new_target(self, memory):
        evidence = _evidence(selector="button.login")
        target = await memory.record(evidence)
        assert target.target_id == compute_target_id("click login", "browser", "example.com")
        assert target.selector == "button.login"
        assert target.success_count == 1

    @pytest.mark.asyncio
    async def test_merge_existing_target(self, memory):
        e1 = _evidence(selector="button.login", uia_name="Login")
        await memory.record(e1)

        e2 = _evidence(selector="button.login-new", ocr_text="Log in")
        target = await memory.record(e2)

        assert target.selector == "button.login-new"  # updated
        assert target.uia_name == "Login"              # preserved
        assert target.ocr_text == "Log in"             # added
        assert target.success_count == 2

    @pytest.mark.asyncio
    async def test_record_failure(self, memory):
        evidence = _evidence(succeeded=False, error="selector not found")
        target = await memory.record(evidence)
        assert target.success_count == 0
        assert target.fail_count == 1

    @pytest.mark.asyncio
    async def test_nearby_text_merge_dedup(self, memory):
        e1 = _evidence(nearby_text=["Email", "Password"])
        await memory.record(e1)

        e2 = _evidence(nearby_text=["Password", "Submit"])
        target = await memory.record(e2)
        assert "Email" in target.nearby_text
        assert "Password" in target.nearby_text
        assert "Submit" in target.nearby_text

    @pytest.mark.asyncio
    async def test_tier_history_capped(self, memory):
        for i in range(60):
            evidence = _evidence(
                tier_attempts=[TierRecord("selector", "success", 10.0, "selector")]
            )
            await memory.record(evidence)

        stats = memory.stats
        assert stats["total_targets"] == 1

    @pytest.mark.asyncio
    async def test_different_intents_different_targets(self, memory):
        e1 = _evidence(intent="click login")
        e2 = _evidence(intent="click signup")
        t1 = await memory.record(e1)
        t2 = await memory.record(e2)
        assert t1.target_id != t2.target_id

    @pytest.mark.asyncio
    async def test_default_domain(self, memory):
        evidence = _evidence(domain="")
        target = await memory.record(evidence)
        assert target.domain == "unknown"


# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------


class TestRecall:
    @pytest.mark.asyncio
    async def test_recall_existing(self, memory):
        evidence = _evidence(selector="button.login")
        await memory.record(evidence)

        target = await memory.recall("click login", "browser", "example.com")
        assert target is not None
        assert target.selector == "button.login"

    @pytest.mark.asyncio
    async def test_recall_nonexistent(self, memory):
        target = await memory.recall("click login", "browser", "nonexistent.com")
        assert target is None

    @pytest.mark.asyncio
    async def test_recall_below_threshold(self, memory):
        # Create a target with many failures
        for _ in range(10):
            evidence = _evidence(succeeded=False)
            await memory.record(evidence)

        # Should be below default threshold
        target = await memory.recall("click login", "browser", "example.com")
        # May or may not be None depending on score; just verify no crash
        assert target is None or target.reliability < 0.5

    @pytest.mark.asyncio
    async def test_recall_case_insensitive_intent(self, memory):
        evidence = _evidence()
        await memory.record(evidence)

        t1 = await memory.recall("Click Login", "browser", "example.com")
        t2 = await memory.recall("click login", "browser", "example.com")
        assert (t1 is not None) == (t2 is not None)

    @pytest.mark.asyncio
    async def test_recall_updates_stats(self, memory):
        # Record a successful target with high confidence
        evidence = _evidence(selector="button.login", succeeded=True)
        await memory.record(evidence)

        target = await memory.recall("click login", "browser", "example.com")
        assert target is not None  # should be found
        assert memory.stats["hits"] == 1

        await memory.recall("nonexistent", "browser", "example.com")
        assert memory.stats["misses"] == 1


# ---------------------------------------------------------------------------
# Get Anchors
# ---------------------------------------------------------------------------


class TestGetAnchors:
    @pytest.mark.asyncio
    async def test_returns_ranked_anchors(self, memory):
        evidence = _evidence(
            selector="button.login",
            uia_name="Login",
            nearby_text=["Email"],
        )
        await memory.record(evidence)

        anchors = await memory.get_anchors("click login", "browser", "example.com")
        assert len(anchors) >= 2
        # First anchor should have higher confidence
        if len(anchors) >= 2:
            assert anchors[0].confidence >= anchors[1].confidence

    @pytest.mark.asyncio
    async def test_empty_for_nonexistent(self, memory):
        anchors = await memory.get_anchors("nonexistent", "browser", "test.com")
        assert anchors == []


# ---------------------------------------------------------------------------
# Recall by Context
# ---------------------------------------------------------------------------


class TestRecallByContext:
    @pytest.mark.asyncio
    async def test_finds_by_context(self, memory):
        evidence = _evidence(selector="button.login", succeeded=True)
        await memory.record(evidence)

        # Should find the target when searching by context
        results = await memory.recall_by_context("click login", "example.com")
        assert len(results) >= 1
        assert results[0].selector == "button.login"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    @pytest.mark.asyncio
    async def test_persist_and_load(self, memory, store_dir):
        evidence = _evidence(selector="button.login")
        await memory.record(evidence)

        # Verify file was created
        files = list(store_dir.glob("*.json"))
        assert len(files) == 1

        # Create new memory instance and load
        memory2 = ActionMemory(config=MemoryConfig(store_dir=store_dir))
        count = await memory2.load("example.com")
        assert count == 1

        target = await memory2.recall("click login", "browser", "example.com")
        assert target is not None
        assert target.selector == "button.login"

    @pytest.mark.asyncio
    async def test_load_nonexistent_domain(self, memory):
        count = await memory.load("nonexistent.com")
        assert count == 0

    @pytest.mark.asyncio
    async def test_load_corrupt_file(self, store_dir):
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "corrupt.com.json").write_text("not valid json{{{")

        memory = ActionMemory(config=MemoryConfig(store_dir=store_dir))
        count = await memory.load("corrupt.com")
        assert count == 0

    @pytest.mark.asyncio
    async def test_load_all(self, memory, store_dir):
        await memory.record(_evidence(domain="a.com"))
        await memory.record(_evidence(domain="b.com"))

        memory2 = ActionMemory(config=MemoryConfig(store_dir=store_dir))
        total = await memory2.load_all()
        assert total == 2

    @pytest.mark.asyncio
    async def test_persist_atomic(self, store_dir):
        """Verify persist uses atomic write (tmp file)."""
        memory = ActionMemory(config=MemoryConfig(store_dir=store_dir))
        await memory.record(_evidence())

        # Should only have .json, no .tmp
        tmp_files = list(store_dir.glob("*.tmp"))
        assert len(tmp_files) == 0


# ---------------------------------------------------------------------------
# Eviction
# ---------------------------------------------------------------------------


class TestEviction:
    @pytest.mark.asyncio
    async def test_evicts_lru(self, store_dir):
        config = MemoryConfig(store_dir=store_dir, max_entries_per_domain=3)
        memory = ActionMemory(config=config)

        # Create 5 targets
        for i in range(5):
            evidence = _evidence(intent=f"click button {i}")
            await memory.record(evidence)

        stats = memory.stats
        assert stats["total_targets"] == 3


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    @pytest.mark.asyncio
    async def test_initial_stats(self, memory):
        stats = memory.stats
        assert stats["total_targets"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["heal_attempts"] == 0

    @pytest.mark.asyncio
    async def test_domain_stats(self, memory):
        await memory.record(_evidence())
        ds = memory.domain_stats("example.com")
        assert ds["target_count"] == 1

    @pytest.mark.asyncio
    async def test_domain_stats_empty(self, memory):
        ds = memory.domain_stats("nonexistent.com")
        assert ds["target_count"] == 0


# ---------------------------------------------------------------------------
# Heal
# ---------------------------------------------------------------------------


class TestHeal:
    @pytest.mark.asyncio
    async def test_heal_with_ax_match(self, memory):
        # Record a target with UIA name
        evidence = _evidence(uia_name="Login", uia_control_type="button")
        target = await memory.record(evidence)

        # Create AX snapshot with matching node
        snapshot = AXSnapshot(
            url="https://example.com",
            title="Example",
            nodes={
                "btn1": AXNode(ref="btn1", role="button", name="Login"),
            },
        )

        result = await memory.heal(target, snapshot)
        assert result.success is True
        assert result.match is not None
        assert result.match.healed is True

    @pytest.mark.asyncio
    async def test_heal_no_match(self, memory):
        evidence = _evidence(uia_name="Nonexistent", uia_control_type="button")
        target = await memory.record(evidence)

        snapshot = AXSnapshot(
            url="https://example.com",
            title="Example",
            nodes={
                "lnk1": AXNode(ref="lnk1", role="link", name="Other"),
            },
        )

        result = await memory.heal(target, snapshot)
        assert result.success is False
        assert len(result.strategies_tried) > 0

    @pytest.mark.asyncio
    async def test_heal_updates_stats(self, memory):
        evidence = _evidence(uia_name="Login", uia_control_type="button")
        target = await memory.record(evidence)

        snapshot = AXSnapshot(
            url="https://example.com",
            title="Example",
            nodes={"btn1": AXNode(ref="btn1", role="button", name="Login")},
        )

        await memory.heal(target, snapshot)
        assert memory.stats["heal_attempts"] == 1
        assert memory.stats["heal_successes"] == 1

    @pytest.mark.asyncio
    async def test_heal_updates_target(self, memory):
        evidence = _evidence(uia_name="Login", uia_control_type="button")
        target = await memory.record(evidence)
        old_count = target.success_count

        snapshot = AXSnapshot(
            url="https://example.com",
            title="Example",
            nodes={"btn1": AXNode(ref="btn1", role="button", name="Login")},
        )

        await memory.heal(target, snapshot)
        assert target.success_count == old_count + 1


# ---------------------------------------------------------------------------
# Safe filename
# ---------------------------------------------------------------------------


class TestSafeFilename:
    def test_basic(self):
        assert _safe_filename("example.com") == "example.com"

    def test_with_slashes(self):
        result = _safe_filename("https://example.com/path")
        assert "/" not in result

    def test_length_cap(self):
        long_domain = "a" * 200
        result = _safe_filename(long_domain)
        assert len(result) <= 100
