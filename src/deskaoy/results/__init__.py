"""agent-core results — structured action results and output defense."""

from deskaoy.results.output import OutputBudgetConfig, OutputDefender
from deskaoy.results.typed import (
    ClickResult,
    DelegatedResult,
    DragResult,
    ExtractResult,
    FillResult,
    HoverResult,
    JSEvalResult,
    KeypressResult,
    NavigateResult,
    ScreenshotResult,
    ScrollResult,
    SelectResult,
    SpilledResult,
)
from deskaoy.results.types import (
    ActionError,
    ActionMethod,
    ActionResult,
    CompletionReason,
    ErrorCategory,
    ResultMeta,
    action_result,
    timed_action_result,
)

__all__ = [
    "ActionError", "ActionMethod", "ActionResult", "CompletionReason",
    "ErrorCategory", "ResultMeta", "action_result", "timed_action_result",
    "ClickResult", "DelegatedResult", "DragResult", "ExtractResult",
    "FillResult", "HoverResult", "JSEvalResult", "KeypressResult",
    "NavigateResult", "ScrollResult", "ScreenshotResult", "SelectResult",
    "SpilledResult",
    "OutputBudgetConfig", "OutputDefender",
]
