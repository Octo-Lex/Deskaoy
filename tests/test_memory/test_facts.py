"""Tests for Fact + Soul store and Fact extractor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deskaoy.memory.facts import Fact, FactStore, SoulAspect
from deskaoy.memory.fact_extractor import FactExtractor, ExtractionPattern


# ═══════════════════════════════════════════════════════════════════════════
# Fact + Soul dataclass
# ═══════════════════════════════════════════════════════════════════════════

class TestFact:
    def test_to_dict(self):
        f = Fact(category="user_info", subject="name", content="Alice")
        d = f.to_dict()
        assert d["category"] == "user_info"
        assert d["subject"] == "name"
        assert d["content"] == "Alice"

    def test_from_dict(self):
        d = {"category": "work", "subject": "company", "content": "ACME",
             "source": "explicit", "confidence": 0.9}
        f = Fact.from_dict(d)
        assert f.category == "work"
        assert f.source == "explicit"
        assert f.confidence == 0.9

    def test_round_trip(self):
        f = Fact(category="prefs", subject="coffee", content="latte",
                 source="observation", confidence=0.7)
        f2 = Fact.from_dict(f.to_dict())
        assert f2.category == f.category
        assert f2.content == f.content


class TestSoulAspect:
    def test_to_dict(self):
        sa = SoulAspect(aspect="tone", content="concise")
        d = sa.to_dict()
        assert d["aspect"] == "tone"

    def test_from_dict(self):
        d = {"aspect": "verbosity", "content": "brief"}
        sa = SoulAspect.from_dict(d)
        assert sa.aspect == "verbosity"

    def test_round_trip(self):
        sa = SoulAspect(aspect="humor", content="dry")
        sa2 = SoulAspect.from_dict(sa.to_dict())
        assert sa2.content == sa.content


# ═══════════════════════════════════════════════════════════════════════════
# FactStore
# ═══════════════════════════════════════════════════════════════════════════

class TestFactStore:
    def _store(self, tmp: Path) -> FactStore:
        return FactStore(storage_dir=tmp)

    def test_save_fact_creates(self, tmp_path: Path):
        s = self._store(tmp_path)
        key = s.save_fact(Fact(category="user_info", subject="name", content="Alice"))
        assert key == "user_info/name"
        assert s.fact_count() == 1

    def test_save_fact_upserts(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="user_info", subject="name", content="Alice"))
        s.save_fact(Fact(category="user_info", subject="name", content="Bob"))
        assert s.fact_count() == 1
        assert s.all_facts()[0].content == "Bob"

    def test_get_facts_all(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="a", subject="1", content="x"))
        s.save_fact(Fact(category="b", subject="2", content="y"))
        assert len(s.get_facts()) == 2

    def test_get_facts_by_category(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="work", subject="company", content="ACME"))
        s.save_fact(Fact(category="user_info", subject="name", content="Alice"))
        assert len(s.get_facts("work")) == 1
        assert s.get_facts("work")[0].content == "ACME"

    def test_search_facts_keyword(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="user_info", subject="name", content="Alice Smith"))
        s.save_fact(Fact(category="work", subject="company", content="ACME Corp"))
        results = s.search_facts("Alice")
        assert len(results) == 1
        assert results[0][0].content == "Alice Smith"
        assert results[0][1] > 0

    def test_search_facts_no_match(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="x", subject="y", content="z"))
        assert s.search_facts("banana") == []

    def test_search_facts_limit(self, tmp_path: Path):
        s = self._store(tmp_path)
        for i in range(10):
            s.save_fact(Fact(category="x", subject=f"s{i}", content=f"item {i}"))
        results = s.search_facts("item", limit=3)
        assert len(results) == 3

    def test_delete_fact(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="x", subject="y", content="z"))
        assert s.delete_fact("x", "y") is True
        assert s.fact_count() == 0
        assert s.delete_fact("x", "y") is False

    def test_fact_count(self, tmp_path: Path):
        s = self._store(tmp_path)
        assert s.fact_count() == 0
        s.save_fact(Fact(category="x", subject="y", content="z"))
        assert s.fact_count() == 1

    def test_all_facts(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="a", subject="1", content="x"))
        s.save_fact(Fact(category="b", subject="2", content="y"))
        assert len(s.all_facts()) == 2


class TestFactStoreSoul:
    def _store(self, tmp: Path) -> FactStore:
        return FactStore(storage_dir=tmp)

    def test_set_soul_creates(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.set_soul("tone", "concise")
        assert len(s.all_soul()) == 1

    def test_set_soul_updates(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.set_soul("tone", "concise")
        s.set_soul("tone", "verbose and detailed")
        aspects = s.all_soul()
        assert len(aspects) == 1
        assert aspects[0].content == "verbose and detailed"

    def test_get_soul(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.set_soul("tone", "concise")
        sa = s.get_soul("tone")
        assert sa is not None
        assert sa.content == "concise"
        assert s.get_soul("nonexistent") is None

    def test_delete_soul(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.set_soul("tone", "concise")
        assert s.delete_soul("tone") is True
        assert len(s.all_soul()) == 0
        assert s.delete_soul("tone") is False


class TestFactStoreContext:
    def _store(self, tmp: Path) -> FactStore:
        return FactStore(storage_dir=tmp)

    def test_facts_for_context_empty(self, tmp_path: Path):
        s = self._store(tmp_path)
        assert s.facts_for_context() == ""

    def test_facts_for_context_groups(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="user_info", subject="name", content="Alice"))
        s.save_fact(Fact(category="user_info", subject="email", content="a@b.com"))
        s.save_fact(Fact(category="work", subject="company", content="ACME"))
        ctx = s.facts_for_context()
        assert "## Known Facts" in ctx
        assert "### user_info" in ctx
        assert "### work" in ctx
        assert "**name**: Alice" in ctx

    def test_facts_context_cached(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.save_fact(Fact(category="x", subject="y", content="z"))
        ctx1 = s.facts_for_context()
        ctx2 = s.facts_for_context()
        assert ctx1 == ctx2

    def test_soul_for_context(self, tmp_path: Path):
        s = self._store(tmp_path)
        s.set_soul("tone", "concise")
        ctx = s.soul_for_context()
        assert "## Soul" in ctx
        assert "### tone" in ctx

    def test_soul_for_context_empty(self, tmp_path: Path):
        s = self._store(tmp_path)
        assert s.soul_for_context() == ""


class TestFactStorePersistence:
    def test_save_load_roundtrip(self, tmp_path: Path):
        s = FactStore(storage_dir=tmp_path)
        s.save_fact(Fact(category="user_info", subject="name", content="Alice"))
        s.set_soul("tone", "concise")
        s.save()

        s2 = FactStore(storage_dir=tmp_path)
        s2.load()
        assert s2.fact_count() == 1
        assert s2.all_facts()[0].content == "Alice"
        assert len(s2.all_soul()) == 1
        assert s2.all_soul()[0].content == "concise"

    def test_load_missing_files(self, tmp_path: Path):
        s = FactStore(storage_dir=tmp_path)
        s.load()  # should not raise
        assert s.fact_count() == 0

    def test_load_corrupt_json(self, tmp_path: Path):
        (tmp_path / "facts.json").write_text("not json{{{")
        s = FactStore(storage_dir=tmp_path)
        s.load()
        assert s.fact_count() == 0

    def test_save_no_dir(self):
        s = FactStore()  # no storage_dir
        s.save_fact(Fact(category="x", subject="y", content="z"))
        s.save()  # should not raise


# ═══════════════════════════════════════════════════════════════════════════
# FactExtractor
# ═══════════════════════════════════════════════════════════════════════════

class TestFactExtractor:
    def test_extract_from_fill_email(self):
        ext = FactExtractor()
        facts = ext.extract_from_result("fill", "email_field", result_value="alice@work.com")
        assert len(facts) == 1
        assert facts[0].category == "user_info"
        assert facts[0].subject == "email"
        assert "alice@work.com" in facts[0].content
        assert facts[0].source == "action_observation"

    def test_extract_from_fill_name(self):
        ext = FactExtractor()
        facts = ext.extract_from_result("fill", "full_name", result_value="Alice Smith")
        assert len(facts) == 1
        assert facts[0].subject == "name"

    def test_extract_from_fill_phone(self):
        ext = FactExtractor()
        facts = ext.extract_from_result("fill", "phone_number", result_value="+1234567890")
        assert len(facts) == 1
        assert facts[0].subject == "phone"

    def test_extract_from_navigate(self):
        ext = FactExtractor()
        facts = ext.extract_from_result("navigate", "url", result_value="https://github.com/user/repo")
        assert len(facts) == 1
        assert facts[0].category == "projects"
        assert "github.com" in facts[0].content

    def test_extract_skips_junk_values(self):
        ext = FactExtractor()
        facts = ext.extract_from_result("fill", "email", result_value="test@test.com")
        assert len(facts) == 0

    def test_extract_skips_empty(self):
        ext = FactExtractor()
        facts = ext.extract_from_result("fill", "email", result_value="")
        assert len(facts) == 0

    def test_extract_non_matching_action(self):
        ext = FactExtractor()
        facts = ext.extract_from_result("click", "button", result_value="ok")
        assert len(facts) == 0

    def test_extract_non_matching_target(self):
        ext = FactExtractor()
        facts = ext.extract_from_result("fill", "search_box", result_value="hello")
        assert len(facts) == 0

    def test_extract_from_instruction_name(self):
        ext = FactExtractor()
        facts = ext.extract_from_instruction("my name is Alice and I need help")
        assert len(facts) == 1
        assert facts[0].category == "user_info"
        assert facts[0].content == "Alice"

    def test_extract_from_instruction_company(self):
        ext = FactExtractor()
        facts = ext.extract_from_instruction("I work at ACME Corp.")
        assert len(facts) == 1
        assert facts[0].subject == "company"

    def test_extract_from_instruction_preference(self):
        ext = FactExtractor()
        facts = ext.extract_from_instruction("I prefer dark mode.")
        assert len(facts) == 1
        assert facts[0].category == "preferences"

    def test_extract_from_instruction_project(self):
        ext = FactExtractor()
        facts = ext.extract_from_instruction("I'm working on AI-OS Desktop Agent.")
        assert len(facts) == 1
        assert facts[0].subject == "current_project"

    def test_extract_from_instruction_no_match(self):
        ext = FactExtractor()
        facts = ext.extract_from_instruction("click the submit button")
        assert len(facts) == 0

    def test_custom_patterns(self):
        ext = FactExtractor(patterns=[
            ExtractionPattern(
                category="custom",
                subject_template="custom_field",
                content_template="Custom: {value}",
                action="fill",
                target_pattern="custom_input",
            )
        ])
        facts = ext.extract_from_result("fill", "custom_input", result_value="hello")
        assert len(facts) == 1
        assert facts[0].category == "custom"
