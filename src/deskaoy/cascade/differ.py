"""Snapshot Differ — structural diff between two AXSnapshot objects.

Computes a deterministic diff between pre-action and post-action accessibility
tree snapshots. Used by TwoStepVerifier to classify action outcomes and by
AgentLoop to send only changed state to the LLM (token savings).

Pure Python — no external dependencies beyond cascade/types.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from deskaoy.cascade.types import AXNode, AXSnapshot

logger = logging.getLogger(__name__)

# Maximum number of changes to include in text output
_MAX_TEXT_CHANGES = 50

# Fields to check for changes (order matters for evidence)
_DIFF_FIELDS = ("value", "name", "disabled", "focused", "bounds")


@dataclass(frozen=True)
class NodeDiff:
    """A single field change in an element between two snapshots."""
    ref: str
    role: str
    field: str          # which field changed
    before: str         # previous value (stringified)
    after: str          # new value (stringified)

    def to_text(self) -> str:
        return f"[{self.ref}] <{self.role}> .{self.field}: {self.before!r} → {self.after!r}"


@dataclass
class SnapshotDiff:
    """Structural diff between two AXSnapshot objects."""
    added: list[AXNode] = field(default_factory=list)
    removed: list[AXNode] = field(default_factory=list)
    changed: list[NodeDiff] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed and not self.changed

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)


class SnapshotDiffer:
    """Compute structural diffs between AX snapshots.

    Usage::

        differ = SnapshotDiffer()
        diff = differ.diff(before_snapshot, after_snapshot)
        print(differ.diff_to_text(diff))
    """

    def diff(self, before: AXSnapshot, after: AXSnapshot) -> SnapshotDiff:
        """Compute the structural diff between two snapshots.

        Compares by element ref (e.g., "e1", "e42"):
          - Elements in 'after' but not 'before' → added
          - Elements in 'before' but not 'after' → removed
          - Elements in both with different fields → changed
        """
        added: list[AXNode] = []
        removed: list[AXNode] = []
        changed: list[NodeDiff] = []

        before_refs = set(before.nodes.keys())
        after_refs = set(after.nodes.keys())

        # Added elements
        for ref in sorted(after_refs - before_refs, key=_sort_ref):
            added.append(after.nodes[ref])

        # Removed elements
        for ref in sorted(before_refs - after_refs, key=_sort_ref):
            removed.append(before.nodes[ref])

        # Changed elements (present in both)
        for ref in sorted(before_refs & after_refs, key=_sort_ref):
            before_node = before.nodes[ref]
            after_node = after.nodes[ref]

            for field_name in _DIFF_FIELDS:
                before_val = _stringify(getattr(before_node, field_name, None))
                after_val = _stringify(getattr(after_node, field_name, None))

                if before_val != after_val:
                    changed.append(NodeDiff(
                        ref=ref,
                        role=after_node.role,
                        field=field_name,
                        before=before_val,
                        after=after_val,
                    ))

        return SnapshotDiff(added=added, removed=removed, changed=changed)

    def diff_to_text(self, diff: SnapshotDiff, *, max_changes: int = _MAX_TEXT_CHANGES) -> str:
        """Convert a SnapshotDiff to LLM-readable text.

        Format::

            DIFF: +2 added, -1 removed, ~3 changed
            + [e15] <button name="Submit" />
            - [e8] <dialog name="Confirm" />
            ~ [e3] <textbox .value: "" → "hello"
            ~ [e3] <textbox .focused: "False" → "True"
        """
        if diff.is_empty:
            return "DIFF: no changes detected"

        parts = [f"DIFF: +{len(diff.added)} added, -{len(diff.removed)} removed, ~{len(diff.changed)} changed"]

        total = 0
        for node in diff.added:
            if total >= max_changes:
                parts.append(f"  ... ({len(diff.added) - total} more additions truncated)")
                break
            parts.append(f"+ {_format_node(node)}")
            total += 1

        total = 0
        for node in diff.removed:
            if total >= max_changes:
                parts.append(f"  ... ({len(diff.removed) - total} more removals truncated)")
                break
            parts.append(f"- {_format_node(node)}")
            total += 1

        total = 0
        for change in diff.changed:
            if total >= max_changes:
                parts.append(f"  ... ({len(diff.changed) - total} more changes truncated)")
                break
            parts.append(f"~ {change.to_text()}")
            total += 1

        return "\n".join(parts)

    def is_significant(self, diff: SnapshotDiff) -> bool:
        """Return True if the diff contains meaningful changes.

        Ignores trivial changes like focus shifts unless there are
        structural changes (added/removed elements).
        """
        if diff.added or diff.removed:
            return True

        # Check for non-focus changes
        return any(change.field != "focused" for change in diff.changed)

    def has_value_change(self, diff: SnapshotDiff, ref: str) -> bool:
        """Check if a specific element had its value changed."""
        return any(c.ref == ref and c.field == "value" for c in diff.changed)

    def element_appeared(self, diff: SnapshotDiff, role: str = "", name_contains: str = "") -> bool:
        """Check if an element matching the criteria appeared in the diff."""
        for node in diff.added:
            if role and node.role != role:
                continue
            if name_contains and name_contains.lower() not in (node.name or "").lower():
                continue
            return True
        return False

    def element_disappeared(self, diff: SnapshotDiff, role: str = "", name_contains: str = "") -> bool:
        """Check if an element matching the criteria disappeared in the diff."""
        for node in diff.removed:
            if role and node.role != role:
                continue
            if name_contains and name_contains.lower() not in (node.name or "").lower():
                continue
            return True
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sort_ref(ref: str) -> int:
    """Sort refs numerically when possible."""
    digits = ref.lstrip("e")
    return int(digits) if digits.isdigit() else 0


def _stringify(value: object) -> str:
    """Convert any value to a comparable string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (tuple, list)):
        return str(value)
    return str(value)


def _format_node(node: AXNode) -> str:
    """Format a node for diff output."""
    parts = [f"[{node.ref}]", f"<{node.role}"]
    if node.name:
        parts.append(f'name="{node.name}"')
    if node.value:
        val = node.value if len(node.value) <= 80 else node.value[:77] + "..."
        parts.append(f'value="{val}"')
    return " ".join(parts) + " />"
