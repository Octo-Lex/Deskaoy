# v0.15: Routines + SKILL.md + Fact Extraction

> **v0.14.0 → v0.15.0** | ~9h | 3 workstreams
> **Sources:** Pocket Agent (routines, facts, soul), browser-use (SKILL.md)

---

## Overview

Three user-facing features that make the agent genuinely useful:

1. **Scheduled Routines** — "Every morning at 8am, check my calendar"
2. **SKILL.md Definitions** — Declarative capabilities in markdown
3. **Fact Extraction** — Build a user model from interactions

All three are independent modules under `src/agent_core/` with zero cross-dependencies between them. They wire into DesktopAgent as new subsystems.

---

## Workstream A: Scheduled Routines (~3h)

**Source:** Pocket Agent `src/memory/cron-jobs.ts`

### New file: `src/agent_core/routines/__init__.py`

```python
@dataclass
class Routine:
    name: str                        # "morning_check"
    schedule: str                    # cron expression or natural language
    prompt: str                      # "Check calendar and summarize today's events"
    channel: str = "default"         # routing hint for multi-app
    enabled: bool = True
    job_type: str = "routine"        # "routine" | "reminder"
    delete_after_run: bool = False
    context_messages: int = 0        # how many previous messages to include
    # Internal
    _id: int | None = None
    _next_run: float | None = None   # monotonic timestamp
    _last_run: float | None = None
    _run_count: int = 0

@dataclass
class RoutineExecution:
    routine_name: str
    started_at: float
    finished_at: float
    success: bool
    result_summary: str
    error: str = ""

class RoutineScheduler:
    """Schedule and execute routines on a cron-like basis.

    Uses no external deps — parses simplified cron expressions
    (minute hour day month weekday) and checks against system clock.
    Stores routines in JSON file via StorageResolver.
    """

    def __init__(self, storage_dir: Path | None = None): ...

    def add(self, routine: Routine) -> str: ...
    def remove(self, name: str) -> bool: ...
    def enable(self, name: str) -> None: ...
    def disable(self, name: str) -> None: ...
    def list(self, enabled_only: bool = False) -> list[Routine]: ...

    def get_due(self) -> list[Routine]:
        """Return routines whose next_run <= now."""

    def mark_run(self, name: str) -> None:
        """Update _last_run, increment _run_count, compute _next_run."""

    def compute_next_run(self, schedule: str) -> float:
        """Parse cron expression → next monotonic timestamp.

        Supported formats:
          - "*/5 * * * *"    (standard 5-field cron)
          - "0 8 * * *"      (every day at 8am)
          - "30 9 * * 1-5"   (weekdays at 9:30am)
          - "every 5m"       (every 5 minutes)
          - "every 1h"       (every hour)
          - "@daily"         (once daily at midnight)
          - "@hourly"        (once per hour)
        """

    def load(self) -> None:
        """Load routines from JSON file."""

    def save(self) -> None:
        """Persist routines to JSON file."""
```

### Tests (~16)
- add routine assigns ID and computes next_run
- remove routine by name
- enable/disable routine
- list all vs enabled only
- compute_next_run for "0 8 * * *" (daily 8am)
- compute_next_run for "*/5 * * * *" (every 5 min)
- compute_next_run for "every 5m"
- compute_next_run for "@daily"
- get_due returns only past-due routines
- get_due empty when nothing due
- mark_run updates last_run and run_count
- mark_run computes new next_run
- delete_after_run auto-removes after execution
- save and load round-trip
- load from nonexistent file is empty
- RoutineExecution dataclass fields

---

## Workstream B: SKILL.md Definitions (~2h)

**Source:** browser-use `skills/open-source/SKILL.md`

### Design

A SKILL.md file describes a capability the agent can perform. It has:
- YAML frontmatter (name, description, triggers, allowed-tools)
- Markdown body (instructions, examples, constraints)

Our `SkillLoader` parses these files and registers them with the `PipelineRegistry`
as `PipelineDefinition` objects — so skills integrate seamlessly with the existing
pipeline fast-path.

### New file: `src/agent_core/skills/__init__.py`

(Update existing `src/agent_core/skills/` package)

### New file: `src/agent_core/skills/loader.py`

