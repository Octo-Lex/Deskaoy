"""Typed result payloads for each action kind."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deskaoy.results.types import ActionMethod, CompletionReason


@dataclass
class ClickResult:
    target: str
    method: ActionMethod
    coordinates: tuple[float, float] | None = None
    element_tag: str | None = None
    page_changed: bool | None = None


@dataclass
class NavigateResult:
    url: str
    final_url: str
    status_code: int | None = None
    title: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    load_time_ms: float | None = None


@dataclass
class ExtractResult:
    selector: str
    extracted: Any
    schema_used: dict | None = None
    element_count: int = 0
    truncated: bool = False


@dataclass
class ScreenshotResult:
    image_hash: str
    width: int
    height: int
    format: str = "png"
    file_path: str | None = None
    base64_preview: str | None = None


@dataclass
class FillResult:
    selector: str
    value_entered: str
    method: ActionMethod
    character_count: int = 0
    clear_first: bool = True


@dataclass
class SelectResult:
    selector: str
    option: str
    method: ActionMethod
    by: str = "text"


@dataclass
class HoverResult:
    target: str
    method: ActionMethod
    coordinates: tuple[float, float] | None = None


@dataclass
class DragResult:
    source: str
    destination: str
    method: ActionMethod
    source_coords: tuple[float, float] | None = None
    dest_coords: tuple[float, float] | None = None


@dataclass
class ScrollResult:
    direction: str
    amount: int
    method: ActionMethod


@dataclass
class KeypressResult:
    key: str
    modifiers: int = 0


@dataclass
class JSEvalResult:
    expression: str
    result_type: str
    result: Any
    console_errors: list[str] = field(default_factory=list)


@dataclass
class DelegatedResult:
    instruction: str
    completion_reason: CompletionReason
    summary: str
    steps_executed: int
    budget_remaining: float
    execution_history: list[dict] = field(default_factory=list)


@dataclass
class SpilledResult:
    preview: str
    file_path: str
    original_type: str
    original_size_chars: int


# Tuple of all typed result classes for isinstance checks
TYPED_RESULT_TYPES = (
    ClickResult, NavigateResult, ExtractResult, ScreenshotResult,
    FillResult, SelectResult, HoverResult, DragResult, ScrollResult,
    KeypressResult, JSEvalResult, DelegatedResult, SpilledResult,
)
