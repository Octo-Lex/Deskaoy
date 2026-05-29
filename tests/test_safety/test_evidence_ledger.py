"""Tests for EvidenceLedger — SHA-256 chained JSONL audit trail."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from deskaoy.safety.evidence_ledger import (
    GENESIS_HASH,
    EvidenceLedger,
    IntegrityReport,
    LedgerEntry,
    _compute_hash,
    _iso_now,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    return tmp_path / "ledgers"


@pytest.fixture
async def ledger(ledger_dir: Path) -> EvidenceLedger:
    ld = EvidenceLedger(ledger_dir / "test.jsonl")
    await ld.init()
    return ld


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_init_creates_file(self, ledger_dir: Path) -> None:
        ld = EvidenceLedger(ledger_dir / "new.jsonl")
        await ld.init()
        assert (ledger_dir / "new.jsonl").exists()

    @pytest.mark.asyncio
    async def test_init_creates_parent_dirs(self, tmp_path: Path) -> None:
        ld = EvidenceLedger(tmp_path / "deep" / "nested" / "ledgers" / "a.jsonl")
        await ld.init()
        assert (tmp_path / "deep" / "nested" / "ledgers" / "a.jsonl").exists()

    @pytest.mark.asyncio
    async def test_close_prevents_append(self, ledger: EvidenceLedger) -> None:
        await ledger.close()
        with pytest.raises(RuntimeError, match="closed"):
            await ledger.append("s1", "test", {})


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------

class TestAppend:
    @pytest.mark.asyncio
    async def test_append_returns_entry(self, ledger: EvidenceLedger) -> None:
        entry = await ledger.append("s1", "action:start", {"action": "click"})
        assert entry.seq == 1
        assert entry.event_type == "action:start"
        assert entry.session_id == "s1"
        assert entry.data == {"action": "click"}
        assert entry.prev == GENESIS_HASH

    @pytest.mark.asyncio
    async def test_append_increments_seq(self, ledger: EvidenceLedger) -> None:
        await ledger.append("s1", "e1", {})
        await ledger.append("s1", "e2", {})
        await ledger.append("s1", "e3", {})
        assert ledger.get_seq() == 3

    @pytest.mark.asyncio
    async def test_append_chains_hashes(self, ledger: EvidenceLedger) -> None:
        e1 = await ledger.append("s1", "e1", {})
        e2 = await ledger.append("s1", "e2", {})
        e3 = await ledger.append("s1", "e3", {})
        assert e1.prev == GENESIS_HASH
        assert e2.prev == e1.hash
        assert e3.prev == e2.hash

    @pytest.mark.asyncio
    async def test_append_writes_to_disk(self, ledger: EvidenceLedger) -> None:
        await ledger.append("s1", "action:start", {"x": 1})
        await ledger.append("s1", "action:result", {"ok": True})

        lines = ledger._path.read_text().strip().split("\n")
        assert len(lines) == 2
        d1 = json.loads(lines[0])
        assert d1["seq"] == 1
        assert d1["event_type"] == "action:start"

    @pytest.mark.asyncio
    async def test_read_all(self, ledger: EvidenceLedger) -> None:
        await ledger.append("s1", "e1", {"a": 1})
        await ledger.append("s1", "e2", {"b": 2})
        entries = ledger.read_all()
        assert len(entries) == 2
        assert entries[0].data == {"a": 1}

    @pytest.mark.asyncio
    async def test_get_last_hash(self, ledger: EvidenceLedger) -> None:
        assert ledger.get_last_hash() == GENESIS_HASH
        e1 = await ledger.append("s1", "e1", {})
        assert ledger.get_last_hash() == e1.hash

    @pytest.mark.asyncio
    async def test_last_hash_updates_on_append(self, ledger: EvidenceLedger) -> None:
        e1 = await ledger.append("s1", "e1", {})
        e2 = await ledger.append("s1", "e2", {})
        assert ledger.get_last_hash() == e2.hash
        assert ledger.get_last_hash() != e1.hash


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

class TestHashComputation:
    def test_compute_hash_deterministic(self) -> None:
        h1 = _compute_hash(1, "2025-01-01T00:00:00.000Z", GENESIS_HASH, "test", {"a": 1})
        h2 = _compute_hash(1, "2025-01-01T00:00:00.000Z", GENESIS_HASH, "test", {"a": 1})
        assert h1 == h2

    def test_compute_hash_differs_for_different_data(self) -> None:
        h1 = _compute_hash(1, "2025-01-01T00:00:00.000Z", GENESIS_HASH, "test", {"a": 1})
        h2 = _compute_hash(1, "2025-01-01T00:00:00.000Z", GENESIS_HASH, "test", {"a": 2})
        assert h1 != h2

    def test_compute_hash_format(self) -> None:
        h = _compute_hash(1, "ts", "prev", "type", {})
        assert h.startswith("sha256:")
        assert len(h) == 7 + 64  # "sha256:" + 64 hex chars

    def test_genesis_hash_format(self) -> None:
        assert GENESIS_HASH.startswith("sha256:")
        assert GENESIS_HASH == "sha256:" + "0" * 64

    def test_iso_now_format(self) -> None:
        ts = _iso_now()
        assert ts.endswith("Z")
        assert "T" in ts


# ---------------------------------------------------------------------------
# Integrity verification
# ---------------------------------------------------------------------------

class TestIntegrity:
    @pytest.mark.asyncio
    async def test_empty_ledger_valid(self, ledger: EvidenceLedger) -> None:
        report = ledger.verify_integrity()
        assert report.valid is True
        assert report.total_entries == 0

    @pytest.mark.asyncio
    async def test_clean_chain_valid(self, ledger: EvidenceLedger) -> None:
        await ledger.append("s1", "e1", {})
        await ledger.append("s1", "e2", {})
        await ledger.append("s1", "e3", {})
        report = ledger.verify_integrity()
        assert report.valid is True
        assert report.total_entries == 3

    @pytest.mark.asyncio
    async def test_tampered_entry_detected(self, ledger: EvidenceLedger) -> None:
        await ledger.append("s1", "e1", {"secret": "original"})
        await ledger.append("s1", "e2", {})

        # Tamper with first entry's data in memory
        ledger._entries[0].data["secret"] = "tampered"
        report = ledger.verify_integrity()
        assert report.valid is False
        assert report.broken_at == 1
        assert "hash mismatch" in report.error

    @pytest.mark.asyncio
    async def test_broken_prev_detected(self, ledger: EvidenceLedger) -> None:
        await ledger.append("s1", "e1", {})
        await ledger.append("s1", "e2", {})

        # Break the prev pointer
        ledger._entries[1].prev = "sha256:broken"
        report = ledger.verify_integrity()
        assert report.valid is False
        assert report.broken_at == 2

    @pytest.mark.asyncio
    async def test_report_fields(self, ledger: EvidenceLedger) -> None:
        await ledger.append("s1", "e1", {})
        await ledger.append("s1", "e2", {})
        report = ledger.verify_integrity()
        assert report.first_seq == 1
        assert report.last_seq == 2
        assert report.broken_at is None
        assert report.error is None


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

class TestResume:
    @pytest.mark.asyncio
    async def test_resume_preserves_chain(self, ledger_dir: Path) -> None:
        path = ledger_dir / "resume.jsonl"

        # Write 3 entries
        ld1 = EvidenceLedger(path)
        await ld1.init()
        e1 = await ld1.append("s1", "e1", {"x": 1})
        e2 = await ld1.append("s1", "e2", {"x": 2})
        e3 = await ld1.append("s1", "e3", {"x": 3})
        await ld1.close()

        # Resume
        ld2 = EvidenceLedger(path)
        await ld2.init()
        assert ld2.get_seq() == 3
        assert ld2.get_last_hash() == e3.hash
        assert len(ld2.read_all()) == 3

        # Can append more
        e4 = await ld2.append("s1", "e4", {"x": 4})
        assert e4.prev == e3.hash
        assert ld2.get_seq() == 4
        assert ld2.verify_integrity().valid is True

    @pytest.mark.asyncio
    async def test_resume_integrity_check(self, ledger_dir: Path) -> None:
        path = ledger_dir / "integrity.jsonl"

        ld1 = EvidenceLedger(path)
        await ld1.init()
        for i in range(5):
            await ld1.append("s1", f"e{i}", {"i": i})
        await ld1.close()

        ld2 = EvidenceLedger(path)
        await ld2.init()
        report = ld2.verify_integrity()
        assert report.valid is True
        assert report.total_entries == 5


# ---------------------------------------------------------------------------
# Multiple sessions
# ---------------------------------------------------------------------------

class TestMultipleSessions:
    @pytest.mark.asyncio
    async def test_separate_files(self, ledger_dir: Path) -> None:
        ld1 = EvidenceLedger(ledger_dir / "sess-a.jsonl")
        ld2 = EvidenceLedger(ledger_dir / "sess-b.jsonl")
        await ld1.init()
        await ld2.init()

        await ld1.append("a", "e1", {})
        await ld2.append("b", "e1", {})
        await ld1.append("a", "e2", {})

        assert ld1.get_seq() == 2
        assert ld2.get_seq() == 1

    @pytest.mark.asyncio
    async def test_entries_from_different_sessions(self, ledger: EvidenceLedger) -> None:
        await ledger.append("sess-a", "e1", {})
        await ledger.append("sess-b", "e1", {})
        await ledger.append("sess-a", "e2", {})
        entries = ledger.read_all()
        assert [e.session_id for e in entries] == ["sess-a", "sess-b", "sess-a"]


# ---------------------------------------------------------------------------
# Entry serialization
# ---------------------------------------------------------------------------

class TestEntrySerialization:
    def test_round_trip(self) -> None:
        entry = LedgerEntry(
            seq=1, ts="2025-01-01T00:00:00.000Z",
            hash="sha256:abc123", prev=GENESIS_HASH,
            session_id="s1", event_type="test", data={"key": "value"},
        )
        d = entry.to_dict()
        restored = LedgerEntry.from_dict(d)
        assert restored.seq == entry.seq
        assert restored.hash == entry.hash
        assert restored.data == entry.data

    def test_from_dict_missing_data(self) -> None:
        d = {"seq": 1, "ts": "ts", "hash": "h", "prev": "p",
             "session_id": "s", "event_type": "e"}
        entry = LedgerEntry.from_dict(d)
        assert entry.data == {}
