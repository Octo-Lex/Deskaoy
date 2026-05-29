"""Fact and soul storage — persistent user model.

Adopted from Pocket Agent's facts.ts + soul.ts patterns.

Facts are atomic statements (category/subject/content) about the user,
environment, or workflow. Soul aspects are persistent personality/vibe
preferences that shape agent behavior.

Storage: JSON files in a configurable directory. Keyword search built-in.
Hybrid embedding search available when embedding deps are present (future).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    """A single atomic fact about the user or environment."""

    category: str  # "user_info", "preferences", "projects", "people", "work", "notes"
    subject: str  # "partner_name", "coffee_preference", "current_project"
    content: str  # "Alice", "latte with oat milk", "AI-OS Desktop Agent"
    source: str = ""  # "conversation", "action_observation", "explicit"
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "subject": self.subject,
            "content": self.content,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Fact:
        return cls(
            category=data["category"],
            subject=data["subject"],
            content=data["content"],
            source=data.get("source", ""),
            confidence=data.get("confidence", 1.0),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class SoulAspect:
    """A persistent personality/vibe aspect."""

    aspect: str  # "tone", "verbosity", "humor"
    content: str  # "concise and technical", "brief", "dry"
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {"aspect": self.aspect, "content": self.content,
                "updated_at": self.updated_at}

    @classmethod
    def from_dict(cls, data: dict) -> SoulAspect:
        return cls(
            aspect=data["aspect"],
            content=data["content"],
            updated_at=data.get("updated_at", ""),
        )


# ---------------------------------------------------------------------------
# FactStore
# ---------------------------------------------------------------------------


class FactStore:
    """JSON-file-backed fact and soul storage.

    File layout::

        {storage_dir}/facts.json    — list of Fact dicts
        {storage_dir}/soul.json     — list of SoulAspect dicts

    Provides keyword search (no embedding deps required).
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir
        self._facts: list[Fact] = []
        self._soul: list[SoulAspect] = []
        self._facts_cache: str | None = None
        self._facts_cache_valid: bool = False
        self._soul_cache: str | None = None
        self._soul_cache_valid: bool = False

    # ── Fact CRUD ─────────────────────────────────────────────────────────

    def save_fact(self, fact: Fact) -> str:
        """Save or update a fact (upsert by category+subject).

        Returns ``"{category}/{subject}"`` as the key.
        """
        now = _now_iso()
        fact.updated_at = now

        # Upsert: update existing fact with same category+subject
        for i, existing in enumerate(self._facts):
            if existing.category == fact.category and existing.subject == fact.subject:
                fact.created_at = existing.created_at or now
                self._facts[i] = fact
                self._invalidate_cache()
                self.save()
                return f"{fact.category}/{fact.subject}"

        fact.created_at = now
        self._facts.append(fact)
        self._invalidate_cache()
        self.save()
        return f"{fact.category}/{fact.subject}"

    def get_facts(self, category: str = "") -> list[Fact]:
        """Get facts, optionally filtered by category."""
        if not category:
            return list(self._facts)
        return [f for f in self._facts if f.category == category]

    def search_facts(self, query: str, limit: int = 6) -> list[tuple[Fact, float]]:
        """Keyword search. Returns (fact, score) pairs sorted by score desc."""
        return self._keyword_search(query, limit)

    def delete_fact(self, category: str, subject: str) -> bool:
        """Delete a fact by category+subject."""
        before = len(self._facts)
        self._facts = [
            f for f in self._facts
            if not (f.category == category and f.subject == subject)
        ]
        if len(self._facts) < before:
            self._invalidate_cache()
            self.save()
            return True
        return False

    def all_facts(self) -> list[Fact]:
        return list(self._facts)

    def fact_count(self) -> int:
        return len(self._facts)

    # ── Soul CRUD ─────────────────────────────────────────────────────────

    def set_soul(self, aspect: str, content: str) -> None:
        """Set or update a soul aspect."""
        now = _now_iso()
        for i, sa in enumerate(self._soul):
            if sa.aspect == aspect:
                self._soul[i] = SoulAspect(aspect=aspect, content=content, updated_at=now)
                self._soul_cache_valid = False
                self.save()
                return
        self._soul.append(SoulAspect(aspect=aspect, content=content, updated_at=now))
        self._soul_cache_valid = False
        self.save()

    def get_soul(self, aspect: str) -> SoulAspect | None:
        for sa in self._soul:
            if sa.aspect == aspect:
                return sa
        return None

    def all_soul(self) -> list[SoulAspect]:
        return list(self._soul)

    def delete_soul(self, aspect: str) -> bool:
        before = len(self._soul)
        self._soul = [sa for sa in self._soul if sa.aspect != aspect]
        if len(self._soul) < before:
            self._soul_cache_valid = False
            self.save()
            return True
        return False

    # ── Context injection ─────────────────────────────────────────────────

    def facts_for_context(self) -> str:
        """Format all facts as markdown for LLM context injection."""
        if self._facts_cache_valid and self._facts_cache is not None:
            return self._facts_cache

        if not self._facts:
            self._facts_cache = ""
            self._facts_cache_valid = True
            return ""

        by_category: dict[str, list[Fact]] = {}
        for f in self._facts:
            by_category.setdefault(f.category, []).append(f)

        lines: list[str] = ["## Known Facts"]
        for cat in sorted(by_category):
            lines.append(f"\n### {cat}")
            for f in sorted(by_category[cat], key=lambda x: x.subject):
                lines.append(f"- **{f.subject}**: {f.content}")

        result = "\n".join(lines)
        self._facts_cache = result
        self._facts_cache_valid = True
        return result

    def soul_for_context(self) -> str:
        """Format soul aspects as markdown for LLM context."""
        if self._soul_cache_valid and self._soul_cache is not None:
            return self._soul_cache

        if not self._soul:
            self._soul_cache = ""
            self._soul_cache_valid = True
            return ""

        lines: list[str] = ["## Soul"]
        for sa in sorted(self._soul, key=lambda x: x.aspect):
            lines.append(f"\n### {sa.aspect}")
            lines.append(sa.content)

        result = "\n".join(lines)
        self._soul_cache = result
        self._soul_cache_valid = True
        return result

    # ── Persistence ───────────────────────────────────────────────────────

    def load(self) -> None:
        """Load facts and soul from JSON files."""
        self._facts = self._load_json("facts.json", Fact.from_dict)
        self._soul = self._load_json("soul.json", SoulAspect.from_dict)
        self._invalidate_cache()

    def save(self) -> None:
        """Persist facts and soul to JSON files."""
        if self._storage_dir is None:
            return
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        facts_path = self._storage_dir / "facts.json"
        facts_path.write_text(
            json.dumps([f.to_dict() for f in self._facts], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        soul_path = self._storage_dir / "soul.json"
        soul_path.write_text(
            json.dumps([s.to_dict() for s in self._soul], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Search ────────────────────────────────────────────────────────────

    def _keyword_search(self, query: str, limit: int) -> list[tuple[Fact, float]]:
        """Simple keyword search. Scores by fraction of query words matched."""
        query_words = set(re.findall(r"\w+", query.lower()))
        if not query_words:
            return []

        results: list[tuple[Fact, float]] = []
        for fact in self._facts:
            text = f"{fact.category} {fact.subject} {fact.content}".lower()
            text_words = set(re.findall(r"\w+", text))
            overlap = query_words & text_words
            if overlap:
                score = len(overlap) / len(query_words)
                results.append((fact, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    # ── Helpers ───────────────────────────────────────────────────────────

    def _invalidate_cache(self) -> None:
        self._facts_cache_valid = False
        self._soul_cache_valid = False

    def _load_json(self, filename: str, factory) -> list:
        if self._storage_dir is None:
            return []
        path = self._storage_dir / filename
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [factory(item) for item in data]
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Failed to load %s: %s", filename, exc)
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
