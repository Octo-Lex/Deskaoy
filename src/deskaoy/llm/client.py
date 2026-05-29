"""SimpleLLMClient — minimal LLM adapter that AgentLoop can drive.

Implements the 3 methods AgentLoop needs:
  - propose_action(prompt) → dict
  - create_plan(instruction, tools) → list[dict]
  - replan(**kwargs) → list[dict]

Supports OpenAI and Anthropic APIs. Provider is auto-detected from
environment variables (OPENAI_API_KEY / ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_ACTION_SYSTEM = (
    "You are a desktop automation agent. Given the current state and tool API, "
    "decide the next action. Respond with a SINGLE JSON object:\n"
    '- {"action": "click", "params": {"target": "element name or ref"}}\n'
    '- {"action": "type_text", "params": {"text": "...", "target": "..."}}\n'
    '- {"action": "fill", "params": {"target": "...", "value": "..."}}\n'
    '- {"action": "key_press", "params": {"key": "Enter"}}\n'
    '- {"action": "scroll", "params": {"direction": "down", "amount": 3}}\n'
    '- {"action": "screenshot", "params": {}}\n'
    '- {"action": "snapshot", "params": {}}\n'
    '- {"done": true} when the task is complete.\n\n'
    "IMPORTANT: Return ONLY valid JSON. No markdown, no explanation."
)

_PLAN_SYSTEM = (
    "You are a desktop automation planner. Break the instruction into "
    "concrete steps using the available tools. Respond with a JSON array:\n"
    '[{"description": "step 1"}, {"description": "step 2"}, ...]\n\n'
    "IMPORTANT: Return ONLY valid JSON. No markdown, no explanation."
)

# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

@dataclass
class LLMUsage:
    """Token usage accumulator."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0
    total_latency_ms: float = 0.0

    def record(self, prompt: int, completion: int, latency_ms: float) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.request_count += 1
        self.total_latency_ms += latency_ms


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict | list | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` blocks
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } or [ ... ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start >= 0:
            # Find matching close
            depth = 0
            for i in range(start, len(text)):
                if text[i] == start_char:
                    depth += 1
                elif text[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break

    return None


# ---------------------------------------------------------------------------
# SimpleLLMClient
# ---------------------------------------------------------------------------

class SimpleLLMClient:
    """Minimal LLM client for AgentLoop.

    Supports OpenAI and Anthropic chat completion APIs.
    Provider is auto-detected from environment variables:
      - OPENAI_API_KEY → uses OpenAI
      - ANTHROPIC_API_KEY → uses Anthropic
      - Both set → prefers OpenAI

    Usage:
        client = SimpleLLMClient()  # auto-detect
        response = await client.propose_action("Click the Submit button")
    """

    def __init__(
        self,
        provider: str = "auto",
        model: str | None = None,
        timeout: float = 30.0,
        api_key: str | None = None,
    ) -> None:
        self._timeout = timeout
        self._usage = LLMUsage()
        self._provider: str | None = None
        self._model: str | None = None
        self._client: Any = None

        # Resolve provider
        if provider == "auto":
            if api_key or os.environ.get("OPENAI_API_KEY"):
                provider = "openai"
            elif os.environ.get("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            else:
                logger.warning(
                    "No API key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
                )
                return

        if provider == "openai":
            self._init_openai(model, api_key)
        elif provider == "anthropic":
            self._init_anthropic(model, api_key)
        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'openai' or 'anthropic'.")

    def _init_openai(self, model: str | None, api_key: str | None) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("openai package not installed. pip install openai")
            return
        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client = OpenAI(api_key=key)
        self._provider = "openai"
        self._model = model or "gpt-4o-mini"
        logger.info("SimpleLLMClient: OpenAI %s", self._model)

    def _init_anthropic(self, model: str | None, api_key: str | None) -> None:
        try:
            import anthropic
        except ImportError:
            logger.error("anthropic package not installed. pip install anthropic")
            return
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = anthropic.Anthropic(api_key=key)
        self._provider = "anthropic"
        self._model = model or "claude-haiku-4-20250414"
        logger.info("SimpleLLMClient: Anthropic %s", self._model)

    @property
    def provider(self) -> str | None:
        return self._provider

    @property
    def model(self) -> str | None:
        return self._model

    @property
    def usage(self) -> LLMUsage:
        return self._usage

    @property
    def is_ready(self) -> bool:
        return self._client is not None

    # ─── Core API (what AgentLoop needs) ────────────────

    async def propose_action(self, prompt: str) -> dict:
        """Ask the LLM for the next action given the current state."""
        if not self.is_ready:
            logger.warning("No LLM client configured; returning done.")
            return {"done": True}

        start = time.monotonic()
        try:
            raw = await self._chat(
                system=_ACTION_SYSTEM,
                user=prompt,
            )
            (time.monotonic() - start) * 1000

            parsed = _extract_json(raw)
            if parsed is None:
                logger.warning("LLM returned unparseable response: %s", raw[:200])
                return {"done": True}

            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and parsed:
                return parsed[0] if isinstance(parsed[0], dict) else {"done": True}

            return {"done": True}

        except Exception as exc:
            logger.exception("propose_action failed: %s", exc)
            return {"done": True}

    async def create_plan(self, instruction: str, tools: str) -> list[dict]:
        """Ask the LLM to break an instruction into steps."""
        if not self.is_ready:
            return [{"description": instruction}]

        user = f"Instruction: {instruction}\n\nAvailable tools:\n{tools}"
        try:
            raw = await self._chat(system=_PLAN_SYSTEM, user=user)
            parsed = _extract_json(raw)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
            return [{"description": instruction}]
        except Exception as exc:
            logger.exception("create_plan failed: %s", exc)
            return [{"description": instruction}]

    async def replan(self, **kwargs: Any) -> list[dict]:
        """Re-plan after stagnation or error."""
        instruction = kwargs.get("instruction", "retry")
        tools = kwargs.get("tools", "")
        completed = kwargs.get("completed_steps", [])
        errors = kwargs.get("errors", [])

        if not self.is_ready:
            return [{"description": instruction}]

        user = (
            f"Original instruction: {instruction}\n"
            f"Completed steps: {completed}\n"
            f"Errors: {errors}\n\n"
            f"Available tools:\n{tools}\n\n"
            "Create a revised plan to complete the instruction."
        )
        try:
            raw = await self._chat(system=_PLAN_SYSTEM, user=user)
            parsed = _extract_json(raw)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
            return [{"description": instruction}]
        except Exception:
            return [{"description": instruction}]

    # ─── Internal ───────────────────────────────────────

    async def _chat(self, system: str, user: str) -> str:
        """Send a chat completion request. Returns raw text content."""
        start = time.monotonic()

        if self._provider == "openai":
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            latency = (time.monotonic() - start) * 1000
            usage = response.usage
            if usage:
                self._usage.record(
                    usage.prompt_tokens or 0,
                    usage.completion_tokens or 0,
                    latency,
                )
            return response.choices[0].message.content or ""

        if self._provider == "anthropic":
            response = await asyncio.to_thread(
                self._client.messages.create,
                model=self._model,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=0.1,
                max_tokens=1024,
            )
            latency = (time.monotonic() - start) * 1000
            self._usage.record(
                response.usage.input_tokens,
                response.usage.output_tokens,
                latency,
            )
            # Anthropic returns list of content blocks
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "".join(text_blocks)

        raise RuntimeError(f"Unknown provider: {self._provider}")
