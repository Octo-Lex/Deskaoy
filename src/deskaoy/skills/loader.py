"""Skill loader — parse SKILL.md files into executable definitions.

Adopted from browser-use's SKILL.md pattern. A SKILL.md file describes
a capability in YAML frontmatter + markdown body. The loader discovers
them from a directory and integrates with the existing PipelineRegistry.

Directory structure::

    skills/
      my-skill/
        SKILL.md
      another-skill/
        SKILL.md
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from deskaoy.pipeline.types import PipelineDefinition, PipelineStep

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SkillTrigger:
    """When to activate this skill."""

    type: str  # "keyword" | "regex" | "intent"
    pattern: str
    case_sensitive: bool = False


@dataclass
class SkillDefinition:
    """Parsed SKILL.md contents."""

    name: str
    description: str
    triggers: list[SkillTrigger] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    instructions: str = ""
    constraints: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    source_path: str = ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL
)

_SECTION_RE = re.compile(
    r"^##\s+(.+)$", re.MULTILINE
)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body.

    Returns (frontmatter_dict, body_text).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    yaml_text = m.group(1)
    body = m.group(2)

    # Minimal YAML parser (no pyyaml dep needed for our flat structure)
    fm: dict = {}
    current_list_key: str | None = None
    current_list: list = []

    for line in yaml_text.split("\n"):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#") or not stripped:
            if current_list_key:
                fm[current_list_key] = current_list
                current_list_key = None
            continue

        # List item (- value)
        if stripped.startswith("- ") and current_list_key:
            current_list.append(stripped[2:].strip().strip('"').strip("'"))
            continue

        # Key: value
        if ":" in stripped:
            # Flush previous list
            if current_list_key:
                fm[current_list_key] = current_list

            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")

            if val == "":
                # Start of a list
                current_list_key = key
                current_list = []
            else:
                current_list_key = None
                fm[key] = val

    # Flush final list
    if current_list_key:
        fm[current_list_key] = current_list

    return fm, body


def _extract_section(body: str, heading: str) -> str:
    """Extract the text under a ## heading until the next ## or end."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(body)
    return m.group(1).strip() if m else ""


def _extract_list_section(body: str, heading: str) -> list[str]:
    """Extract bullet items under a ## heading."""
    text = _extract_section(body, heading)
    if not text:
        return []
    items = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            items.append(stripped[2:].strip())
        elif stripped:
            items.append(stripped)
    return items


def _parse_triggers(raw: list[str] | str) -> list[SkillTrigger]:
    """Parse triggers from frontmatter value.

    Accepts:
      - list of strings: ["keyword:notepad", "regex:open\\s+notepad"]
      - list of dicts (already parsed): [{"type": "keyword", "pattern": "notepad"}]
    """
    if isinstance(raw, str):
        raw = [raw]

    triggers: list[SkillTrigger] = []
    for item in raw:
        if isinstance(item, dict):
            triggers.append(SkillTrigger(
                type=item.get("type", "keyword"),
                pattern=item.get("pattern", ""),
                case_sensitive=item.get("case_sensitive", False),
            ))
        elif isinstance(item, str):
            # Format: "type:pattern" or just a pattern (defaults to keyword)
            if ":" in item:
                t, _, p = item.partition(":")
                triggers.append(SkillTrigger(type=t.strip(), pattern=p.strip()))
            else:
                triggers.append(SkillTrigger(type="keyword", pattern=item.strip()))

    return triggers


def _parse_allowed_tools(raw: list[str] | str) -> list[str]:
    if isinstance(raw, str):
        # "click, fill, key_press" or "[click, fill]"
        raw = raw.strip("[]")
        return [t.strip().strip('"').strip("'") for t in raw.split(",") if t.strip()]
    return list(raw)