```python
@dataclass
class SkillTrigger:
    """When to activate this skill."""
    type: str          # "keyword" | "regex" | "intent"
    pattern: str       # the keyword/regex/intent description
    case_sensitive: bool = False

@dataclass
class SkillDefinition:
    """Parsed SKILL.md contents."""
    name: str
    description: str
    triggers: list[SkillTrigger]
    allowed_tools: list[str]
    instructions: str          # Raw markdown body
    constraints: list[str]     # Extracted "## Constraints" section
    examples: list[str]        # Extracted "## Examples" section
    source_path: str = ""      # Where the SKILL.md was loaded from

class SkillLoader:
    """Load SKILL.md files from a directory.

    Directory structure:
      skills/
        my-skill/
          SKILL.md
        another-skill/
          SKILL.md
    """

    def __init__(self, skills_dir: Path | None = None): ...

    def discover(self) -> list[SkillDefinition]:
        """Scan skills_dir for SKILL.md files."""

    def load(self, path: Path) -> SkillDefinition:
        """Parse a single SKILL.md file.

        Frontmatter format (YAML):
          ---
          name: my-skill
          description: Type text into Notepad
          triggers:
            - type: keyword
              pattern: "notepad"
          allowed-tools: [click, fill, key_press, snapshot]
          ---

        Body is free-form markdown with optional sections:
          - ## Instructions / ## Steps
          - ## Constraints
          - ## Examples
        """

    def to_pipeline(self, skill: SkillDefinition) -> PipelineDefinition | None:
        """Convert a skill to a PipelineDefinition for the fast-path.

        Only possible if the skill has a ## Steps section with
        structured action definitions. Otherwise returns None
        (skill is instruction-only, used by the LLM path).
        """

    def match(self, instruction: str) -> SkillDefinition | None:
        """Find a skill whose triggers match the instruction."""
```

### Built-in skills directory: `src/agent_core/skills/builtins/`

```
skills/builtins/
  desktop-basics/
    SKILL.md        # "click", "type", "scroll" basics
  desktop-screenshot/
    SKILL.md        # screenshot + OCR read
```

### Tests (~14)
- parse SKILL.md with full frontmatter
- parse SKILL.md with minimal frontmatter (name + description only)
- parse SKILL.md with no frontmatter → raises ValueError
- extract triggers from frontmatter
- extract allowed-tools from frontmatter
- extract ## Constraints section from body
- extract ## Examples section from body
- discover finds all SKILL.md files in directory
- discover empty directory returns []
- to_pipeline converts skill with ## Steps to PipelineDefinition
- to_pipeline returns None for instruction-only skill
- match by keyword trigger
- match by regex trigger
- match returns None when no triggers match
- duplicate skill name logs warning

---

## Workstream C: Fact Extraction (~4h)

**Source:** Pocket Agent `src/memory/facts.ts`, `src/memory/soul.ts`

### Design

Pocket Agent has three memory layers:
1. **Facts** — Atomic statements about the user (category/subject/content)
2. **Soul** — Persistent personality aspects (tone, preferences, values)
3. **Daily logs** — Timestamped journal of interactions

We adopt Facts + Soul. Daily logs are deferred (they need a running agent loop).

Facts are extracted from `ActionResult` data after execution. The LLM can also
extract facts directly from conversation context.

### New file: `src/agent_core/memory/facts.py`

```python
@dataclass
class Fact:
    """A single atomic fact about the user or environment."""
    category: str         # "user_info", "preferences", "projects", "people", "work", "notes"
    subject: str          # "partner_name", "coffee_preference", "current_project"
    content: str          # "Alice", "latte with oat milk", "AI-OS Desktop Agent"
    source: str = ""      # "conversation", "action_observation", "explicit"
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""

@dataclass
class SoulAspect:
    """A persistent personality/vibe aspect."""
    aspect: str           # "tone", "verbosity", "humor"
    content: str          # "concise and technical", "brief", "dry"
    updated_at: str = ""

class FactStore:
    """JSON-file-backed fact and soul storage.

    File layout:
      {storage_dir}/facts.json     — list of Fact dicts
      {storage_dir}/soul.json      — list of SoulAspect dicts

    Provides keyword search (no embedding deps).
    Upgrades to hybrid search if embeddings available (future).
    """

    def __init__(self, storage_dir: Path | None = None): ...

    # ─── Fact CRUD ──────────────────────────
    def save_fact(self, fact: Fact) -> str: ...
    def get_facts(self, category: str = "") -> list[Fact]: ...
    def search_facts(self, query: str, limit: int = 6) -> list[tuple[Fact, float]]: ...
    def delete_fact(self, category: str, subject: str) -> bool: ...
    def all_facts(self) -> list[Fact]: ...
    def fact_count(self) -> int: ...

    # ─── Soul CRUD ──────────────────────────
    def set_soul(self, aspect: str, content: str) -> None: ...
    def get_soul(self, aspect: str) -> SoulAspect | None: ...
    def all_soul(self) -> list[SoulAspect]: ...
    def delete_soul(self, aspect: str) -> bool: ...

    # ─── Context injection ──────────────────
    def facts_for_context(self) -> str:
        """Format all facts as markdown for LLM context injection.
        Grouped by category. Cached until mutation."""

    def soul_for_context(self) -> str:
        """Format soul aspects as markdown for LLM context."""

    # ─── Persistence ────────────────────────
    def load(self) -> None: ...
    def save(self) -> None: ...

    # ─── Search ─────────────────────────────
    def _keyword_search(self, query: str, limit: int) -> list[tuple[Fact, float]]: ...
```

