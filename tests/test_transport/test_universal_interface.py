"""Tests for Universal Discovery Interface (describe).

Validates that Deskaoy's universal interface works correctly:
  - describe() returns the full discovery document
  - Every capability has input_schema and output_schema
  - schema() is a backward-compat alias for describe()
  - manifest.py is valid and version-synced
  - REST GET / returns the discovery document
  - MCP tools/describe returns the discovery document
  - Context passthrough works on REST and MCP
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from deskaoy.desktop_agent import DesktopAgent, CAPABILITIES, CAPABILITY_NAMES
from deskaoy.manifest import CAPABILITY_MANIFEST, validate_manifest


# ---------------------------------------------------------------------------
# 1. CAPABILITIES registry completeness
# ---------------------------------------------------------------------------

class TestCapabilitiesRegistry:
    """Every capability must have input_schema and output_schema."""

    ALL_CAPABILITIES = CAPABILITY_NAMES

    def test_capabilities_is_nonempty(self):
        assert len(CAPABILITIES) >= 10

    @pytest.mark.parametrize("name", ALL_CAPABILITIES)
    def test_has_description(self, name):
        assert CAPABILITIES[name]["description"]
        assert isinstance(CAPABILITIES[name]["description"], str)

    @pytest.mark.parametrize("name", ALL_CAPABILITIES)
    def test_has_action_class(self, name):
        valid_classes = {"read_only", "recoverable", "draftable", "sensitive", "external", "irreversible"}
        assert CAPABILITIES[name]["action_class"] in valid_classes

    @pytest.mark.parametrize("name", ALL_CAPABILITIES)
    def test_has_input_schema(self, name):
        schema = CAPABILITIES[name].get("input_schema")
        assert schema is not None, f"Capability '{name}' missing input_schema"
        assert schema["type"] == "object"
        assert "properties" in schema

    @pytest.mark.parametrize("name", ALL_CAPABILITIES)
    def test_has_output_schema(self, name):
        schema = CAPABILITIES[name].get("output_schema")
        assert schema is not None, f"Capability '{name}' missing output_schema"
        assert isinstance(schema, dict)

    @pytest.mark.parametrize("name", ALL_CAPABILITIES)
    def test_input_schema_has_required_array(self, name):
        schema = CAPABILITIES[name]["input_schema"]
        assert "required" in schema
        assert isinstance(schema["required"], list)

    @pytest.mark.parametrize("name", ALL_CAPABILITIES)
    def test_has_impact_level(self, name):
        valid = {"none", "low", "medium", "high"}
        assert CAPABILITIES[name]["impact_level"] in valid

    @pytest.mark.parametrize("name", ALL_CAPABILITIES)
    def test_has_cost_estimate(self, name):
        cost = CAPABILITIES[name]["cost_estimate"]
        assert isinstance(cost, (int, float))
        assert cost >= 0.0


# ---------------------------------------------------------------------------
# 2. describe() method
# ---------------------------------------------------------------------------

class TestDescribe:
    """The universal discovery document."""

    def setup_method(self):
        self.agent = DesktopAgent()
        self.desc = self.agent.describe()

    def test_has_identity(self):
        assert self.desc["name"] == "desktop_agent"
        assert self.desc["display_name"] == "Desktop Agent"
        assert self.desc["version"] == "1.1.0"
        assert self.desc["schema_version"] == 1

    def test_has_description(self):
        assert isinstance(self.desc["description"], str)
        assert len(self.desc["description"]) > 20

    def test_has_domains(self):
        assert "desktop_automation" in self.desc["domains"]
        assert "browser_automation" in self.desc["domains"]

    def test_has_transports(self):
        transports = self.desc["transports"]
        for t in ["cli", "mcp", "rest", "python"]:
            assert t in transports, f"Missing transport: {t}"

    def test_has_permissions_required(self):
        perms = self.desc["permissions_required"]
        assert isinstance(perms, list)
        assert len(perms) >= 3
        assert "screen_capture" in perms
        assert "mouse_input" in perms

    def test_has_capabilities_with_schemas(self):
        caps = self.desc["capabilities"]
        assert len(caps) >= 10

        for name, cap in caps.items():
            assert "description" in cap, f"{name} missing description"
            assert "action_class" in cap, f"{name} missing action_class"
            assert "input" in cap, f"{name} missing input schema"
            assert "output" in cap, f"{name} missing output schema"
            assert cap["input"]["type"] == "object"
            assert "properties" in cap["input"]

    def test_has_action_class_definitions(self):
        classes = self.desc["action_classes"]
        assert "read_only" in classes
        assert "sensitive" in classes
        assert isinstance(classes["read_only"], str)

    def test_has_features(self):
        features = self.desc["features"]
        assert features["dry_run"] is True
        assert features["estimate"] is True
        assert features["undo"] == "best_effort"
        assert features["cancellation"] is True

    def test_has_runtime_status(self):
        status = self.desc["status"]
        assert "bridges" in status
        assert "circuit_breaker" in status

    def test_has_aios_identity(self):
        aios = self.desc["aios"]
        assert aios["capability_id"] == "aios.first_party.desktop_agent"
        assert aios["capability_type"] == "agent"
        assert aios["entrypoint"] == "deskaoy.desktop_agent:DesktopAgent"

    def test_schema_is_alias_for_describe(self):
        """schema() returns the same document as describe()."""
        schema_result = self.agent.schema()
        describe_result = self.agent.describe()
        assert schema_result["name"] == describe_result["name"]
        assert schema_result["version"] == describe_result["version"]
        assert schema_result["capabilities"] == describe_result["capabilities"]

    def test_describe_is_json_serializable(self):
        """The discovery document must be JSON-serializable."""
        serialized = json.dumps(self.desc, default=str)
        assert len(serialized) > 100
        # Round-trip
        parsed = json.loads(serialized)
        assert parsed["name"] == "desktop_agent"


# ---------------------------------------------------------------------------
# 3. Manifest validation
# ---------------------------------------------------------------------------

class TestManifest:
    """CAPABILITY_MANIFEST must be valid and version-synced."""

    def test_manifest_valid(self):
        errors = validate_manifest()
        assert errors == [], f"Manifest validation errors: {errors}"

    def test_manifest_version_matches_agent(self):
        assert CAPABILITY_MANIFEST["version"] == "1.1.0"

    def test_manifest_has_required_keys(self):
        required = {"capability_id", "name", "version", "publisher", "capability_type",
                    "domains", "entrypoint", "supported_actions", "action_classes",
                    "permissions", "runtime", "storage"}
        assert required <= set(CAPABILITY_MANIFEST.keys())

    def test_manifest_capabilities_match_capabilities_registry(self):
        manifest_actions = set(CAPABILITY_MANIFEST["supported_actions"])
        registry_actions = set(CAPABILITIES.keys())
        assert manifest_actions == registry_actions, \
            f"Mismatch: manifest has {manifest_actions - registry_actions} extra, " \
            f"registry has {registry_actions - manifest_actions} extra"

    def test_standalone_capability_id_accepted(self):
        """Standalone mode should accept 'deskaoy' prefix."""
        standalone_manifest = dict(CAPABILITY_MANIFEST)
        standalone_manifest["capability_id"] = "deskaoy.standalone"
        errors = validate_manifest(standalone_manifest)
        assert errors == []


# ---------------------------------------------------------------------------
# 4. REST discovery endpoint
# ---------------------------------------------------------------------------

class TestRESTDiscovery:
    """REST server must expose GET / and GET /capabilities."""

    @pytest.fixture
    def app(self):
        from deskaoy.transport.rest_server import create_app
        application = create_app()
        if application is None:
            pytest.skip("aiohttp not installed")
        return application

    @pytest.fixture
    async def client(self, app, aiohttp_client):
        return await aiohttp_client(app)

    @pytest.mark.asyncio
    async def test_root_returns_discovery(self, app):
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get("/")
            assert resp.status == 200
            data = await resp.json()
            assert data["name"] == "desktop_agent"
            assert data["version"] == "1.1.0"
            assert "capabilities" in data
            assert "input" in data["capabilities"]["click"]

    @pytest.mark.asyncio
    async def test_capabilities_returns_discovery(self, app):
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get("/capabilities")
            assert resp.status == 200
            data = await resp.json()
            assert data["name"] == "desktop_agent"

    @pytest.mark.asyncio
    async def test_health_endpoint(self, app):
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get("/health")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_execute_requires_auth(self, app):
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post("/execute/click", json={"target": "test"})
            assert resp.status == 401


# ---------------------------------------------------------------------------
# 5. MCP describe support
# ---------------------------------------------------------------------------

class TestMCPDescribe:
    """MCP server must support tools/describe method."""

    def setup_method(self):
        from deskaoy.transport.mcp_server import MCPServer
        self.server = MCPServer(compact=False)

    @pytest.mark.asyncio
    async def test_tools_describe_returns_document(self):
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/describe",
        }
        response = await self.server.handle_request(request)
        assert response["id"] == 1
        result = response["result"]
        assert result["name"] == "desktop_agent"
        assert "capabilities" in result
        assert "input" in result["capabilities"]["click"]

    @pytest.mark.asyncio
    async def test_tools_list_uses_real_schemas(self):
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }
        response = await self.server.handle_request(request)
        tools = response["result"]["tools"]

        # Find the click tool
        click_tool = next(t for t in tools if t["name"] == "click")
        schema = click_tool["inputSchema"]
        assert "target" in schema["properties"]
        assert "button" in schema["properties"]
        assert schema["properties"]["button"]["enum"] == ["left", "right", "double"]

    @pytest.mark.asyncio
    async def test_tools_list_automate_has_instruction(self):
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
        }
        response = await self.server.handle_request(request)
        tools = response["result"]["tools"]

        automate_tool = next(t for t in tools if t["name"] == "automate")
        schema = automate_tool["inputSchema"]
        assert "instruction" in schema["properties"]
        assert "instruction" in schema["required"]


# ---------------------------------------------------------------------------
# 6. Context passthrough
# ---------------------------------------------------------------------------

class TestContextPassthrough:
    """REST and MCP must accept context overrides from callers."""

    @pytest.fixture
    def app(self):
        from deskaoy.transport.rest_server import create_app
        application = create_app()
        if application is None:
            pytest.skip("aiohttp not installed")
        return application

    @pytest.mark.asyncio
    async def test_rest_context_overrides(self, app):
        """REST caller can pass _context with locale/timeout/etc."""
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as cli:
            token = app.get("token", "")

            resp = await cli.post(
                "/execute/screenshot",
                json={
                    "_context": {
                        "dry_run": True,
                        "timeout_seconds": 10,
                        "locale": "ar-SA",
                        "timezone": "Asia/Riyadh",
                        "user_id": "test-user",
                    },
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            # Should either succeed (dry_run) or fail gracefully
            assert resp.status in (200, 500)

    @pytest.mark.asyncio
    async def test_mcp_context_overrides(self):
        """MCP caller can pass _context in arguments."""
        from deskaoy.transport.mcp_server import MCPServer
        server = MCPServer()

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "screenshot",
                "arguments": {
                    "_context": {
                        "dry_run": True,
                        "locale": "ar-SA",
                        "user_id": "test-user",
                    },
                },
            },
        }
        response = await server.handle_request(request)
        result = json.loads(response["result"]["content"][0]["text"])
        # Should either succeed or fail gracefully — not crash
        assert "status" in result


# ---------------------------------------------------------------------------
# 7. Version negotiation
# ---------------------------------------------------------------------------

class TestVersionNegotiation:
    """Discovery document includes schema_version for evolution."""

    def test_describe_includes_schema_version(self):
        agent = DesktopAgent()
        desc = agent.describe()
        assert "schema_version" in desc
        assert desc["schema_version"] == 1

    def test_manifest_includes_version(self):
        assert CAPABILITY_MANIFEST["version"] == "1.1.0"

    def test_agent_version_matches(self):
        agent = DesktopAgent()
        assert agent.version == "1.1.0"
        desc = agent.describe()
        assert desc["version"] == "1.1.0"