def load_skill(path: Path) -> SkillDefinition:
    """Parse a single SKILL.md file.

    Raises ``ValueError`` if required fields (name, description) are missing.
    """
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)

    name = fm.get("name", "")
    description = fm.get("description", "")

    if not name:
        raise ValueError(f"SKILL.md at {path} missing required 'name' field")
    if not description:
        raise ValueError(f"SKILL.md at {path} missing required 'description' field")

    raw_triggers = fm.get("triggers", [])
    triggers = _parse_triggers(raw_triggers) if raw_triggers else []

    raw_tools = fm.get("allowed-tools", [])
    allowed_tools = _parse_allowed_tools(raw_tools) if raw_tools else []

    # Extract sections from body
    instructions = _extract_section(body, "Instructions") or _extract_section(body, "Steps") or body.strip()
    constraints = _extract_list_section(body, "Constraints")
    examples = _extract_list_section(body, "Examples")

    return SkillDefinition(
        name=name,
        description=description,
        triggers=triggers,
        allowed_tools=allowed_tools,
        instructions=instructions,
        constraints=constraints,
        examples=examples,
        source_path=str(path),
    )


# ---------------------------------------------------------------------------
# SkillLoader
# ---------------------------------------------------------------------------


class SkillLoader:
    """Load SKILL.md files from a directory."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._skills_dir = skills_dir
        self._skills: dict[str, SkillDefinition] = {}

    def discover(self) -> list[SkillDefinition]:
        """Scan skills_dir for SKILL.md files."""
        if self._skills_dir is None or not self._skills_dir.exists():
            return []

        self._skills = {}
        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                skill = load_skill(skill_file)
                if skill.name in self._skills:
                    logger.warning("Duplicate skill name %r — overwriting", skill.name)
                self._skills[skill.name] = skill
            except ValueError as exc:
                logger.warning("Skipping invalid skill: %s", exc)

        return list(self._skills.values())

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def load(self, path: Path) -> SkillDefinition:
        """Parse a single SKILL.md file and register it."""
        skill = load_skill(path)
        self._skills[skill.name] = skill
        return skill

    def match(self, instruction: str) -> SkillDefinition | None:
        """Find a skill whose triggers match the instruction."""
        inst_lower = instruction.lower()

        for skill in self._skills.values():
            for trigger in skill.triggers:
                if trigger.type == "keyword":
                    pattern = trigger.pattern if trigger.case_sensitive else trigger.pattern.lower()
                    text = instruction if trigger.case_sensitive else inst_lower
                    if pattern in text:
                        return skill
                elif trigger.type == "regex":
                    flags = 0 if trigger.case_sensitive else re.IGNORECASE
                    if re.search(trigger.pattern, instruction, flags):
                        return skill
                elif trigger.type == "intent":
                    # Intent matching is fuzzy — check if pattern words appear
                    pattern_lower = trigger.pattern.lower()
                    words = pattern_lower.split()
                    if any(w in inst_lower for w in words):
                        return skill

        return None

    def to_pipeline(self, skill: SkillDefinition) -> PipelineDefinition | None:
        """Convert a skill to a PipelineDefinition for the fast-path.

        Only possible if the skill instructions contain structured action
        definitions in the format::

            ## Steps
            - action: click
              target: button.submit
            - action: fill
              target: input.email
              value: "{{email}}"

        Otherwise returns ``None`` (skill is instruction-only, used by LLM).
        """
        steps_text = _extract_section(skill.instructions, "Steps") if "## Steps" not in skill.instructions else ""
        # If instructions IS the steps section, check the raw source
        if not steps_text and skill.source_path:
            try:
                raw = Path(skill.source_path).read_text(encoding="utf-8")
                _, body = _parse_frontmatter(raw)
                steps_text = _extract_section(body, "Steps")
            except (OSError, ValueError):
                pass

        if not steps_text:
            return None

        # Parse structured steps: "- action: X" lines
        steps: list[PipelineStep] = []
        current_step: dict | None = None

        for line in steps_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("- action:"):
                if current_step:
                    steps.append(PipelineStep(
                        action=current_step.get("action", ""),
                        params=current_step.get("params", {}),
                    ))
                action_name = stripped.split(":", 1)[1].strip()
                current_step = {"action": action_name, "params": {}}
            elif current_step and stripped.startswith("target:"):
                current_step["params"]["target"] = stripped.split(":", 1)[1].strip()
            elif current_step and stripped.startswith("value:"):
                current_step["params"]["value"] = stripped.split(":", 1)[1].strip()

        if current_step:
            steps.append(PipelineStep(
                action=current_step.get("action", ""),
                params=current_step.get("params", {}),
            ))

        if not steps:
            return None

        return PipelineDefinition(
            name=skill.name,
            description=skill.description,
            steps=steps,
        )

    @property
    def count(self) -> int:
        return len(self._skills)

    @property
    def all_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())
