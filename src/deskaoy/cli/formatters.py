"""Output formatters for the deskaoy CLI.

Converts internal data structures to human-readable strings or raw JSON.
"""
from __future__ import annotations

import json
import sys
from typing import Any

# Re-export types needed (lazy — only used when formatting)
from deskaoy.os_types import (
    AgentEstimate,
    AgentResult,
    ResultStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_icon(status: ResultStatus) -> str:
    """Status icon that falls back to ASCII on non-UTF-8 terminals."""
    try:
        enc = (sys.stdout.encoding or 'ascii').lower().replace('-', '')
        use_unicode = enc == 'utf8'
    except Exception:
        use_unicode = False
    if not use_unicode:
        return {
            ResultStatus.SUCCESS: '+',
            ResultStatus.PARTIAL: '~',
            ResultStatus.FAILURE: 'x',
            ResultStatus.CANCELLED: 'X',
            ResultStatus.NEEDS_REVIEW: '!',
            ResultStatus.DRY_RUN: 'o',
            ResultStatus.RATE_LIMITED: '#',
            ResultStatus.RETRYABLE: 'r',
            ResultStatus.EMPTY_RESULTS: '0',
            ResultStatus.CONFIG_ERROR: 'c',
        }.get(status, '?')
    return {
        ResultStatus.SUCCESS: "✓",
        ResultStatus.PARTIAL: "◐",
        ResultStatus.FAILURE: "✗",
        ResultStatus.CANCELLED: "⊘",
        ResultStatus.NEEDS_REVIEW: "⚠",
        ResultStatus.DRY_RUN: "◎",
        ResultStatus.RATE_LIMITED: "⏱",
        ResultStatus.RETRYABLE: "↻",
        ResultStatus.EMPTY_RESULTS: "∅",
        ResultStatus.CONFIG_ERROR: "⚙",
    }.get(status, "?")


def _confidence_bar(score: float) -> str:
    """Visual confidence bar: [████░░░░░░] 40%"""
    filled = int(score * 10)
    empty = 10 - filled
    return f"[{'█' * filled}{'░' * empty}] {score:.0%}"


def _truncate(text: str, max_len: int = 80) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_result(result: AgentResult, *, json_mode: bool = False) -> str:
    """Format an AgentResult for terminal output."""
    if json_mode:
        return json.dumps(_result_to_dict(result), indent=2, default=str)

    icon = _status_icon(result.status)
    lines = [
        f"{icon} {result.status.value.upper()}",
        f"  Summary: {_truncate(result.summary)}",
    ]

    # Confidence
    if result.confidence.score > 0:
        lines.append(f"  Confidence: {_confidence_bar(result.confidence.score)}")
        if result.confidence.reason:
            lines.append(f"    Reason: {result.confidence.reason}")

    # Issues
    if result.issues:
        lines.append(f"  Issues ({len(result.issues)}):")
        for issue in result.issues[:3]:
            lines.append(f"    - [{issue.severity.value}] {issue.code.value}: {_truncate(issue.message)}")

    # Mutations
    if result.mutations:
        lines.append(f"  Mutations: {len(result.mutations)}")

    # Data preview
    if result.data:
        preview = json.dumps(result.data, default=str)[:120]
        lines.append(f"  Data: {preview}")

    return "\n".join(lines)


def format_estimate(estimate: AgentEstimate, *, json_mode: bool = False) -> str:
    """Format an AgentEstimate for terminal output."""
    if json_mode:
        return json.dumps(_estimate_to_dict(estimate), indent=2, default=str)

    lines = [
        "◎ ESTIMATE",
        f"  Cost: ${estimate.cost_usd:.4f}",
        f"  Latency: {estimate.latency_ms}ms",
        f"  Confidence: {_confidence_bar(estimate.confidence.score)}",
        f"  Can execute: {'Yes' if estimate.can_execute else 'No'}",
    ]

    if estimate.refusal_reason:
        lines.append(f"  Refusal: {estimate.refusal_reason}")

    if not estimate.provider_healthy:
        lines.append(f"  ⚠ Provider unhealthy: {estimate.degradation_note}")

    return "\n".join(lines)


def format_health(status: Any, *, json_mode: bool = False) -> str:
    """Format a HealthStatus for terminal output."""
    if json_mode:
        return json.dumps(_health_to_dict(status), indent=2, default=str)

    healthy = getattr(status, "healthy", False)
    icon = "✓" if healthy else "✗"
    lines = [f"{icon} Health: {'HEALTHY' if healthy else 'UNHEALTHY'}"]

    probes = getattr(status, "probes", None) or getattr(status, "details", None)
    if probes:
        if isinstance(probes, dict):
            for name, result in probes.items():
                if result is None:
                    # N/A — optional subsystem not configured
                    lines.append(f"  - {name}: not configured")
                elif isinstance(result, bool):
                    lines.append(f"  {'✓' if result else '✗'} {name}")
                else:
                    ok = getattr(result, "healthy", True)
                    lines.append(f"  {'✓' if ok else '✗'} {name}")
        elif isinstance(probes, (list, tuple)):
            for probe in probes:
                name = getattr(probe, "name", str(probe))
                ok = getattr(probe, "healthy", True)
                lines.append(f"  {'✓' if ok else '✗'} {name}")

    return "\n".join(lines)


def format_routine(routine: Any, *, json_mode: bool = False) -> str:
    """Format a Routine for listing."""
    if json_mode:
        return json.dumps(_routine_to_dict(routine), indent=2, default=str)

    name = getattr(routine, "name", "?")
    schedule = getattr(routine, "schedule", "?")
    instruction = getattr(routine, "instruction", "")
    enabled = getattr(routine, "enabled", True)

    status = "ON" if enabled else "OFF"
    lines = [
        f"  {name:<20} [{status}] {_truncate(schedule, 20):<20} {_truncate(instruction, 40)}"
    ]
    return "\n".join(lines)


def format_routine_header() -> str:
    """Column header for routine listing."""
    return f"  {'Name':<20} {'Status':<6} {'Schedule':<20} {'Instruction'}"
    return f"  {'─' * 20} {'─' * 6} {'─' * 20} {'─' * 40}"


def format_skill(skill: Any, *, json_mode: bool = False) -> str:
    """Format a SkillDefinition for listing."""
    if json_mode:
        return json.dumps(_skill_to_dict(skill), indent=2, default=str)

    name = getattr(skill, "name", "?")
    description = getattr(skill, "description", "")

    triggers = getattr(skill, "triggers", None)
    trigger_str = ""
    if triggers:
        parts = []
        for t in triggers[:3]:
            kw = getattr(t, "keyword", None) or getattr(t, "pattern", "")
            parts.append(kw)
        trigger_str = ", ".join(parts)

    lines = [f"  {name:<25} {_truncate(description, 50)}"]
    if trigger_str:
        lines.append(f"    Triggers: {trigger_str}")

    return "\n".join(lines)


def format_fact(fact: Any, *, json_mode: bool = False) -> str:
    """Format a Fact for listing."""
    if json_mode:
        return json.dumps(_fact_to_dict(fact), indent=2, default=str)

    category = getattr(fact, "category", "?")
    subject = getattr(fact, "subject", "?")
    content = getattr(fact, "content", "")
    confidence = getattr(fact, "confidence", 1.0)

    lines = [
        f"  [{category}] {subject}",
        f"    {_truncate(content, 70)}",
        f"    Confidence: {_confidence_bar(confidence)}",
    ]
    return "\n".join(lines)


def format_schema(schema: dict, *, json_mode: bool = False) -> str:
    """Format a capability schema as a table."""
    if json_mode:
        return json.dumps(schema, indent=2, default=str)

    lines = ["  Capability Schema:", ""]

    capabilities = schema.get("capabilities", {})
    if isinstance(capabilities, dict) and capabilities:
        lines.append(f"  {'Capability':<20} {'Action Class':<15} {'Methods'}")
        lines.append(f"  {'─' * 20} {'─' * 15} {'─' * 30}")
        for cap_name, cap_def in capabilities.items():
            action_class = cap_def.get("action_class", "?") if isinstance(cap_def, dict) else "?"
            methods = cap_def.get("methods", []) if isinstance(cap_def, dict) else []
            methods_str = ", ".join(methods[:5]) if methods else "-"
            lines.append(f"  {cap_name:<20} {action_class:<15} {methods_str}")
    else:
        lines.append("  (no capabilities defined)")

    return "\n".join(lines)


def format_snapshot_table(record: Any) -> str:
    """Format a SnapshotRecord as an element table."""
    elements = getattr(record, "elements", [])
    if not elements:
        return "  (no elements)"

    lines = [
        f"  {'ID':<6} {'Role':<15} {'Name':<30} {'Actionable'}",
        f"  {'─' * 6} {'─' * 15} {'─' * 30} {'─' * 10}",
    ]
    for elem in elements:
        eid = getattr(elem, "element_id", "?")
        role = getattr(elem, "role", "?")
        name = _truncate(getattr(elem, "name", "") or "", 28)
        actionable = "Yes" if getattr(elem, "actionable", False) else "No"
        lines.append(f"  {eid:<6} {role:<15} {name:<30} {actionable}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dict converters (for JSON mode)
# ---------------------------------------------------------------------------

def _result_to_dict(r: AgentResult) -> dict:
    return {
        "execution_id": r.execution_id,
        "status": r.status.value,
        "summary": r.summary,
        "data": r.data,
        "confidence": {
            "score": r.confidence.score,
            "reason": r.confidence.reason,
        },
        "issues": [
            {"severity": i.severity.value, "code": i.code.value, "message": i.message}
            for i in r.issues
        ],
        "mutations": [
            {"resource_type": m.resource_type, "operation": m.operation}
            for m in r.mutations
        ],
    }


def _estimate_to_dict(e: AgentEstimate) -> dict:
    return {
        "cost_usd": e.cost_usd,
        "latency_ms": e.latency_ms,
        "confidence": {"score": e.confidence.score, "reason": e.confidence.reason},
        "can_execute": e.can_execute,
        "requires_auth": e.requires_auth,
        "refusal_reason": e.refusal_reason,
        "provider_healthy": e.provider_healthy,
        "degradation_note": e.degradation_note,
    }


def _health_to_dict(h: Any) -> dict:
    if hasattr(h, "__dict__"):
        return {k: v for k, v in h.__dict__.items() if not k.startswith("_")}
    return {"healthy": getattr(h, "healthy", False)}


def _routine_to_dict(r: Any) -> dict:
    if hasattr(r, "__dict__"):
        return {k: v for k, v in r.__dict__.items() if not k.startswith("_")}
    return {"name": getattr(r, "name", "?"), "schedule": getattr(r, "schedule", "?")}


def _skill_to_dict(s: Any) -> dict:
    if hasattr(s, "__dict__"):
        return {k: v for k, v in s.__dict__.items() if not k.startswith("_")}
    return {"name": getattr(s, "name", "?"), "description": getattr(s, "description", "")}


def _fact_to_dict(f: Any) -> dict:
    if hasattr(f, "__dict__"):
        return {k: v for k, v in f.__dict__.items() if not k.startswith("_")}
    return {
        "category": getattr(f, "category", "?"),
        "subject": getattr(f, "subject", "?"),
        "content": getattr(f, "content", ""),
    }
