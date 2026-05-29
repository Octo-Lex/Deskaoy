"""agent-core — Surface-agnostic agent engine for the AI Operating System.

This package provides the cascade engine, recovery pipeline, visual verification,
VLM providers, loop detection, budget governance, and result envelope that work
on any GUI surface — not just browsers.

Surface-specific adapters (browser, macOS, Windows, Linux) implement the
SurfaceAdapter protocol and plug into the engine.

The DesktopAgent class implements the AI-OS Agent Protocol (v2.2) and wraps
the internal engine behind the platform contract.
"""

__version__ = "1.1.0"

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
