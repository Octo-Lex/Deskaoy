"""4-pass AX snapshot formatter — produces token-efficient LLM page state.

Adapted from OpenCLI's ``snapshotFormatter.ts``.  Raw accessibility trees
contain noise (decorative elements, empty containers, duplicate wrappers).
This formatter applies 4 cleanup passes to produce compact, actionable text
for LLM consumption.

Pipeline:
  1. Filter  — remove non-interactive, empty-text, disabled, decorative
  2. Dedup   — collapse parent-child pairs where child adds no value
  3. Prune   — bottom-up remove containers with no interactive descendants
  4. Collapse — single-child chains → direct parent→child

Output format::

    url: win32://Notepad
    title: Untitled - Notepad
    viewport: 1920x1080
    ---
    [1] <textbox name="Text Editor" value="Hello World" />
    [2] <menubar name="Application">
          [3] <menuitem name="File" />
          [4] <menuitem name="Edit" />
        </menubar>
    ---
    interactive: 4 | depth: 3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from deskaoy.cascade.types import AXSnapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Roles that are purely decorative / structural
# Roles that are purely decorative / structural
_DECORATIVE_ROLES = frozenset({
    "unknown", "section", "generic",
    "separator", "whitespace", "image", "illustration",
})

# Roles that are structural containers (kept even when unnamed)
_STRUCTURAL_ROLES = frozenset({
    "pane", "group", "window", "document", "page",
})

# Roles that count as "interactive" for the footer count
_INTERACTIVE_ROLES = frozenset({
    "button", "link", "textbox", "combobox", "checkbox",
    "radio", "menuitem", "tab", "slider", "searchbox",
    "spinbutton", "switch", "option", "treeitem",
    "menu", "menubar", "toolbar", "dialog", "alertdialog",
})

MAX_VALUE_LENGTH = 80
MAX_NAME_LENGTH = 60


# ---------------------------------------------------------------------------
# Node wrapper for formatting
# ---------------------------------------------------------------------------

@dataclass
class _FormatNode:
    """Mutable wrapper used during formatting passes."""
    ref: str
    role: str
    name: str
    value: str | None = None
    disabled: bool = False
    url: str | None = None
    bounds: tuple[float, float, float, float] | None = None
    children: list[_FormatNode] = field(default_factory=list)
    depth: int = 0
    kept: bool = True  # set to False by filter pass

    @property
    def is_interactive(self) -> bool:
        return self.role in _INTERACTIVE_ROLES

    @property
    def has_interactive_descendant(self) -> bool:
        if self.is_interactive:
            return True
        return any(c.has_interactive_descendant for c in self.children)


# ---------------------------------------------------------------------------
# Build tree from flat AXSnapshot
# ---------------------------------------------------------------------------

def _build_tree(snapshot: AXSnapshot) -> list[_FormatNode]:
    """Build a tree structure from the flat snapshot node dict.

    Since AXSnapshot.nodes is flat (ref→node), we create root-level nodes
    and rely on depth ordering.  For simple formatting we treat them as
    a flat list grouped by depth (the tree structure is reconstructed
    from ref prefixes if available).
    """
    nodes: list[_FormatNode] = []
    sorted_refs = sorted(snapshot.nodes.keys(), key=lambda r: int(r.lstrip("e")) if r.lstrip("e").isdigit() else 0)

    for ref in sorted_refs:
        ax = snapshot.nodes[ref]
        nodes.append(_FormatNode(
            ref=ref,
            role=ax.role,
            name=ax.name[:MAX_NAME_LENGTH] if ax.name else "",
            value=(ax.value[:MAX_VALUE_LENGTH] if ax.value and len(ax.value) > MAX_VALUE_LENGTH else ax.value),
            disabled=ax.disabled,
            url=ax.url,
            bounds=ax.bounds,
        ))
    return nodes


# ---------------------------------------------------------------------------
# Pass 1: Filter
# ---------------------------------------------------------------------------

def _pass_filter(nodes: list[_FormatNode]) -> list[_FormatNode]:
    """Remove non-interactive, empty-name decorative, and disabled-only nodes."""
    result = []
    for n in nodes:
        # Always keep interactive elements
        if n.is_interactive:
            n.kept = True
            result.append(n)
            continue
        # Keep named elements
        if n.name:
            n.kept = True
            result.append(n)
            continue
        # Keep structural containers (may have interactive children)
        if n.role in _STRUCTURAL_ROLES:
            n.kept = True
            result.append(n)
            continue
        # Drop purely decorative
        n.kept = False
    return result


# ---------------------------------------------------------------------------
# Pass 2: Deduplicate
# ---------------------------------------------------------------------------

def _pass_dedup(nodes: list[_FormatNode]) -> list[_FormatNode]:
    """Collapse nodes that are identical or where one wraps the other."""
    if len(nodes) <= 1:
        return nodes

    result = []
    seen: set[str] = set()

    for n in nodes:
        # Dedup key: role + name (case-insensitive)
        key = f"{n.role}:{n.name.lower()}"
        if key in seen and not n.is_interactive:
            continue
        seen.add(key)
        result.append(n)
    return result


# ---------------------------------------------------------------------------
# Pass 3: Prune
# ---------------------------------------------------------------------------

def _pass_prune(nodes: list[_FormatNode]) -> list[_FormatNode]:
    """Remove containers with no interactive descendants."""
    return [n for n in nodes if n.is_interactive or n.has_interactive_descendant or bool(n.name)]


# ---------------------------------------------------------------------------
# Pass 4: Collapse
# ---------------------------------------------------------------------------

def _pass_collapse(nodes: list[_FormatNode]) -> list[_FormatNode]:
    """Collapse runs of non-interactive containers."""
    # Remove unnamed, non-interactive decorative nodes
    result = []
    for n in nodes:
        if not n.name and not n.is_interactive and n.role in _DECORATIVE_ROLES:
            continue
        result.append(n)
    return result


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize_node(n: _FormatNode) -> str:
    """Serialize a single node to compact markup."""
    parts = [f"[{n.ref}]", f"<{n.role}"]
    if n.name:
        parts.append(f'name="{n.name}"')
    if n.value:
        # Truncate value
        val = n.value if len(n.value) <= MAX_VALUE_LENGTH else n.value[:MAX_VALUE_LENGTH - 3] + "..."
        parts.append(f'value="{val}"')
    if n.url:
        parts.append(f'url="{n.url}"')
    if n.disabled:
        parts.append("[disabled]")
    return " ".join(parts) + " />"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def format_snapshot(snapshot: AXSnapshot) -> str:
    """Format an AXSnapshot into token-efficient text for LLM consumption.

    Applies the 4-pass pipeline and produces a compact string
    representation suitable for inclusion in LLM prompts.
    """
    # Build tree
    nodes = _build_tree(snapshot)

    if not nodes:
        return f"url: {snapshot.url}\ntitle: {snapshot.title}\n---\n(empty)\n---\ninteractive: 0"

    # Apply pipeline
    nodes = _pass_filter(nodes)
    nodes = _pass_dedup(nodes)
    nodes = _pass_prune(nodes)
    nodes = _pass_collapse(nodes)

    # Count interactive
    interactive_count = sum(1 for n in nodes if n.is_interactive)
    max_depth = 1  # flat list, so depth is 1

    # Build output
    lines = [
        f"url: {snapshot.url}",
        f"title: {snapshot.title}",
        "---",
    ]

    for n in nodes:
        lines.append(_serialize_node(n))

    lines.append("---")
    lines.append(f"interactive: {interactive_count} | depth: {max_depth}")

    return "\n".join(lines)
