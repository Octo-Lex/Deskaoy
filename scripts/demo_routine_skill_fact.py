#!/usr/bin/env python3
"""Desktop Agent — Routines + Skills + Facts demo.

Demonstrates all v0.15 subsystems working together:
  1. Create a routine (scheduled task)
  2. Load a skill (SKILL.md-based trigger matching)
  3. Store a fact (extracted knowledge)
  4. Show facts and soul aspects
  5. Demonstrate skill matching against instruction

No real desktop, no real LLM, no network required.

Usage:
    python scripts/demo_routine_skill_fact.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Ensure project is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from deskaoy.routines import Routine, RoutineScheduler, compute_next_run
from deskaoy.skills.loader import SkillLoader, load_skill
from deskaoy.memory.facts import Fact, FactStore


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Desktop Agent — Routines + Skills + Facts Demo")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp(prefix="desktop-agent-demo-")

    # -- 1. Routines --------------------------------------
    print("\n--- 1. Routines ---")

    scheduler = RoutineScheduler(storage_dir=Path(tmpdir))

    morning_routine = Routine(
        name="morning-check",
        schedule="0 8 * * 1-5",  # 8am weekdays
        prompt="Check email and summarize new messages",
        enabled=True,
    )
    scheduler.add(morning_routine)
    print(f"  [OK] Added routine: {morning_routine.name}")
    print(f"    Schedule: {morning_routine.schedule} (8am Mon-Fri)")

    # Compute next run
    next_run = compute_next_run(morning_routine.schedule)
    print(f"    Next fire: {next_run}")

    # List routines
    routines = scheduler.list()
    print(f"  Total routines: {len(routines)}")
    for r in routines:
        print(f"    - {r.name}: {r.schedule}")

    # -- 2. Skills ----------------------------------------
    print("\n--- 2. Skills ---")

    loader = SkillLoader()

    # Load built-in skills
    skills_dir = Path(__file__).resolve().parent.parent / "src" / "deskaoy" / "skills" / "builtins"
    if skills_dir.exists():
        loader._skills_dir = skills_dir
        loader.discover()
        print(f"  [OK] Loaded skills from: {skills_dir}")

    skills = loader.list_skills() if hasattr(loader, 'list_skills') else loader.discover()
    print(f"  Total skills: {len(skills)}")
    for s in skills:
        name = getattr(s, 'name', '?')
        desc = getattr(s, 'description', '')
        print(f"    - {name}: {desc[:50]}")

    # Try matching
    instruction = "take a screenshot of the desktop and OCR it"
    match_result = loader.match(instruction) if hasattr(loader, 'match') else None
    if match_result:
        name = getattr(match_result, 'name', '?')
        print(f"\n  Instruction: '{instruction}'")
        print(f"  Matched skill: {name}")
    else:
        print(f"\n  No skill matched: '{instruction}'")
        print("  (Skill matching requires loaded skills with trigger patterns)")

    # -- 3. Facts ----------------------------------------
    print("\n--- 3. Facts ---")

    store = FactStore(storage_dir=Path(tmpdir))

    # Save some facts
    store.save_fact(Fact(
        category="preference",
        subject="theme",
        content="User prefers dark mode in all applications",
        confidence=0.95,
        source="conversation",
    ))
    print("  [OK] Saved fact: theme preference")

    store.save_fact(Fact(
        category="workflow",
        subject="morning_routine",
        content="User starts day by checking email, then calendar, then Slack",
        confidence=0.85,
        source="action_observation",
    ))
    print("  [OK] Saved fact: morning workflow")

    store.save_fact(Fact(
        category="preference",
        subject="browser",
        content="User prefers Chrome over Firefox",
        confidence=0.9,
        source="explicit",
    ))
    print("  [OK] Saved fact: browser preference")

    # List facts
    facts = store.get_facts()
    print(f"\n  Total facts: {len(facts)}")
    for f in facts:
        print(f"    [{f.category}] {f.subject}: {f.content[:50]} (conf: {f.confidence:.0%})")

    # Search facts
    results = store.search("theme") if hasattr(store, 'search') else []
    print(f"\n  Search 'theme': {len(results)} results")

    results = store.search("email") if hasattr(store, 'search') else []
    print(f"  Search 'email': {len(results)} results")

    # Soul aspects
    soul = store.get_soul_aspects() if hasattr(store, 'get_soul_aspects') else []
    print(f"\n  Soul aspects: {len(soul)}")

    # Context for LLM
    context = store.facts_for_context() if hasattr(store, 'facts_for_context') else ""
    if context:
        print(f"\n  Facts context (for LLM prompt):\n{'-' * 40}")
        print(f"  {context[:200]}...")
    else:
        print(f"\n  Facts context: (no context method)")

    # -- Summary ------------------------------------------
    print("\n" + "=" * 60)
    print("Demo complete.")
    print(f"  Routines: {len(routines)}")
    print(f"  Skills:   {len(skills)}")
    print(f"  Facts:    {len(facts)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
