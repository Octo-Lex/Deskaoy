"""Tests for AppAgent — scoped single-app agent."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from deskaoy.orchestration.app_agent import AppAgent, AppAgentConfig, AppAgentResult
from deskaoy.orchestration.blackboard import Blackboard


class TestAppAgentConfig:
    def test_construction(self):
        cfg = AppAgentConfig(
            app_name="Outlook",
            window_title="Outlook",
            max_steps=5,
            reads=["email.subject"],
            writes=["task.url"],
        )
        assert cfg.app_name == "Outlook"
        assert cfg.max_steps == 5
        assert cfg.reads == ["email.subject"]
        assert cfg.writes == ["task.url"]

    def test_defaults(self):
        cfg = AppAgentConfig(app_name="Test")
        assert cfg.window_title == ""
        assert cfg.max_steps == 10
        assert cfg.reads == []
        assert cfg.writes == []


class TestAppAgentResult:
    def test_to_dict(self):
        r = AppAgentResult(
            ok=True, app_name="Outlook",
            summary="Read email", outputs={"x": 1},
            duration_ms=100.0, steps=2,
        )
        d = r.to_dict()
        assert d["ok"] is True
        assert d["app_name"] == "Outlook"
        assert d["outputs"]["x"] == 1


class TestAppAgent:
    @pytest.mark.asyncio
    async def test_execute_no_llm_no_surface(self):
        """AppAgent with no LLM/surface returns no-op result."""
        bb = Blackboard()
        cfg = AppAgentConfig(app_name="Test", writes=["output.key"])
        agent = AppAgent(config=cfg, blackboard=bb, llm=None, surface=None)
        result = await agent.execute("Do something")
        assert result.ok is True
        assert result.app_name == "Test"

    @pytest.mark.asyncio
    async def test_execute_reads_blackboard_inputs(self):
        """AppAgent reads declared blackboard keys before execution."""
        bb = Blackboard()
        bb.write("email.subject", "Hello", writer="other")

        cfg = AppAgentConfig(
            app_name="Notion",
            reads=["email.subject"],
            writes=["task.url"],
        )
        agent = AppAgent(config=cfg, blackboard=bb, llm=None, surface=None)
        result = await agent.execute("Create a task from the email")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_execute_writes_outputs_to_blackboard(self):
        """AppAgent writes declared outputs to the blackboard."""
        bb = Blackboard()

        # Mock LLM + surface that returns outputs
        llm = AsyncMock()
        llm.propose_action.return_value = {
            "action": "click",
            "params": {},
            "outputs": {"task.url": "https://notion.so/task/1"},
            "summary": "Created task",
        }
        surface = MagicMock()
        surface.click = MagicMock(return_value=MagicMock(ok=True))

        cfg = AppAgentConfig(
            app_name="Notion",
            writes=["task.url"],
        )
        agent = AppAgent(config=cfg, blackboard=bb, llm=llm, surface=surface)
        result = await agent.execute("Create a task")
        assert result.ok is True
        assert bb.read("task.url") == "https://notion.so/task/1"

    @pytest.mark.asyncio
    async def test_execute_handles_llm_error(self):
        """AppAgent handles LLM failure gracefully."""
        bb = Blackboard()
        llm = AsyncMock()
        llm.propose_action.side_effect = RuntimeError("API down")

        cfg = AppAgentConfig(app_name="Test")
        agent = AppAgent(config=cfg, blackboard=bb, llm=llm, surface=MagicMock())
        result = await agent.execute("Do something")
        assert result.ok is False
        assert "API down" in result.error

    @pytest.mark.asyncio
    async def test_execute_handles_no_action_proposed(self):
        """AppAgent handles empty LLM response."""
        bb = Blackboard()
        llm = AsyncMock()
        llm.propose_action.return_value = {"action": "", "params": {}}

        cfg = AppAgentConfig(app_name="Test")
        agent = AppAgent(config=cfg, blackboard=bb, llm=llm, surface=MagicMock())
        result = await agent.execute("Do something")
        assert result.ok is False
        assert "No action" in result.summary

    @pytest.mark.asyncio
    async def test_execute_handles_unknown_action(self):
        """AppAgent handles unknown surface action."""
        bb = Blackboard()
        llm = AsyncMock()
        llm.propose_action.return_value = {
            "action": "nonexistent_method",
            "params": {},
            "outputs": {},
            "summary": "Test",
        }
        surface = MagicMock(spec=[])  # No methods

        cfg = AppAgentConfig(app_name="Test")
        agent = AppAgent(config=cfg, blackboard=bb, llm=llm, surface=surface)
        result = await agent.execute("Do something")
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_app_name_property(self):
        bb = Blackboard()
        cfg = AppAgentConfig(app_name="Outlook")
        agent = AppAgent(config=cfg, blackboard=bb)
        assert agent.app_name == "Outlook"

    @pytest.mark.asyncio
    async def test_missing_read_input_doesnt_crash(self):
        """If a declared read key is not in blackboard, agent continues."""
        bb = Blackboard()
        cfg = AppAgentConfig(app_name="Test", reads=["missing.key"])
        agent = AppAgent(config=cfg, blackboard=bb, llm=None, surface=None)
        result = await agent.execute("Do something")
        assert result.ok is True  # No-op mode, still ok

    @pytest.mark.asyncio
    async def test_duration_ms_recorded(self):
        bb = Blackboard()
        cfg = AppAgentConfig(app_name="Test")
        agent = AppAgent(config=cfg, blackboard=bb, llm=None, surface=None)
        result = await agent.execute("Do something")
        assert result.duration_ms >= 0
