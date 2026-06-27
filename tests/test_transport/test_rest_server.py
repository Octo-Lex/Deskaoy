"""Tests for REST transport (BATCH-05 TASK-05)."""
from __future__ import annotations

import pytest

from deskaoy.transport.rest_server import (
    _check_token,
    _get_or_create_token,
    create_app,
)


class TestRESTAuth:
    """TEST-05-05-01 through TEST-05-05-02."""

    def test_token_created(self):
        """TEST-05-05-01: Token is created and non-empty."""
        token = _get_or_create_token()
        assert len(token) > 20

    def test_check_token_valid(self):
        """TEST-05-05-02: Token validation works."""
        token = "test-token-12345"
        assert _check_token("Bearer test-token-12345", token) is True
        assert _check_token("Bearer wrong", token) is False
        assert _check_token(None, token) is False
        assert _check_token("", token) is False
        assert _check_token("Basic abc", token) is False


class TestRESTApp:
    """TEST-05-05-03 through TEST-05-05-05."""

    @pytest.fixture
    def app(self):
        """Create REST app (skips if aiohttp not installed)."""
        application = create_app()
        if application is None:
            pytest.skip("aiohttp not installed")
        return application

    def test_app_created(self, app):
        """TEST-05-05-03: REST app is created with routes."""
        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource') and r.resource is not None]
        assert "/health" in routes or any("/health" in str(r) for r in app.router.routes())

    def test_app_has_token(self, app):
        """TEST-05-05-04: App stores the auth token."""
        assert "token" in app
        assert len(app["token"]) > 20

    def test_execute_endpoint_exists(self, app):
        """TEST-05-05-05: Execute endpoint is registered."""
        routes = []
        for r in app.router.routes():
            res = r.resource
            if res:
                routes.append(res.canonical)
        # Should have /execute/{name}
        assert any("execute" in str(r) for r in routes)
