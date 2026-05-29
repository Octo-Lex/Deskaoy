"""Tests for SKILL.md loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from deskaoy.skills.loader import (
    SkillDefinition,
    SkillLoader,
    SkillTrigger,
    load_skill,
    _parse_frontmatter,
    _parse_triggers,
    _parse_allowed_tools,
    _extract_section,
    _extract_list_section,
)


# ═══════════════════════════════════════════════════════════════════════════
# Unit: frontmatter parsing
# ═══════════════════════════════════════════════════════════════════════════

class TestParseFrontmatter:
    def test_full_frontmatter(self):
        text = textwrap.dedent("""\
        ---
        name: my-skill
        description: A test skill
        ---
        Body text here.
        """)
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "my-skill"
        assert fm["description"] == "A test skill"
        assert "Body text here" in body

    def test_minimal_frontmatter(self):
        text = textwrap.dedent("""\
        ---
        name: test
        description: minimal
        ---
        """)
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "test"

    def test_no_frontmatter(self):
        text = "Just markdown body"
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert body == "Just markdown body"

    def test_frontmatter_with_list(self):
        text = textwrap.dedent("""\
        ---
        name: skill
        description: test
        triggers:
          - keyword:notepad
          - keyword:type
        ---
        body
        """)
        fm, body = _parse_frontmatter(text)
        assert "triggers" in fm
        assert isinstance(fm["triggers"], list)
        assert len(fm["triggers"]) == 2

    def test_frontmatter_with_quoted_values(self):
        text = textwrap.dedent("""\
        ---
        name: "quoted-skill"
        description: 'has quotes'
        ---
        body
        """)
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "quoted-skill"
        assert fm["description"] == "has quotes"


class TestParseTriggers:
    def test_keyword_trigger(self):
        triggers = _parse_triggers(["keyword:notepad"])
        assert len(triggers) == 1
        assert triggers[0].type == "keyword"
        assert triggers[0].pattern == "notepad"

    def test_regex_trigger(self):
        triggers = _parse_triggers(["regex:open\\s+notepad"])
        assert triggers[0].type == "regex"
        assert triggers[0].pattern == "open\\s+notepad"

    def test_bare_string_defaults_to_keyword(self):
        triggers = _parse_triggers(["notepad"])
        assert triggers[0].type == "keyword"

    def test_string_input(self):
        triggers = _parse_triggers("keyword:email")
        assert len(triggers) == 1
        assert triggers[0].pattern == "email"


class TestParseAllowedTools:
    def test_list_input(self):
        assert _parse_allowed_tools(["click", "fill"]) == ["click", "fill"]

    def test_comma_string(self):
        assert _parse_allowed_tools("click, fill, key_press") == ["click", "fill", "key_press"]

    def test_bracketed_string(self):
        assert _parse_allowed_tools("[click, fill]") == ["click", "fill"]


class TestExtractSection:
    def test_extract_instructions(self):
        body = "## Instructions\nDo this.\n## Constraints\nDon't do that."
        assert _extract_section(body, "Instructions") == "Do this."

    def test_extract_missing_section(self):
        body = "## Instructions\nDo this."
        assert _extract_section(body, "Constraints") == ""

    def test_extract_last_section(self):
        body = "## Instructions\nDo this.\n## More\nExtra."
        assert _extract_section(body, "More") == "Extra."


class TestExtractListSection:
    def test_bullet_items(self):
        body = "## Constraints\n- First\n- Second\n- Third"
        items = _extract_list_section(body, "Constraints")
        assert items == ["First", "Second", "Third"]

    def test_asterisk_items(self):
        body = "## Examples\n* One\n* Two"
        items = _extract_list_section(body, "Examples")
        assert items == ["One", "Two"]

    def test_empty_section(self):
        body = "## Constraints\n"
        items = _extract_list_section(body, "Constraints")
        assert items == []


# ═══════════════════════════════════════════════════════════════════════════
# Unit: load_skill
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadSkill:
    def test_full_skill(self, tmp_path: Path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
        ---
        name: test-skill
        description: A test skill
        triggers:
          - keyword:notepad
          - regex:open\\s+app
        allowed-tools:
          - click
          - fill
        ---
        # Test Skill

        ## Instructions
        Do the thing.

        ## Constraints
        - Be careful
        - No destructive actions

        ## Examples
        - Open Notepad and type hello
        """))
        skill = load_skill(skill_md)
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert len(skill.triggers) == 2
        assert skill.triggers[0].type == "keyword"
        assert skill.triggers[1].type == "regex"
        assert skill.allowed_tools == ["click", "fill"]
        assert "Do the thing" in skill.instructions
        assert skill.constraints == ["Be careful", "No destructive actions"]
        assert len(skill.examples) == 1
        assert skill.source_path == str(skill_md)

    def test_minimal_skill(self, tmp_path: Path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
        ---
        name: minimal
        description: Minimal skill
        ---
        Just instructions here.
        """))
        skill = load_skill(skill_md)
        assert skill.name == "minimal"
        assert skill.triggers == []
        assert skill.allowed_tools == []

    def test_missing_name_raises(self, tmp_path: Path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
        ---
        description: No name
        ---
        body
        """))
        with pytest.raises(ValueError, match="missing required 'name'"):
            load_skill(skill_md)

    def test_missing_description_raises(self, tmp_path: Path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
        ---
        name: has-name
        ---
        body
        """))
        with pytest.raises(ValueError, match="missing required 'description'"):
            load_skill(skill_md)


# ═══════════════════════════════════════════════════════════════════════════
# Integration: SkillLoader
# ═══════════════════════════════════════════════════════════════════════════

def _make_skill_dir(base: Path, name: str, content: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


class TestSkillLoader:
    def test_discover(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "skill-a", textwrap.dedent("""\
        ---
        name: skill-a
        description: First
        triggers:
          - keyword:alpha
        ---
        Body A
        """))
        _make_skill_dir(skills_dir, "skill-b", textwrap.dedent("""\
        ---
        name: skill-b
        description: Second
        triggers:
          - keyword:beta
        ---
        Body B
        """))

        loader = SkillLoader(skills_dir)
        found = loader.discover()
        assert len(found) == 2
        assert loader.count == 2

    def test_discover_empty_dir(self, tmp_path: Path):
        loader = SkillLoader(tmp_path / "nonexistent")
        found = loader.discover()
        assert found == []

    def test_discover_skips_invalid(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        # Valid skill
        _make_skill_dir(skills_dir, "valid", textwrap.dedent("""\
        ---
        name: valid
        description: Good
        ---
        Body
        """))
        # Invalid skill (missing description)
        d = skills_dir / "invalid"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: bad\n---\n")

        loader = SkillLoader(skills_dir)
        found = loader.discover()
        assert len(found) == 1
        assert found[0].name == "valid"

    def test_discover_duplicate_name_warns(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "a", textwrap.dedent("""\
        ---
        name: dup
        description: First
        ---
        A
        """))
        _make_skill_dir(skills_dir, "b", textwrap.dedent("""\
        ---
        name: dup
        description: Second
        ---
        B
        """))

        loader = SkillLoader(skills_dir)
        found = loader.discover()
        assert len(found) == 1
        # Last one wins
        assert loader.get("dup").description == "Second"

    def test_load_single(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(textwrap.dedent("""\
        ---
        name: loaded
        description: Loaded skill
        ---
        Body
        """))
        loader = SkillLoader()
        skill = loader.load(skill_file)
        assert skill.name == "loaded"
        assert loader.count == 1

    def test_match_keyword(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "notepad-skill", textwrap.dedent("""\
        ---
        name: notepad
        description: Notepad automation
        triggers:
          - keyword:notepad
        ---
        Body
        """))

        loader = SkillLoader(skills_dir)
        loader.discover()

        assert loader.match("open notepad and type hello") is not None
        assert loader.match("open chrome") is None

    def test_match_regex(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "regex-skill", textwrap.dedent("""\
        ---
        name: regex-skill
        description: Regex trigger
        triggers:
          - regex:open\\s+(notepad|calc)
        ---
        Body
        """))

        loader = SkillLoader(skills_dir)
        loader.discover()

        assert loader.match("open notepad") is not None
        assert loader.match("open calc") is not None
        assert loader.match("open chrome") is None

    def test_to_pipeline_with_steps(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(textwrap.dedent("""\
        ---
        name: structured
        description: Has steps
        ---
        ## Steps
        - action: click
          target: button.submit
        - action: fill
          target: input.email
          value: test@test.com
        """))

        loader = SkillLoader()
        skill = loader.load(skill_file)
        pipeline = loader.to_pipeline(skill)
        assert pipeline is not None
        assert pipeline.name == "structured"
        assert len(pipeline.steps) == 2
        assert pipeline.steps[0].action == "click"

    def test_to_pipeline_no_steps_returns_none(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(textwrap.dedent("""\
        ---
        name: freeform
        description: No structured steps
        ---
        Just freeform instructions.
        """))

        loader = SkillLoader()
        skill = loader.load(skill_file)
        assert loader.to_pipeline(skill) is None

    def test_all_skills(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "a", textwrap.dedent("""\
        ---
        name: a
        description: A
        ---
        A
        """))
        loader = SkillLoader(skills_dir)
        loader.discover()
        assert len(loader.all_skills) == 1
