"""Shape inference — summarize nested data as a flat path→type map.

Inspired by OpenCLI's ``shape.ts``.  Instead of sending a full JSON payload
to an LLM, we send a compact type descriptor so the model understands
*structure* without paying token cost for *content*.

Example::

    >>> infer_shape({"items": [{"title": "Hello", "score": 42}]})
    {'$.items': 'array(1)', '$.items[0].title': 'string', '$.items[0].score': 'number'}

The output is bounded by *max_bytes* — once the serialized shape exceeds
the budget, a ``"(truncated)"`` key is appended.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def infer_shape(
    value: Any,
    *,
    max_depth: int = 6,
    max_bytes: int = 2048,
) -> dict[str, str]:
    """Summarize *value* as a flat ``{path: type_descriptor}`` map.

    Parameters
    ----------
    value:
        Any JSON-serialisable Python value.
    max_depth:
        Maximum nesting depth to traverse.  Deeper nodes are described as
        ``"object"`` / ``"array"`` without expansion.
    max_bytes:
        Byte budget for the *output* map (serialized as JSON).  Once
        exceeded, ``{"(truncated)": "reached NB budget"}`` is appended.

    Returns
    -------
    dict[str, str]
        Flat path→type map.  Paths use ``$.`` JSONPath-style prefixes.
    """
    result: dict[str, str] = {}
    _walk(value, "$", result, depth=0, max_depth=max_depth, max_bytes=max_bytes)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _type_label(v: Any) -> str:
    """Return a compact type descriptor for a leaf value."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "number"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return f"string(len={len(v)})" if len(v) <= 120 else "string"
    return type(v).__name__


def _walk(
    value: Any,
    path: str,
    result: dict[str, str],
    *,
    depth: int,
    max_depth: int,
    max_bytes: int,
) -> None:
    """Recursively walk *value*, populating *result*."""
    # Budget check — once we exceed, stop
    if max_bytes > 0:
        try:
            serialized = json.dumps(result, default=str)
            if len(serialized.encode("utf-8")) >= max_bytes:
                result["(truncated)"] = f"reached {max_bytes}B budget"
                return
        except (TypeError, ValueError):
            pass

    # Leaf values
    if value is None or isinstance(value, (bool, int, float, str)):
        result[path] = _type_label(value)
        return

    # Lists / tuples
    if isinstance(value, (list, tuple)):
        result[path] = f"array({len(value)})"
        if depth >= max_depth:
            return
        # Expand first element + last if different, to show heterogeneity
        indices = _sample_indices(len(value))
        for i in indices:
            _walk(value[i], f"{path}[{i}]", result,
                  depth=depth + 1, max_depth=max_depth, max_bytes=max_bytes)
            # Abort if truncated marker appeared
            if "(truncated)" in result:
                return
        return

    # Dicts
    if isinstance(value, dict):
        result[path] = f"object({len(value)})"
        if depth >= max_depth:
            return
        for key in value:
            child_path = f"{path}.{key}" if path == "$" else f"{path}.{key}"
            _walk(value[key], child_path, result,
                  depth=depth + 1, max_depth=max_depth, max_bytes=max_bytes)
            if "(truncated)" in result:
                return
        return

    # Fallback for unknown types
    result[path] = _type_label(value)


def _sample_indices(length: int) -> list[int]:
    """Return representative indices to expand from a list.

    For short lists (≤5) return all.  Otherwise return first + last.
    """
    if length == 0:
        return []
    if length <= 5:
        return list(range(length))
    return [0, length - 1]
