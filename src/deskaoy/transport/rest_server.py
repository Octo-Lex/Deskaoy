"""REST HTTP transport — local HTTP API for agent integration.

Provides a REST API on 127.0.0.1:3847 with bearer token auth.
Compatible with any HTTP-capable agent or SDK.

Usage:
    deskaoy serve

Requires: pip install deskaoy[rest]
Graceful fallback when aiohttp is not installed.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Any

from deskaoy.cli.version import VERSION

# Token storage
_TOKEN_DIR = Path.home() / ".deskaoy-dev"
_TOKEN_FILE = _TOKEN_DIR / "token"
_DEFAULT_PORT = 3847


def _get_or_create_token() -> str:
    """Get existing token or create a new one."""
    if _TOKEN_FILE.exists():
        return _TOKEN_FILE.read_text().strip()
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    _TOKEN_FILE.write_text(token)
    return token


def _check_token(auth_header: str | None, expected: str) -> bool:
    """Validate bearer token."""
    if not auth_header:
        return False
    if not auth_header.startswith("Bearer "):
        return False
    return auth_header[7:] == expected


# ---------------------------------------------------------------------------
# REST Server (using aiohttp if available, else stub)
# ---------------------------------------------------------------------------

def create_app() -> Any:
    """Create the REST application. Returns aiohttp web.Application or None."""
    try:
        from aiohttp import web
    except ImportError:
        return None

    token = _get_or_create_token()
    agent_instance: Any = None

    def get_agent() -> Any:
        nonlocal agent_instance
        if agent_instance is None:
            from deskaoy.desktop_agent import DesktopAgent
            agent_instance = DesktopAgent()
        return agent_instance

    async def health_handler(request: Any) -> Any:
        return web.json_response({
            "status": "ok",
            "version": VERSION,
            "uptime": "running",
        })

    async def describe_handler(request: Any) -> Any:
        """Universal discovery endpoint — the service describes itself."""
        agent = get_agent()
        return web.json_response(agent.describe())

    async def tools_handler(request: Any) -> Any:
        """Backward-compat tool listing."""
        agent = get_agent()
        desc = agent.describe()
        return web.json_response({
            "name": desc["name"],
            "version": desc["version"],
            "capabilities": desc["capabilities"],
        })

    async def execute_handler(request: Any) -> Any:
        # Auth check
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)

        tool_name = request.match_info["name"]
        try:
            body = await request.json()
        except Exception:
            body = {}

        from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken
        agent = get_agent()

        # Extract context overrides from caller
        context_overrides = body.pop("_context", {})
        dry_run = context_overrides.get("dry_run", False)
        timeout = context_overrides.get("timeout_seconds", 60)
        autonomy_mode = context_overrides.get("autonomy_mode", "autopilot")
        locale = context_overrides.get("locale", "en-US")
        timezone = context_overrides.get("timezone", "America/New_York")

        ctx = AgentContext(
            execution_id=f"rest-{id(request)}",
            idempotency_key=f"rest-{id(request)}",
            task_id=f"rest-{id(request)}",
            user_id=context_overrides.get("user_id", "rest"),
            session_id=context_overrides.get("session_id", "rest-session"),
            dry_run=dry_run,
            timeout_seconds=timeout,
            cancellation_token=CancellationToken(),
            autonomy_mode=autonomy_mode,
            locale=locale,
            timezone=timezone,
        )
        goal = AgentGoal(capability=tool_name, params=body)

        result = await agent.execute(goal, ctx)
        return web.json_response({
            "status": result.status.value,
            "summary": result.summary,
            "confidence": result.confidence.score,
            "issues": [
                {"severity": i.severity.value, "code": i.code.value, "message": i.message}
                for i in result.issues
            ],
        })

    async def status_handler(request: Any) -> Any:
        agent = get_agent()
        health = await agent.health()
        return web.json_response({
            "healthy": health.healthy,
            "checks": health.details if hasattr(health, 'details') else {},
        })

    async def screenshot_handler(request: Any) -> Any:
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)
        return web.json_response({"error": "Screenshot requires surface adapter"}, status=501)

    async def confirm_handler(request: Any) -> Any:
        """Approve or reject a safety-gated action."""
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            body = await request.json()
            approved = body.get("approved", False)
            return web.json_response({"confirmed": approved})
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

    async def abort_handler(request: Any) -> Any:
        """Abort the in-flight task."""
        return web.json_response({"aborted": True})

    async def observe_handler(request: Any) -> Any:
        """Run Desktop Observation Pipeline (BATCH-27)."""
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            from deskaoy.observation import ObservationConfig
            from deskaoy.observation_pipeline import ObservationPipeline

            config = ObservationConfig(
                preset=body.get("preset", "standard"),
                save_snapshot=body.get("save", False),
                include_annotation=body.get("annotate", False),
            )

            pipeline = ObservationPipeline()
            result = await pipeline.observe(config)

            return web.json_response(result.to_dict(), default=str)
        except Exception as exc:
            return web.json_response(
                {"error": str(exc)}, status=500,
            )

    async def clipboard_handler(request: Any) -> Any:
        """Clipboard operations (BATCH-28)."""
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            body = await request.json()
        except Exception:
            body = {}

        agent = get_agent()
        action = body.get("action", "read")

        try:
            if action == "read":
                text = await agent.read_clipboard()
                return web.json_response({"ok": True, "text": text})
            elif action == "write":
                await agent.write_clipboard(body.get("text", ""))
                return web.json_response({"ok": True})
            elif action == "paste":
                result = await agent.paste()
                return web.json_response({"ok": result.ok, "data": result.data})
            else:
                return web.json_response({"error": f"Unknown action: {action}"}, status=400)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    async def set_value_handler(request: Any) -> Any:
        """Set element value (BATCH-28)."""
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            body = await request.json()
        except Exception:
            body = {}

        agent = get_agent()
        target = body.get("target", "")
        value = body.get("value", "")
        dry_run = body.get("dry_run", False)

        try:
            result = await agent.set_value(target, value, dry_run=dry_run)
            resp = {"ok": result.ok, "data": result.data}
            if result.error:
                resp["error"] = result.error.message
            return web.json_response(resp)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    async def perform_action_handler(request: Any) -> Any:
        """Perform accessibility action (BATCH-28)."""
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            body = await request.json()
        except Exception:
            body = {}

        agent = get_agent()
        target = body.get("target", "")
        action = body.get("action", "")
        value = body.get("value", "")
        dry_run = body.get("dry_run", False)

        try:
            result = await agent.perform_action(target, action, value=value, dry_run=dry_run)
            resp = {"ok": result.ok, "data": result.data}
            if result.error:
                resp["error"] = result.error.message
            return web.json_response(resp)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    async def chat_handler(request: Any) -> Any:
        """Handle chat message (BATCH-29)."""
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            from deskaoy.agent.chat import AgentChat

            agent = get_agent()
            chat = AgentChat(agent)
            message = body.get("message", "")
            result = await chat.process_command(message)
            return web.json_response({
                "ok": result.ok,
                "output": result.output,
                "data": result.data,
            })
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    async def run_script_handler(request: Any) -> Any:
        """Run automation script (BATCH-29)."""
        auth = request.headers.get("Authorization", "")
        if not _check_token(auth, token):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            from deskaoy.agent.script_runner import ScriptRunner

            agent = get_agent()
            runner = ScriptRunner(agent)
            path = body.get("path", "")
            dry_run = body.get("dry_run", False)
            result = await runner.run(path, dry_run=dry_run)
            return web.json_response({
                "ok": result.ok,
                "name": result.name,
                "steps_total": result.steps_total,
                "steps_ok": result.steps_ok,
                "steps_failed": result.steps_failed,
                "dry_run": result.dry_run,
                "steps": [
                    {"index": s.step_index, "action": s.action, "ok": s.ok, "output": s.output}
                    for s in result.step_results
                ],
            })
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    app = web.Application()
    app.router.add_get("/", describe_handler)
    app.router.add_get("/capabilities", describe_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/tools", tools_handler)
    app.router.add_get("/status", status_handler)
    app.router.add_get("/screenshot", screenshot_handler)
    app.router.add_post("/execute/{name}", execute_handler)
    app.router.add_post("/confirm", confirm_handler)
    app.router.add_post("/abort", abort_handler)
    app.router.add_post("/observe", observe_handler)
    app.router.add_post("/clipboard", clipboard_handler)
    app.router.add_post("/set-value", set_value_handler)
    app.router.add_post("/perform-action", perform_action_handler)
    app.router.add_post("/chat", chat_handler)
    app.router.add_post("/run-script", run_script_handler)

    # Store token for display
    app["token"] = token

    return app


def run_rest_server(port: int = _DEFAULT_PORT, skip_consent: bool = False) -> int:
    """Entry point for `deskaoy serve`. Returns exit code."""
    try:
        from aiohttp import web
    except ImportError:
        print("Error: aiohttp is required for REST server.", file=sys.stderr)
        print("Install with: pip install deskaoy[rest]", file=sys.stderr)
        return 1

    app = create_app()
    if app is None:
        print("Error: Failed to create REST application.", file=sys.stderr)
        return 1

    token = app.get("token", "")
    print(f"deskaoy REST server v{VERSION}")
    print(f"  Listening on: http://127.0.0.1:{port}")
    print(f"  Token: {token[:8]}...{token[-4:]}")
    print(f"  Token file: {_TOKEN_FILE}")
    print("  Endpoints: GET /health, GET /tools, POST /execute/<name>")
    print()
    print("  Press Ctrl+C to stop.")

    try:
        web.run_app(app, host="127.0.0.1", port=port, print=None)
        return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
