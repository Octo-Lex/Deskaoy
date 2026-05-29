"""Templates — pre-built orchestration patterns for common workflows.

Templates bypass LLM decomposition (zero cost, zero latency) for
known multi-app patterns. Each template declares trigger keywords
and a fixed subtask graph.

Usage:
    from deskaoy.orchestration.templates import match_template, TEMPLATES
    template = match_template("read email and create a task")
    # → {"subtasks": [...], "trigger": [...]}
"""

from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {
    "email_to_task": {
        "description": "Read an email and create a task from it",
        "trigger": ["email to task", "email and create", "email task", "read email create"],
        "subtasks": [
            {
                "id": 1,
                "app": "outlook",
                "instruction": "Read the latest email subject and body",
                "outputs": ["email.subject", "email.body"],
                "depends_on": [],
            },
            {
                "id": 2,
                "app": "notion",
                "instruction": "Create a task titled ${email.subject} with body ${email.body}",
                "outputs": ["task.url"],
                "depends_on": [1],
            },
        ],
    },
    "screenshot_to_note": {
        "description": "Take a screenshot and save it as a note",
        "trigger": ["screenshot to note", "screenshot and save", "capture and note"],
        "subtasks": [
            {
                "id": 1,
                "app": "desktop",
                "instruction": "Take a screenshot of the current screen",
                "outputs": ["screenshot.path"],
                "depends_on": [],
            },
            {
                "id": 2,
                "app": "notepad",
                "instruction": "Open Notepad and write 'Screenshot saved at ${screenshot.path}'",
                "outputs": ["note.saved"],
                "depends_on": [1],
            },
        ],
    },
    "copy_paste_between_apps": {
        "description": "Copy text from one app and paste into another",
        "trigger": ["copy from", "paste to", "copy and paste", "transfer text"],
        "subtasks": [
            {
                "id": 1,
                "app": "source",
                "instruction": "Select all text and copy to clipboard",
                "outputs": ["clipboard.text"],
                "depends_on": [],
            },
            {
                "id": 2,
                "app": "destination",
                "instruction": "Paste the clipboard text into the document",
                "outputs": ["paste.ok"],
                "depends_on": [1],
            },
        ],
    },
}


def match_template(instruction: str) -> dict[str, Any] | None:
    """Match an instruction to a known orchestration template.

    Returns the template dict if a match is found, None otherwise.
    Matching is case-insensitive word-level matching against trigger phrases.
    """
    instruction_lower = instruction.lower()
    # Split instruction into words for exact word matching
    instruction_words = set(instruction_lower.split())

    best_match: str | None = None
    best_score = 0

    for name, template in TEMPLATES.items():
        triggers = template.get("trigger", [])
        for trigger in triggers:
            # Count how many trigger words appear in the instruction
            trigger_words = trigger.lower().split()
            matches = sum(1 for w in trigger_words if w in instruction_words)
            score = matches / len(trigger_words) if trigger_words else 0

            if score > best_score and score >= 0.5:  # At least half the trigger words match
                best_score = score
                best_match = name

    if best_match is not None:
        return TEMPLATES[best_match]

    return None


def list_templates() -> list[dict[str, Any]]:
    """List all available templates with metadata."""
    return [
        {
            "name": name,
            "description": t["description"],
            "trigger_keywords": t["trigger"],
            "subtask_count": len(t["subtasks"]),
        }
        for name, t in TEMPLATES.items()
    ]
