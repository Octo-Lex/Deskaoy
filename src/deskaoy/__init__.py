"""deskaoy — Surface-agnostic desktop agent for the AI Operating System.

This package provides the cascade engine, recovery pipeline, visual verification,
VLM providers, loop detection, budget governance, and result envelope that work
on any GUI surface.

Surface-specific adapters (Windows, Linux, macOS) implement the
SurfaceAdapter protocol and plug into the engine.

The DesktopAgent class implements the AI-OS Agent Protocol (v2.2) and wraps
the internal engine behind the platform contract.
"""

from deskaoy._version import resolve_version

# Resolve from installed package metadata when available; fall back to the
# hardcoded constant in source checkouts. See cli/version.py.
__version__ = resolve_version()

# AI-OS contract types — the boundary between agent and platform
# DesktopAgent — AI-OS Agent Protocol implementation
from deskaoy.desktop_agent import DesktopAgent
from deskaoy.os_types import (
    AgentContext,
    AgentEstimate,
    AgentGoal,
    AgentResult,
    CancellationToken,
    Confidence,
    ErrorCode,
    HealthCheckResult,
    Issue,
    IssueSeverity,
    Learning,
    MutationRecord,
    OperationCancelled,
    PaginatedResult,
    ResourceRef,
    RestoreMethod,
    ResultStatus,
    ReviewItem,
    Snapshot,
    SuggestedFollowup,
    ToolContext,
    ToolResult,
    UndoResult,
)
