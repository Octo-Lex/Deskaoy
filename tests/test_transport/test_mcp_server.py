"""Tests for MCP transport (BATCH-05 TASK-04)."""
from __future__ import annotations

import pytest

from deskaoy.transport.mcp_server import MCPServer, _build_tools


class TestMCPTools:
    """TEST-05-04-01 through TEST-05-04-04."""

    def test_granular_tools_built(self):
        """TEST-05-04-01: Granular tools include core capabilities."""
        tools = _build_tools(compact=False)
        names = [t["name"] for t in tools]
        assert "click" in names
        assert "fill" in names
        assert "screenshot" in names
        assert len(tools) >= 10

    def test_compact_tools_built(self):
        """TEST-05-04-02: Compact mode returns 6 tools."""
        tools = _build_tools(compact=True)
        assert len(tools) == 6
        names = [t["name"] for t in tools]
        assert "computer" in names
        assert "task" in names

    def test_tool_schemas_valid(self):
        """TEST-05-04-03: All tools have valid JSON Schema."""
        tools = _build_tools(compact=False)
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            schema = tool.get("inputSchema", {})
            assert schema.get("type") == "object"
            assert "properties" in schema


class TestMCPServer:
    """TEST-05-04-05 through TEST-05-04-06."""

    @pytest.fixture
    def server(self):
        return MCPServer(compact=True)

    @pytest.mark.asyncio
    async def test_initialize(self, server):
        """TEST-05-04-05: initialize returns valid MCP response."""
        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        result = response["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == "deskaoy"

    @pytest.mark.asyncio
    async def test_tools_list(self, server):
        """TEST-05-04-06: tools/list returns tool definitions."""
        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        })
        tools = response["result"]["tools"]
        assert len(tools) == 6  # compact mode

    @pytest.mark.asyncio
    async def test_ping(self, server):
        """Ping returns empty result."""
        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "ping",
        })
        assert response["result"] == {}

    @pytest.mark.asyncio
    async def test_unknown_method(self, server):
        """Unknown method returns error."""
        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "unknown/method",
        })
        assert "error" in response
        assert response["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_notification_no_response(self, server):
        """Notifications return None (no response)."""
        response = await server.handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        assert response is None
