"""Runtime Execution Hardening — AI-OS Batch 38 Alignment.

Implements the canonical preflight, attempt lifecycle, truthful receipts,
policy obligation enforcement, and adapter capability declarations that
Deskaoy requires to align with AI-OS's runtime execution hardening.

Reference: AI-OS Batch 38 Design Review
Gap Analysis: plans/AIOS-BATCH38-GAP-ANALYSIS.md
"""

from __future__ import annotations

from deskaoy.runtime.preflight import RuntimePreflight
from deskaoy.runtime.types import (
    AdapterCapabilities,
    PolicyObligation,
    PreflightCheck,
    PreflightResult,
    RuntimeAttempt,
    RuntimeAttemptState,
    RuntimeExecutionReceipt,
    RuntimeResourceBudget,
)

__all__ = [
    "RuntimeAttemptState",
    "RuntimeAttempt",
    "PolicyObligation",
    "AdapterCapabilities",
    "RuntimeResourceBudget",
    "RuntimeExecutionReceipt",
    "PreflightCheck",
    "PreflightResult",
    "RuntimePreflight",
]
