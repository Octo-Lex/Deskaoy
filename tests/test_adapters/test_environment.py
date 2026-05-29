"""Tests for Environment Interface (BATCH-09)."""
from __future__ import annotations

import asyncio
import pytest

from deskaoy.adapters.environment import (
    Environment,
    EnvironmentState,
    EnvironmentInfo,
    LocalDesktop,
    DockerDesktop,
    RemoteVM,
)


class TestEnvironmentState:
    def test_state_values(self):
        assert EnvironmentState.CREATED == "created"
        assert EnvironmentState.READY == "ready"
        assert EnvironmentState.DISPOSED == "disposed"


class TestLocalDesktop:
    def test_initial_state(self):
        env = LocalDesktop()
        assert env.state == EnvironmentState.CREATED

    def test_initialize(self):
        env = LocalDesktop()
        info = asyncio.run(env.initialize())
        assert env.state == EnvironmentState.READY
        assert isinstance(info, EnvironmentInfo)
        assert info.type == "local"
        assert info.screen_width > 0

    def test_lifecycle(self):
        env = LocalDesktop()
        asyncio.run(env.initialize())

        # on_before_tool → BUSY
        params = asyncio.run(env.on_before_tool("click", {"x": 100}))
        assert env.state == EnvironmentState.BUSY
        assert params == {"x": 100}

        # on_after_tool → READY
        asyncio.run(env.on_after_tool("click", {"x": 100}, None))
        assert env.state == EnvironmentState.READY

        # dispose → DISPOSED
        asyncio.run(env.on_dispose())
        assert env.state == EnvironmentState.DISPOSED

    def test_info_available_after_init(self):
        env = LocalDesktop()
        assert env.info is None
        asyncio.run(env.initialize())
        assert env.info is not None
        assert env.info.name == "local-desktop"


class TestDockerDesktop:
    def test_initialize(self):
        env = DockerDesktop(container_id="abc123def456", vnc_port=5900)
        info = asyncio.run(env.initialize())
        assert env.state == EnvironmentState.READY
        assert info.type == "docker"
        assert "abc123" in info.name
        assert info.metadata["vnc_port"] == 5900

    def test_lifecycle(self):
        env = DockerDesktop(container_id="test")
        asyncio.run(env.initialize())
        asyncio.run(env.on_before_tool("click", {}))
        assert env.state == EnvironmentState.BUSY
        asyncio.run(env.on_after_tool("click", {}, None))
        assert env.state == EnvironmentState.READY
        asyncio.run(env.on_dispose())
        assert env.state == EnvironmentState.DISPOSED


class TestRemoteVM:
    def test_initialize(self):
        env = RemoteVM(host="192.168.1.100", port=3389, protocol="rdp")
        info = asyncio.run(env.initialize())
        assert env.state == EnvironmentState.READY
        assert info.type == "remote"
        assert "192.168.1.100" in info.name
        assert info.metadata["protocol"] == "rdp"

    def test_lifecycle(self):
        env = RemoteVM(host="10.0.0.1")
        asyncio.run(env.initialize())
        asyncio.run(env.on_before_tool("type", {"text": "hi"}))
        asyncio.run(env.on_after_tool("type", {"text": "hi"}, None))
        asyncio.run(env.on_dispose())
        assert env.state == EnvironmentState.DISPOSED

    def test_params_passed_through(self):
        """on_before_tool returns unmodified params."""
        env = RemoteVM(host="test")
        asyncio.run(env.initialize())
        params = {"target": "button", "x": 50}
        result = asyncio.run(env.on_before_tool("click", params))
        assert result == params


class TestEnvironmentProtocol:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Environment()

    def test_screenshot_not_implemented_by_default(self):
        """Base Environment.screenshot raises NotImplementedError."""
        env = DockerDesktop(container_id="test")
        asyncio.run(env.initialize())
        with pytest.raises(NotImplementedError):
            asyncio.run(env.screenshot())
