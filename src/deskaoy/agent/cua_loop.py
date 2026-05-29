"""CUA Loop — Computer Use Agent screenshot-based action loop.

Alternative to AgentLoop that uses the Computer Use Agent API (OpenAI CUA
or Anthropic computer_20241022) to drive desktop actions via screenshots.

The CUA loop:
  1. Takes a screenshot of the desktop
  2. Sends it to the CUA model with the instruction
  3. Model proposes an action (click, type, scroll, screenshot)
  4. Execute the action via the surface adapter
  5. Repeat until done or max steps

No external CUA SDK dependency — pure HTTP calls via the existing LLM client.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class CUAProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class CUAAction(StrEnum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    KEY = "key"
    SCROLL = "scroll"
    SCREENSHOT = "screenshot"
    WAIT = "wait"
    DONE = "done"


@dataclass
class CUAStep:
    """A single step in the CUA loop."""
    step_number: int
    action: CUAAction
    params: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    duration_ms: float = 0.0
    error: str | None = None
    reasoning: str = ""


@dataclass
class CUALoopResult:
    """Result of a complete CUA loop execution."""
    instruction: str
    steps: list[CUAStep] = field(default_factory=list)
    completion_reason: str = ""
    total_duration_ms: float = 0.0
    total_steps: int = 0
    provider: CUAProvider = CUAProvider.OPENAI


@dataclass
class CUAActionProposal:
    """A proposed action from the CUA model."""
    action: CUAAction
    params: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    done: bool = False


# ---------------------------------------------------------------------------
# Response Parsers
# ---------------------------------------------------------------------------

def parse_openai_cua_response(response: dict) -> CUAActionProposal:
    """Parse an OpenAI CUA tool call response.

    OpenAI CUA returns a tool_use with:
      - name: "computer_use_preview" or similar
      - input: {"action": "click", "coordinate": [100, 200]}
    """
    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        # Check for text response (task complete)
        content = response.get("content", "")
        if isinstance(content, str):
            return CUAActionProposal(action=CUAAction.DONE, reasoning=content, done=True)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return CUAActionProposal(action=CUAAction.DONE, reasoning=block.get("text", ""), done=True)
        return CUAActionProposal(action=CUAAction.DONE, done=True)

    call = tool_calls[0]
    function = call.get("function", {})
    name = function.get("name", "")
    arguments = function.get("arguments", {})

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}

    action_name = arguments.get("action", name)
    params = {}

    # Map coordinates
    if "coordinate" in arguments:
        coords = arguments["coordinate"]
        params["x"] = coords[0] if len(coords) > 0 else 0
        params["y"] = coords[1] if len(coords) > 1 else 0

    if "text" in arguments:
        params["text"] = arguments["text"]

    if "key" in arguments:
        params["key"] = arguments["key"]

    if "scroll_amount" in arguments or "delta" in arguments:
        params["amount"] = arguments.get("scroll_amount", arguments.get("delta", 3))

    if "start_coordinate" in arguments:
        params["start"] = arguments["start_coordinate"]

    # Map action name to enum
    action_map = {
        "click": CUAAction.CLICK,
        "double_click": CUAAction.DOUBLE_CLICK,
        "right_click": CUAAction.RIGHT_CLICK,
        "type": CUAAction.TYPE,
        "key": CUAAction.KEY,
        "scroll": CUAAction.SCROLL,
        "screenshot": CUAAction.SCREENSHOT,
        "wait": CUAAction.WAIT,
    }
    action = action_map.get(action_name, CUAAction.CLICK)

    return CUAActionProposal(action=action, params=params, reasoning=arguments.get("reasoning", ""))


def parse_anthropic_cua_response(response: dict) -> CUAActionProposal:
    """Parse an Anthropic computer tool use response.

    Anthropic returns content blocks:
      - type: "tool_use", name: "computer_20241022"
      - input: {"action": "left_click", "coordinate": [100, 200]}
    """
    content = response.get("content", [])

    for block in content:
        if not isinstance(block, dict):
            continue

        if block.get("type") == "tool_use" and "computer" in block.get("name", "").lower():
            inp = block.get("input", {})
            action_name = inp.get("action", "")
            params = {}

            if "coordinate" in inp:
                coords = inp["coordinate"]
                params["x"] = coords[0] if len(coords) > 0 else 0
                params["y"] = coords[1] if len(coords) > 1 else 0

            if "text" in inp:
                params["text"] = inp["text"]

            if "key" in inp:
                params["key"] = inp["key"]

            # Map Anthropic action names
            action_map = {
                "left_click": CUAAction.CLICK,
                "right_click": CUAAction.RIGHT_CLICK,
                "double_click": CUAAction.DOUBLE_CLICK,
                "middle_click": CUAAction.CLICK,
                "left_click_drag": CUAAction.CLICK,
                "type": CUAAction.TYPE,
                "key": CUAAction.KEY,
                "scroll_down": CUAAction.SCROLL,
                "scroll_up": CUAAction.SCROLL,
                "screenshot": CUAAction.SCREENSHOT,
                "wait": CUAAction.WAIT,
                "cursor_position": CUAAction.SCREENSHOT,
            }

            if "scroll" in action_name:
                params["direction"] = "down" if "down" in action_name else "up"
                params["amount"] = inp.get("scroll_amount", 3)

            action = action_map.get(action_name, CUAAction.CLICK)
            return CUAActionProposal(action=action, params=params)

        if block.get("type") == "text":
            return CUAActionProposal(action=CUAAction.DONE, reasoning=block.get("text", ""), done=True)

    return CUAActionProposal(action=CUAAction.DONE, done=True)


# ---------------------------------------------------------------------------
# CUA Loop
# ---------------------------------------------------------------------------

class CUALoop:
    """Screenshot-based Computer Use Agent loop.

    Usage::

        loop = CUALoop(adapter=adapter, provider=CUAProvider.OPENAI)
        result = await loop.run("Open Notepad and type Hello World")
    """

    def __init__(
        self,
        adapter: Any = None,
        *,
        provider: CUAProvider = CUAProvider.OPENAI,
        max_steps: int = 25,
        screenshot_interval: float = 1.0,
        api_key: str = "",
        model: str = "",
    ) -> None:
        self._adapter = adapter
        self._provider = provider
        self._max_steps = max_steps
        self._screenshot_interval = screenshot_interval
        self._api_key = api_key
        self._model = model

    async def run(self, instruction: str) -> CUALoopResult:
        """Execute the CUA loop for a given instruction.

        1. Take initial screenshot
        2. Send to CUA model
        3. Parse action proposal
        4. Execute action
        5. Repeat until done or max steps
        """
        start = time.monotonic()
        steps: list[CUAStep] = []
        completion_reason = "max_steps"

        for step_num in range(1, self._max_steps + 1):
            step_start = time.monotonic()

            try:
                # Take screenshot
                screenshot_b64 = await self._take_screenshot()

                # Get action proposal from CUA model
                proposal = await self._get_proposal(instruction, screenshot_b64, steps)

                if proposal.done:
                    steps.append(CUAStep(
                        step_number=step_num,
                        action=CUAAction.DONE,
                        reasoning=proposal.reasoning,
                        duration_ms=(time.monotonic() - step_start) * 1000,
                    ))
                    completion_reason = "success"
                    break

                # Execute the action
                result = await self._execute_action(proposal)
                duration_ms = (time.monotonic() - step_start) * 1000

                steps.append(CUAStep(
                    step_number=step_num,
                    action=proposal.action,
                    params=proposal.params,
                    result=result,
                    duration_ms=duration_ms,
                ))

            except Exception as exc:
                duration_ms = (time.monotonic() - step_start) * 1000
                steps.append(CUAStep(
                    step_number=step_num,
                    action=CUAAction.SCREENSHOT,
                    duration_ms=duration_ms,
                    error=str(exc),
                ))
                logger.warning("CUA step %d error: %s", step_num, exc)

        return CUALoopResult(
            instruction=instruction,
            steps=steps,
            completion_reason=completion_reason,
            total_duration_ms=(time.monotonic() - start) * 1000,
            total_steps=len(steps),
            provider=self._provider,
        )

    async def _take_screenshot(self) -> str:
        """Take a screenshot and return as base64 string."""
        if self._adapter:
            screenshot = await self._adapter.screenshot()
            if isinstance(screenshot, bytes):
                return base64.b64encode(screenshot).decode("ascii")
        return ""  # No screenshot available

    async def _get_proposal(self, instruction: str, screenshot_b64: str, steps: list[CUAStep]) -> CUAActionProposal:
        """Get action proposal from CUA model.

        If api_key is set, calls the real API. Otherwise returns stub.
        """
        if not self._api_key:
            return CUAActionProposal(action=CUAAction.DONE, done=True, reasoning="CUA stub — no API key configured")

        try:
            if self._provider == CUAProvider.OPENAI:
                return await self._call_openai(instruction, screenshot_b64, steps)
            elif self._provider == CUAProvider.ANTHROPIC:
                return await self._call_anthropic(instruction, screenshot_b64, steps)
        except Exception as exc:
            logger.error("CUA API call failed: %s", exc)
            return CUAActionProposal(action=CUAAction.DONE, done=True, reasoning=f"API error: {exc}")

        return CUAActionProposal(action=CUAAction.DONE, done=True, reasoning="Unknown provider")

    async def _call_openai(self, instruction: str, screenshot_b64: str, steps: list[CUAStep]) -> CUAActionProposal:
        """Call OpenAI CUA API."""
        import aiohttp
        model = self._model or "computer-use-preview"
        url = "https://api.openai.com/v1/responses"

        # Build message history from steps
        messages = [{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
        ]}]

        payload = {
            "model": model,
            "input": messages,
            "tools": [{"type": "computer_use_preview", "display_width": 1920, "display_height": 1080}],
            "truncation": "auto",
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                data = await resp.json()
                return parse_openai_cua_response(data.get("output", [{}])[-1] if isinstance(data.get("output"), list) else data)

    async def _call_anthropic(self, instruction: str, screenshot_b64: str, steps: list[CUAStep]) -> CUAActionProposal:
        """Call Anthropic computer use API."""
        import aiohttp
        model = self._model or "claude-sonnet-4-20250514"
        url = "https://api.anthropic.com/v1/messages"

        messages = [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}},
            {"type": "text", "text": instruction},
        ]}]

        payload = {
            "model": model,
            "max_tokens": 1024,
            "messages": messages,
            "tools": [{"type": "computer_20250124", "display_width_px": 1920, "display_height_px": 1080}],
        }

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                data = await resp.json()
                return parse_anthropic_cua_response(data)

    async def _execute_action(self, proposal: CUAActionProposal) -> Any:
        """Execute a proposed action via the surface adapter."""
        if not self._adapter:
            return None

        action = proposal.action
        params = proposal.params

        if action == CUAAction.CLICK:
            x, y = params.get("x", 0), params.get("y", 0)
            return await self._adapter.click(f"{x},{y}")
        elif action == CUAAction.TYPE:
            text = params.get("text", "")
            return await self._adapter.type_text(text)
        elif action == CUAAction.KEY:
            key = params.get("key", "")
            return await self._adapter.key_press(key)
        elif action == CUAAction.SCROLL:
            direction = params.get("direction", "down")
            return await self._adapter.scroll(direction)
        elif action == CUAAction.SCREENSHOT:
            return await self._adapter.screenshot()
        else:
            return None
