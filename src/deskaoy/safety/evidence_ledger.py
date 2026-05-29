"""Evidence Ledger — tamper-evident append-only audit trail.

Every DesktopAgent action produces an immutable record in a JSONL file.
Each entry's hash includes the previous entry's hash, forming a SHA-256
chain.  If any entry is modified or removed, the chain breaks and
`verify_integrity()` will detect it.

Pattern source: deterministic-agent-control-protocol (det-acp) ledger.ts
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENESIS_HASH = "sha256:" + "0" * 64


# ---------------------------------------------------------------------------
# Entry types
# ---------------------------------------------------------------------------

@dataclass
class LedgerEntry:
    """A single entry in the evidence ledger."""
    seq: int                        # Monotonically increasing
    ts: str                         # ISO-8601 timestamp
    hash: str                       # SHA-256(seq|ts|prev|type|json(data))
    prev: str                       # Previous entry's hash (or GENESIS_HASH)
    session_id: str
    event_type: str                 # "action:evaluate", "action:result", etc.
    data: dict                      # Event payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "hash": self.hash,
            "prev": self.prev,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LedgerEntry:
        return cls(
            seq=d["seq"],
            ts=d["ts"],
            hash=d["hash"],
            prev=d["prev"],
            session_id=d["session_id"],
            event_type=d["event_type"],
            data=d.get("data", {}),
        )


@dataclass
class IntegrityReport:
    """Result of verifying the ledger's hash chain."""
    valid: bool
    total_entries: int
    first_seq: int
    last_seq: int
    broken_at: int | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class EvidenceLedger:
    """Append-only JSONL ledger with SHA-256 hash chaining.

    Usage::

        ledger = EvidenceLedger(Path("ledgers/session-abc.jsonl"))
        await ledger.init()
        entry = await ledger.append("session-abc", "action:start", {"action": "click"})
        report = ledger.verify_integrity()
    """

    def __init__(self, file_path: Path) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._seq: int = 0
        self._last_hash: str = GENESIS_HASH
        self._entries: list[LedgerEntry] = []
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Open or resume the ledger from disk."""
        if self._path.exists():
            await self._resume()
        else:
            self._path.touch()
            logger.debug("Created new ledger: %s", self._path)

    async def close(self) -> None:
        """Flush and close the ledger."""
        self._closed = True

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def append(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> LedgerEntry:
        """Append an entry to the ledger and return it."""
        if self._closed:
            raise RuntimeError("Ledger is closed")

        async with self._lock:
            self._seq += 1
            ts = _iso_now()
            prev = self._last_hash

            entry = LedgerEntry(
                seq=self._seq,
                ts=ts,
                hash=_compute_hash(self._seq, ts, prev, event_type, data),
                prev=prev,
                session_id=session_id,
                event_type=event_type,
                data=data,
            )

            line = json.dumps(entry.to_dict(), separators=(",", ":")) + "\n"
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line)

            self._last_hash = entry.hash
            self._entries.append(entry)

            logger.debug(
                "Ledger entry #%d: %s session=%s",
                entry.seq, entry.event_type, entry.session_id,
            )
            return entry

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_all(self) -> list[LedgerEntry]:
        """Return all entries loaded in memory."""
        return list(self._entries)

    def get_seq(self) -> int:
        """Current sequence number."""
        return self._seq

    def get_last_hash(self) -> str:
        """Hash of the last appended entry."""
        return self._last_hash

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def verify_integrity(self) -> IntegrityReport:
        """Verify the SHA-256 hash chain of all loaded entries.

        Returns an IntegrityReport indicating whether the chain is intact
        and, if broken, where the break occurs.
        """
        if not self._entries:
            return IntegrityReport(
                valid=True,
                total_entries=0,
                first_seq=0,
                last_seq=0,
            )

        prev_hash = GENESIS_HASH

        for _i, entry in enumerate(self._entries):
            # Check prev pointer
            if entry.prev != prev_hash:
                return IntegrityReport(
                    valid=False,
                    total_entries=len(self._entries),
                    first_seq=self._entries[0].seq,
                    last_seq=self._entries[-1].seq,
                    broken_at=entry.seq,
                    error=f"Entry #{entry.seq} prev hash mismatch: "
                          f"expected {prev_hash[:20]}…, got {entry.prev[:20]}…",
                )

            # Recompute hash
            expected = _compute_hash(
                entry.seq, entry.ts, entry.prev, entry.event_type, entry.data,
            )
            if entry.hash != expected:
                return IntegrityReport(
                    valid=False,
                    total_entries=len(self._entries),
                    first_seq=self._entries[0].seq,
                    last_seq=self._entries[-1].seq,
                    broken_at=entry.seq,
                    error=f"Entry #{entry.seq} hash mismatch: "
                          f"expected {expected[:20]}…, got {entry.hash[:20]}…",
                )

            prev_hash = entry.hash

        return IntegrityReport(
            valid=True,
            total_entries=len(self._entries),
            first_seq=self._entries[0].seq,
            last_seq=self._entries[-1].seq,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _resume(self) -> None:
        """Resume from an existing ledger file."""
        with open(self._path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                entry = LedgerEntry.from_dict(d)
                self._entries.append(entry)
                self._seq = entry.seq
                self._last_hash = entry.hash

        logger.debug(
            "Resumed ledger: %d entries, seq=%d", len(self._entries), self._seq,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_hash(
    seq: int,
    ts: str,
    prev: str,
    event_type: str,
    data: dict[str, Any],
) -> str:
    """Compute SHA-256 hash over entry fields."""
    payload = f"{seq}|{ts}|{prev}|{event_type}|{json.dumps(data, separators=(',', ':'), sort_keys=True)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _iso_now() -> str:
    """Return ISO-8601 timestamp with millisecond precision."""
    now = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int((now % 1) * 1000):03d}Z"