### New file: `src/agent_core/memory/fact_extractor.py`

```python
@dataclass
class ExtractionPattern:
    """Pattern for extracting facts from action results."""
    category: str
    subject_template: str    # "working_directory" → extracts from result
    content_template: str    # "User is working in {domain}"
    trigger_conditions: list[str]  # ["result.ok == True", "action == 'fill'"]

class FactExtractor:
    """Extract facts from action results and conversation context.

    Two modes:
    1. Automatic: scans ActionResult after execution for extractable info
    2. Explicit: LLM calls a tool to save/forget facts
    """

    def __init__(self, store: FactStore): ...
    self._patterns: list[ExtractionPattern] = [...]

    def extract_from_result(
        self, action: str, target: str, result: ActionResult, context: dict = {}
    ) -> list[Fact]:
        """Auto-extract facts from an action result.

        Examples:
          - fill("email", "alice@work.com") → Fact("user_info", "email", "alice@work.com")
          - navigate("https://github.com/user/repo") → Fact("projects", "github_active", "user/repo")
          - fill on new domain → Fact("preferences", "form_fill", target)
        """

    def extract_from_instruction(
        self, instruction: str, context: dict = {}
    ) -> list[Fact]:
        """Extract explicit facts from user instruction text.

        Pattern: "my name is X" → Fact("user_info", "name", "X")
        Pattern: "I work at X" → Fact("work", "company", "X")
        Pattern: "open X" → Fact("preferences", "frequent_app", "X")
        """
```

### Wiring into DesktopAgent

```python
# In __init__:
self._fact_store = FactStore()
self._fact_extractor = FactExtractor(self._fact_store)

# In _execute_single_action (after action execution):
facts = self._fact_extractor.extract_from_result(
    goal.capability, params.get("target", ""), action_result
)
for fact in facts:
    self._fact_store.save_fact(fact)

# In _build_prompt (for automate):
facts_context = self._fact_store.facts_for_context()
soul_context = self._fact_store.soul_for_context()
if facts_context:
    prompt_parts.insert(0, facts_context)
if soul_context:
    prompt_parts.insert(0, soul_context)
```

### Tests (~18)
- save_fact creates new fact
- save_fact updates existing fact (same category+subject)
- get_facts filters by category
- search_facts keyword matching
- search_facts returns scored results
- delete_fact removes fact
- fact_count
- all_facts returns all
- set_soul creates aspect
- set_soul updates existing aspect
- get_soul returns aspect
- delete_soul removes aspect
- facts_for_context formats as markdown
- facts_for_context groups by category
- soul_for_context formats as markdown
- FactExtractor extracts from fill action
- FactExtractor extracts from navigate action
- FactExtractor extracts from instruction text
- FactExtractor skips non-extractable actions
- save/load round-trip persistence

---

## Execution Order

```
Step 1: A — Scheduled Routines          (~3h)   routines/ package + 16 tests
Step 2: B — SKILL.md Definitions        (~2h)   skills/loader.py + 14 tests
Step 3: C — Fact Extraction             (~4h)   memory/facts.py + memory/fact_extractor.py + 20 tests
Step 4: Wire all into DesktopAgent      (~30m)
Step 5: Full test suite → version bump
```

---

## Files Changed

| # | File | Action | Δ Lines |
|---|------|--------|---------|
| 1 | `src/agent_core/routines/__init__.py` | Create | ~200 |
| 2 | `src/agent_core/skills/loader.py` | Create | ~180 |
| 3 | `src/agent_core/skills/builtins/desktop-basics/SKILL.md` | Create | ~30 |
| 4 | `src/agent_core/skills/builtins/desktop-screenshot/SKILL.md` | Create | ~20 |
| 5 | `src/agent_core/memory/facts.py` | Create | ~200 |
| 6 | `src/agent_core/memory/fact_extractor.py` | Create | ~120 |
| 7 | `src/agent_core/desktop_agent.py` | Edit: wire A+B+C | +40 |
| 8 | `tests/test_routines/` | Create | ~200 |
| 9 | `tests/test_skills/test_loader.py` | Create | ~180 |
| 10 | `tests/test_memory/test_facts.py` | Create | ~220 |
| 11 | `tests/test_memory/test_fact_extractor.py` | Create | ~120 |
| 12 | `pyproject.toml` | Edit: bump v0.15.0 | +1 |

## Expected Outcome

| Metric | Before (v0.14.0) | After (v0.15.0) |
|--------|-------------------|------------------|
| Tests | 2,238 | ~2,288 |
| Scheduled automation | None | **Cron-based routines with JSON persistence** |
| Extensibility | Python pipelines only | **SKILL.md declarative definitions** |
| User model | Action-only memory | **Facts + Soul + auto-extraction** |
