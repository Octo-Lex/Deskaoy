"""Visual feedback overlay for desktop automation.

Opt-in visual feedback system — click ripples, cursor trails,
scroll indicators, and element highlights — for user confidence
during automation.

Never enabled by default (HB-01). Must not interfere with
automation coordinates (HB-02).
"""

from deskaoy.feedback.engine import FeedbackEngine

__all__ = ["FeedbackEngine"]
