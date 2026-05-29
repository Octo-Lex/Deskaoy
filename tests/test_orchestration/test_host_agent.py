"""Tests for HostAgent — multi-app orchestration coordinator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from deskaoy.orchestration.host_agent import HostAgent, OrchestratedResult, SubtaskDef
from deskaoy.orchestration.blackboard import Blackboard


class TestSubtaskDef:
    def test_construction(self):
        st = SubtaskDef(
            id=1, app="outlook",
            instruction="Read email",
            outputs=["email.subject"],
            depends_on=[],
        )
        assert st.id == 1
        assert st.app == "outlook"
        assert st.outputs == ["email.subject"]


class TestOrchestratedResult:
    def test_to_dict(self):
        r = OrchestratedResult(
            ok=True,
            instruction="test",
            subtasks=[],
            blackboard_snapshot={"k": "v"},
            total_duration_ms=100.0,
            decomposition_source="template",
        )
        d = r.to_dict()
        assert d["ok"] is True
        assert d["blackboard_snapshot"]["k"] == "v"
        assert d["decomposition_source"] == "template"


class TestHostAgent:
    @pytest.mark.asyncio
    async def test_template_match_orchestration(self):
        """HostAgent matches a template and executes without LLM."""
        host = HostAgent(llm=None)
        result = await host.orchestrate("Read email and create a task")
        # Template match should work
        assert result.decomposition_source == "template"
        assert len(result.subtasks) == 2  # email_to_task has 2 subtasks

    @pytest.mark.asyncio
    async def test_template_no_match_without_llm_fails(self):
        """HostAgent with no template match and no LLM fails gracefully."""
        host = HostAgent(llm=None)
        result = await host.orchestrate("Do something completely unknown xyzzy")
        assert result.ok is False
        assert result.decomposition_source == "none"
        assert "No LLM" in result.error

    @pytest.mark.asyncio
    async def test_llm_decomposition(self):
        """HostAgent uses LLM when no template matches."""
        llm = AsyncMock()
        llm.propose_action.return_value = {
            "subtasks": [
                {"id": 1, "app": "app1", "instruction": "Step 1", "outputs": ["x"], "depends_on": []},
                {"id": 2, "app": "app2", "instruction": "Step 2 with $x", "outputs": ["y"], "depends_on": [1]},
            ]
        }
        host = HostAgent(llm=llm)
        result = await host.orchestrate("Do custom multi-app workflow")
        assert result.decomposition_source == "llm"
        assert len(result.subtasks) == 2

    @pytest.mark.asyncio
    async def test_llm_decomposition_failure(self):
        """HostAgent handles LLM decomposition failure."""
        llm = AsyncMock()
        llm.propose_action.side_effect = RuntimeError("API error")
        host = HostAgent(llm=llm)
        result = await host.orchestrate("Do custom multi-app workflow")
        assert result.ok is False
        assert "Decomposition failed" in result.error

    @pytest.mark.asyncio
    async def test_llm_returns_empty_subtasks(self):
        """HostAgent handles LLM returning no subtasks."""
        llm = AsyncMock()
        llm.propose_action.return_value = {"subtasks": []}
        host = HostAgent(llm=llm)
        result = await host.orchestrate("Do custom multi-app workflow")
        assert result.ok is False
        assert "no subtasks" in result.error

    @pytest.mark.asyncio
    async def test_llm_json_string_response(self):
        """HostAgent parses JSON string response from LLM."""
        import json
        llm = AsyncMock()
        response = json.dumps({
            "subtasks": [
                {"id": 1, "app": "test", "instruction": "Do it", "outputs": [], "depends_on": []},
            ]
        })
        llm.propose_action.return_value = response
        host = HostAgent(llm=llm)
        result = await host.orchestrate("Do custom multi-app workflow")
        assert result.decomposition_source == "llm"

    @pytest.mark.asyncio
    async def test_total_duration_ms_recorded(self):
        host = HostAgent(llm=None)
        result = await host.orchestrate("Read email and create a task")
        assert result.total_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_blackboard_snapshot_populated(self):
        host = HostAgent(llm=None)
        result = await host.orchestrate("Read email and create a task")
        # With no-op agents, blackboard may be empty but key should exist
        assert isinstance(result.blackboard_snapshot, dict)

    @pytest.mark.asyncio
    async def test_screenshot_to_note_template(self):
        host = HostAgent(llm=None)
        result = await host.orchestrate("Take a screenshot and save as a note")
        assert result.decomposition_source == "template"
        assert len(result.subtasks) == 2

    @pytest.mark.asyncio
    async def test_copy_paste_template(self):
        host = HostAgent(llm=None)
        result = await host.orchestrate("Copy text from source and paste to destination")
        assert result.decomposition_source == "template"
        assert len(result.subtasks) == 2

    def test_parse_json_response_direct(self):
        host = HostAgent()
        data = host._parse_json_response('{"subtasks": []}')
        assert data == {"subtasks": []}

    def test_parse_json_response_markdown_block(self):
        host = HostAgent()
        data = host._parse_json_response('```json\n{"subtasks": []}\n```')
        assert data == {"subtasks": []}

    def test_parse_json_response_embedded(self):
        host = HostAgent()
        data = host._parse_json_response('Here is the plan: {"subtasks": [{"id": 1}]} done')
        assert "subtasks" in data

    def test_parse_json_response_invalid_raises(self):
        host = HostAgent()
        with pytest.raises(ValueError, match="Could not parse"):
            host._parse_json_response("not json at all")
