"""Two-Step Verifier — classify whether an action succeeded by comparing snapshots.

After each action, the agent captures a post-action snapshot and compares it
to the pre-action snapshot. The TwoStepVerifier classifies the outcome and
produces a confidence score and human-readable evidence.

Inspired by Clawd Cursor's 6-signal ground-truth verifier and Stagehand's
act-observe pattern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from deskaoy.cascade.differ import SnapshotDiff, SnapshotDiffer
from deskaoy.cascade.types import AXSnapshot

logger = logging.getLogger(__name__)

# Actions that typically add elements (menus, dialogs open)
_ADDING_ACTIONS = frozenset({"click"})  # click may open menus/dialogs

# Actions that typically remove elements (close, dismiss)
_REMOVING_ACTIONS = frozenset({"key_press"})

# Actions that typically change values (fill, type)
_VALUE_ACTIONS = frozenset({"fill", "type_text"})

# Actions that scroll — usually change viewport but not structure
_SCROLL_ACTIONS = frozenset({"scroll"})


@dataclass(frozen=True)
class TwoStepResult:
    """Result of verifying an action by comparing pre/post snapshots."""
    action_applied: bool       # Did the action appear to succeed?
    evidence: str              # Human-readable evidence
    diff: SnapshotDiff | None = None  # Structural diff
    confidence: float = 0.0    # 0.0–1.0 confidence score

    @property
    def is_conclusive(self) -> bool:
        """True if confidence is above the inconclusive threshold."""
        return self.confidence >= 0.5


class TwoStepVerifier:
    """Verify action outcomes by comparing pre/post snapshots.

    Usage::

        verifier = TwoStepVerifier()
        result = verifier.verify(before_snapshot, after_snapshot, "fill", "username")
        if result.action_applied:
            print(f"Success: {result.evidence}")
    """

    def __init__(self, differ: SnapshotDiffer | None = None) -> None:
        self._differ = differ or SnapshotDiffer()

    def verify(
        self,
        before: AXSnapshot,
        after: AXSnapshot,
        action: str,
        target: str = "",
    ) -> TwoStepResult:
        """Verify an action by comparing pre/post snapshots.

        Args:
            before: Pre-action accessibility snapshot.
            after: Post-action accessibility snapshot.
            action: Action name (click, fill, type_text, key_press, scroll).
            target: Target element description or ref.

        Returns:
            TwoStepResult with confidence and evidence.
        """
        diff = self._differ.diff(before, after)

        # If no changes at all, inconclusive
        if diff.is_empty:
            return TwoStepResult(
                action_applied=False,
                evidence=f"No changes detected after {action}",
                diff=diff,
                confidence=0.0,
            )

        # Classify by action type
        method = getattr(self, f"_verify_{action}", None)
        if method:
            return method(diff, target, action)

        # Generic verification for unknown actions
        return self._verify_generic(diff, target, action)

    def _verify_click(self, diff: SnapshotDiff, target: str, action: str) -> TwoStepResult:
        """Click may open/close menus, dialogs, navigate, or toggle elements."""
        # Dialog/menu appeared → high confidence click worked
        if diff.added:
            for node in diff.added:
                if node.role in ("dialog", "menu", "alertdialog", "popup"):
                    return TwoStepResult(
                        action_applied=True,
                        evidence=f"Click opened {node.role}: '{node.name or 'unnamed'}'",
                        diff=diff,
                        confidence=0.9,
                    )

        # Dialog/menu closed → high confidence
        if diff.removed:
            for node in diff.removed:
                if node.role in ("dialog", "menu", "alertdialog", "popup"):
                    return TwoStepResult(
                        action_applied=True,
                        evidence=f"Click closed {node.role}: '{node.name or 'unnamed'}'",
                        diff=diff,
                        confidence=0.9,
                    )

        # Focus changed → moderate confidence
        focus_changes = [c for c in diff.changed if c.field == "focused"]
        if focus_changes:
            return TwoStepResult(
                action_applied=True,
                evidence=f"Focus shifted after click ({len(focus_changes)} element(s))",
                diff=diff,
                confidence=0.6,
            )

        # Some structural change → low-moderate confidence
        if self._differ.is_significant(diff):
            return TwoStepResult(
                action_applied=True,
                evidence=f"Structural changes after click: +{len(diff.added)} -{len(diff.removed)} ~{len(diff.changed)}",
                diff=diff,
                confidence=0.5,
            )

        # Only trivial changes
        return TwoStepResult(
            action_applied=False,
            evidence=f"Click on '{target}' produced no significant changes",
            diff=diff,
            confidence=0.3,
        )

    def _verify_fill(self, diff: SnapshotDiff, target: str, action: str) -> TwoStepResult:
        """Fill changes the value of a target element."""
        # Value changed → high confidence
        value_changes = [c for c in diff.changed if c.field == "value"]
        if value_changes:
            change = value_changes[0]
            return TwoStepResult(
                action_applied=True,
                evidence=f"Value changed: {change.before!r} → {change.after!r}",
                diff=diff,
                confidence=0.95,
            )

        # Focus changed (element got focus for typing)
        focus_changes = [c for c in diff.changed if c.field == "focused"]
        if focus_changes:
            return TwoStepResult(
                action_applied=True,
                evidence="Element focused after fill",
                diff=diff,
                confidence=0.6,
            )

        return TwoStepResult(
            action_applied=False,
            evidence=f"Fill on '{target}' produced no value change",
            diff=diff,
            confidence=0.2,
        )

    def _verify_type_text(self, diff: SnapshotDiff, target: str, action: str) -> TwoStepResult:
        """Type text appends to element value."""
        value_changes = [c for c in diff.changed if c.field == "value"]
        if value_changes:
            change = value_changes[0]
            # Check that the new value is longer (text was appended)
            if len(change.after) > len(change.before):
                return TwoStepResult(
                    action_applied=True,
                    evidence=f"Text appended: value grew from {len(change.before)} to {len(change.after)} chars",
                    diff=diff,
                    confidence=0.9,
                )
            return TwoStepResult(
                action_applied=True,
                evidence=f"Value changed: {change.before!r} → {change.after!r}",
                diff=diff,
                confidence=0.8,
            )

        return TwoStepResult(
            action_applied=False,
            evidence="Type text produced no value change",
            diff=diff,
            confidence=0.2,
        )

    def _verify_key_press(self, diff: SnapshotDiff, target: str, action: str) -> TwoStepResult:
        """Key press may navigate, submit, dismiss, etc."""
        if diff.removed:
            for node in diff.removed:
                if node.role in ("dialog", "menu", "popup"):
                    return TwoStepResult(
                        action_applied=True,
                        evidence=f"Key press dismissed {node.role}: '{node.name or 'unnamed'}'",
                        diff=diff,
                        confidence=0.85,
                    )

        if diff.added:
            for node in diff.added:
                if node.role in ("dialog", "menu", "alertdialog"):
                    return TwoStepResult(
                        action_applied=True,
                        evidence=f"Key press opened {node.role}: '{node.name or 'unnamed'}'",
                        diff=diff,
                        confidence=0.8,
                    )

        value_changes = [c for c in diff.changed if c.field == "value"]
        if value_changes:
            return TwoStepResult(
                action_applied=True,
                evidence="Key press changed value",
                diff=diff,
                confidence=0.7,
            )

        return self._verify_generic(diff, target, action)

    def _verify_scroll(self, diff: SnapshotDiff, target: str, action: str) -> TwoStepResult:
        """Scroll changes viewport — detect by bounds/content changes."""
        if diff.changed:
            return TwoStepResult(
                action_applied=True,
                evidence=f"Scroll produced {len(diff.changed)} state changes",
                diff=diff,
                confidence=0.6,
            )

        if diff.added or diff.removed:
            return TwoStepResult(
                action_applied=True,
                evidence=f"Scroll changed visible elements: +{len(diff.added)} -{len(diff.removed)}",
                diff=diff,
                confidence=0.7,
            )

        return TwoStepResult(
            action_applied=False,
            evidence="Scroll produced no visible changes",
            diff=diff,
            confidence=0.3,
        )

    def _verify_generic(self, diff: SnapshotDiff, target: str, action: str) -> TwoStepResult:
        """Generic verification for any action with changes."""
        if self._differ.is_significant(diff):
            return TwoStepResult(
                action_applied=True,
                evidence=f"{action} produced changes: +{len(diff.added)} -{len(diff.removed)} ~{len(diff.changed)}",
                diff=diff,
                confidence=0.5,
            )

        return TwoStepResult(
            action_applied=True,
            evidence=f"{action} produced minor changes: {len(diff.changed)} field(s) updated",
            diff=diff,
            confidence=0.3,
        )
