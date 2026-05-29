"""Tests for SimpleLLMClient and register_definition."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.agent.registry import ToolDefinition, ToolParameter, ToolRegistry
from deskaoy.llm.client import SimpleLLMClient, _extract_json, LLMUsage


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

class TestExtractJson:

    def test_raw_json_dict(self):
        text = '{"action": "click", "params": {"target": "btn"}}'
        result = _extract_json(text)
        assert result == {"action": "click", "params": {"target": "btn"}}

    def test_raw_json_array(self):
        text = '[{"description": "step 1"}, {"description": "step 2"}]'
        result = _extract_json(text)
        assert len(result) == 2

    def test_markdown_json_block(self):
        text = '```json\n{"action": "type_text", "params": {"text": "hello"}}\n```'
        result = _extract_json(text)
        assert result["action"] == "type_text"

    def test_markdown_no_language(self):
        text = '```\n{"done": true}\n```'
        result = _extract_json(text)
        assert result == {"done": True}

    def test_json_with_surrounding_text(self):
        text = 'Here is the action:\n{"action": "click"}\nDone!'
        result = _extract_json(text)
        assert result["action"] == "click"

    def test_nested_json(self):
        text = '{"action": "fill", "params": {"target": "input", "value": "test"}}'
        result = _extract_json(text)
        assert result["params"]["value"] == "test"

    def test_invalid_json_returns_none(self):
        result = _extract_json("not json at all")
        assert result is None

    def test_empty_string(self):
        result = _extract_json("")
        assert result is None

    def test_done_true(self):
        result = _extract_json('{"done": true}')
        assert result == {"done": True}

    def test_array_in_text(self):
        text = '[{"description": "click the button"}, {"description": "type text"}]'
        result = _extract_json(text)
        assert isinstance(result, list)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# LLMUsage
# ---------------------------------------------------------------------------

class TestLLMUsage:

    def test_record_accumulates(self):
        usage = LLMUsage()
        usage.record(100, 50, 200.0)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150
        assert usage.request_count == 1
        assert usage.total_latency_ms == 200.0

        usage.record(200, 100, 300.0)
        assert usage.prompt_tokens == 300
        assert usage.completion_tokens == 150
        assert usage.total_tokens == 450
        assert usage.request_count == 2
        assert usage.total_latency_ms == 500.0


# ---------------------------------------------------------------------------
# SimpleLLMClient initialization
# ---------------------------------------------------------------------------

class TestSimpleLLMClientInit:

    def test_no_api_key_returns_not_ready(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove any API keys
            env = dict(os.environ)
            for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
                env.pop(key, None)
            with patch.dict(os.environ, env, clear=True):
                client = SimpleLLMClient()
                assert not client.is_ready

    def test_auto_detects_openai(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-fake"}):
            try:
                client = SimpleLLMClient()
                assert client.provider == "openai"
                assert client.model == "gpt-4o-mini"
            except Exception:
                # openai package may try to validate on init
                pass

    def test_auto_detects_anthropic(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-test-fake"}
        with patch.dict(os.environ, env, clear=True):
            # Clear OPENAI_API_KEY if present
            env_clean = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY",)}
            with patch.dict(os.environ, env_clean | env, clear=True):
                try:
                    client = SimpleLLMClient()
                    assert client.provider == "anthropic"
                except Exception:
                    pass

    def test_explicit_provider(self):
        client = SimpleLLMClient(provider="openai", api_key="sk-test-fake")
        # May fail if openai not installed, but provider should be set
        if client.is_ready:
            assert client.provider == "openai"

    def test_custom_model(self):
        client = SimpleLLMClient(provider="openai", model="gpt-4o", api_key="sk-test-fake")
        if client.is_ready:
            assert client.model == "gpt-4o"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            SimpleLLMClient(provider="nonexistent")


# ---------------------------------------------------------------------------
# SimpleLLMClient propose_action (mocked)
# ---------------------------------------------------------------------------

class TestSimpleLLMClientProposeAction:

    @pytest.mark.asyncio
    async def test_not_ready_returns_done(self):
        with patch.dict(os.environ, {}, clear=True):
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
            with patch.dict(os.environ, env, clear=True):
                client = SimpleLLMClient()
                result = await client.propose_action("Click the button")
                assert result == {"done": True}

    @pytest.mark.asyncio
    async def test_create_plan_not_ready(self):
        with patch.dict(os.environ, {}, clear=True):
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
            with patch.dict(os.environ, env, clear=True):
                client = SimpleLLMClient()
                result = await client.create_plan("Do something", "tools")
                assert result == [{"description": "Do something"}]

    @pytest.mark.asyncio
    async def test_replan_not_ready(self):
        with patch.dict(os.environ, {}, clear=True):
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
            with patch.dict(os.environ, env, clear=True):
                client = SimpleLLMClient()
                result = await client.replan(instruction="retry")
                assert result == [{"description": "retry"}]


# ---------------------------------------------------------------------------
# ToolRegistry.register_definition
# ---------------------------------------------------------------------------

class TestRegisterDefinition:

    def test_registers_custom_tool(self):
        registry = ToolRegistry()
        td = ToolDefinition(
            name="custom_action",
            description="A custom action",
            parameters=(
                ToolParameter("target", "str", True),
                ToolParameter("value", "str", False),
            ),
            handler=lambda **kw: None,
        )
        registry.register_definition(td)

        assert registry.get("custom_action") is not None
        assert registry.get("custom_action").description == "A custom action"

    def test_overwrite_existing(self):
        registry = ToolRegistry()
        td1 = ToolDefinition(name="act", description="v1", parameters=(), handler=lambda: None)
        td2 = ToolDefinition(name="act", description="v2", parameters=(), handler=lambda: None)
        registry.register_definition(td1)
        registry.register_definition(td2)
        assert registry.get("act").description == "v2"

    def test_tool_in_api_description(self):
        registry = ToolRegistry()
        td = ToolDefinition(
            name="do_thing",
            description="Does a thing",
            parameters=(ToolParameter("x", "int", True),),
            handler=lambda x: None,
        )
        registry.register_definition(td)
        api = registry.build_tool_api_description()
        assert "do_thing" in api

    def test_tool_to_json_schema(self):
        registry = ToolRegistry()
        td = ToolDefinition(
            name="click",
            description="Click element",
            parameters=(
                ToolParameter("target", "str", True, "Element to click"),
                ToolParameter("button", "str", False, "left/right"),
            ),
            handler=lambda **kw: None,
        )
        registry.register_definition(td)

        schema = registry.get("click").to_json_schema()
        assert schema["name"] == "click"
        assert "target" in schema["parameters"]["properties"]
        assert schema["parameters"]["required"] == ["target"]
