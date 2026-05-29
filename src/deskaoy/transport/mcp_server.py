"""MCP stdio transport — Model Context Protocol server for agent hosts.

Provides a stdio-based JSON-RPC server that exposes DesktopAgent capabilities
as MCP tools. Compatible with Claude Code, Cursor, Windsurf, Zed, and any
MCP-aware agent host.

Usage:
    deskaoy mcp           # 74 granular tools
    deskaoy mcp --compact # 6 compound tools

Requires: pip install deskaoy[mcp]
Graceful fallback when mcp SDK is not installed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from deskaoy.cli.version import VERSION

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def _build_tools(compact: bool = False) -> list[dict]:
    """Build MCP tool definitions from DesktopAgent capabilities."""
    if compact:
        return [
            {
                "name": "computer",
                "description": "Mouse, keyboard, screenshot, and wait operations",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["screenshot", "click", "double_click", "right_click",
                                    "hover", "scroll", "drag", "type", "key", "wait"],
                            "description": "Action to perform",
                        },
                        "x": {"type": "number", "description": "X coordinate"},
                        "y": {"type": "number", "description": "Y coordinate"},
                        "text": {"type": "string", "description": "Text to type"},
                        "combo": {"type": "string", "description": "Key combination (e.g. mod+s)"},
                        "direction": {"type": "string", "enum": ["up", "down"]},
                        "amount": {"type": "number"},
                        "seconds": {"type": "number"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "accessibility",
                "description": "Accessibility tree operations",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["read_tree", "find", "invoke", "focus", "set_value", "get_value"],
                        },
                        "target": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "window",
                "description": "Window and application management",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "active", "focus", "maximize", "minimize",
                                    "restore", "close", "open_app"],
                        },
                        "name": {"type": "string", "description": "App or window name"},
                        "title": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "system",
                "description": "System operations (clipboard, OCR, shortcuts)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["clipboard_read", "clipboard_write", "ocr", "undo", "shortcuts_list"],
                        },
                        "text": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "browser",
                "description": "Browser automation via CDP",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["connect", "read_text", "click", "type", "evaluate"],
                        },
                        "target": {"type": "string"},
                        "text": {"type": "string"},
                        "expression": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "task",
                "description": "Execute a natural-language task through the full pipeline",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": "Natural-language instruction to execute",
                        },
                    },
                    "required": ["instruction"],
                },
            },
        ]

    # Granular mode — one tool per DesktopAgent capability (with real schemas)
    from deskaoy.desktop_agent import CAPABILITIES
    tools = []
    for name, meta in CAPABILITIES.items():
        tools.append({
            "name": name,
            "description": meta["description"],
            "inputSchema": meta.get("input_schema", {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Target element or description"},
                    "value": {"type": "string", "description": "Value to set"},
                    "instruction": {"type": "string", "description": "Natural-language instruction"},
                    "dry_run": {"type": "boolean", "description": "Preview without executing"},
                },
            }),
        })

    # BATCH-27: observe tool
    tools.append({
        "name": "observe",
        "description": "Capture desktop observation with screenshot, AX tree, OCR, and optional detection",
        "inputSchema": {
            "type": "object",
            "properties": {
                "preset": {
                    "type": "string",
                    "enum": ["quick", "standard", "full"],
                    "description": "Pipeline preset (default: standard)",
                },
                "save": {
                    "type": "boolean",
                    "description": "Save snapshot to SnapshotStore",
                },
                "annotate": {
                    "type": "boolean",
                    "description": "Render SoM annotation on screenshot",
                },
            },
        },
    })

    # BATCH-28: clipboard, set_value, perform_action tools
    tools.append({
        "name": "clipboard",
        "description": "Read, write, or paste clipboard text",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "paste"],
                    "description": "Clipboard operation",
                },
                "text": {
                    "type": "string",
                    "description": "Text to write (required for write action)",
                },
            },
            "required": ["action"],
        },
    })

    tools.append({
        "name": "set_value",
        "description": "Set a value on a target element using UIA ValuePattern first, fallback to click+type",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target element (name, auto:id, or coordinates)",
                },
                "value": {
                    "type": "string",
                    "description": "Value to set",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview without executing",
                },
            },
            "required": ["target", "value"],
        },
    })

    tools.append({
        "name": "perform_action",
        "description": "Perform a named accessibility action on a target element (invoke, toggle, expand, collapse, select, focus, set_value, get_value)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target element",
                },
                "action": {
                    "type": "string",
                    "description": "Action name (invoke, toggle, expand, collapse, select, focus, set_value, get_value)",
                },
                "value": {
                    "type": "string",
                    "description": "Optional value parameter (for set_value)",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview without executing",
                },
            },
            "required": ["target", "action"],
        },
    })

    # BATCH-29: chat_message and run_script tools
    tools.append({
        "name": "chat_message",
        "description": "Send a message to the AgentChat REPL and get a response",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Chat message or slash-command",
                },
            },
            "required": ["message"],
        },
    })

    tools.append({
        "name": "run_script",
        "description": "Execute a .deskaoy.json automation script",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the .deskaoy.json script file",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate and preview without executing",
                },
            },
            "required": ["path"],
        },
    })

    return tools


# ---------------------------------------------------------------------------
# MCP Server (stdio JSON-RPC)
# ---------------------------------------------------------------------------

class MCPServer:
    """Lightweight MCP server over stdio.

    Implements the Model Context Protocol for tool listing and execution.
    No external MCP SDK dependency — pure stdlib JSON-RPC over stdio.
    """

    def __init__(self, compact: bool = False) -> None:
        self.compact = compact
        self._tools = _build_tools(compact)
        self._agent: Any = None

    def _get_agent(self) -> Any:
        """Lazy agent initialization."""
        if self._agent is None:
            from deskaoy.desktop_agent import DesktopAgent
            self._agent = DesktopAgent()
        return self._agent

    async def handle_request(self, request: dict) -> dict | None:
        """Handle a single JSON-RPC request."""
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "deskaoy",
                        "version": VERSION,
                    },
                },
            }

        if method == "notifications/initialized":
            return None  # No response for notifications

        if method == "tools/describe":
            """Universal discovery — returns full describe() document."""
            agent = self._get_agent()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": agent.describe(),
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self._tools},
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = await self._execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    async def _execute_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool call by routing to DesktopAgent."""
        # Handle observe tool directly (BATCH-27)
        if tool_name == "observe":
            return await self._execute_observe(arguments)

        # Handle BATCH-28 tools directly
        if tool_name == "clipboard":
            return await self._execute_clipboard(arguments)
        if tool_name == "set_value":
            return await self._execute_set_value(arguments)
        if tool_name == "perform_action":
            return await self._execute_perform_action(arguments)

        # Handle BATCH-29 tools directly
        if tool_name == "chat_message":
            return await self._execute_chat_message(arguments)
        if tool_name == "run_script":
            return await self._execute_run_script(arguments)

        from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

        agent = self._get_agent()

        # Map compact tool names to capabilities
        capability = tool_name
        params = dict(arguments)

        # Extract context overrides (prefixed with _ to avoid collision)
        context_overrides = params.pop("_context", {})

        # Compact mode: extract action and map
        if self.compact and tool_name in ("computer", "accessibility", "window", "system", "browser"):
            action = arguments.get("action", "")
            if tool_name == "computer":
                if action in ("click", "double_click", "right_click", "hover"):
                    capability = "click"
                    params = {"target": f"{arguments.get('x', 0)},{arguments.get('y', 0)}"}
                elif action == "type":
                    capability = "type_text"
                    params = {"text": arguments.get("text", "")}
                elif action == "key":
                    capability = "key_press"
                    params = {"key": arguments.get("combo", "")}
                elif action == "screenshot":
                    capability = "screenshot"
                    params = {}
                elif action == "scroll":
                    capability = "scroll"
                    params = {"direction": arguments.get("direction", "down")}
                else:
                    capability = "automate"
                    params = {"instruction": json.dumps(arguments)}
            elif tool_name == "accessibility":
                if action == "read_tree":
                    capability = "snapshot"
                    params = {}
                elif action in ("invoke", "click"):
                    capability = "click"
                    params = {"target": arguments.get("target", "")}
                else:
                    capability = "automate"
                    params = {"instruction": json.dumps(arguments)}
            elif tool_name == "window":
                if action == "open_app":
                    capability = "automate"
                    params = {"instruction": f"Open {arguments.get('name', '')}"}
                else:
                    capability = "automate"
                    params = {"instruction": json.dumps(arguments)}
            elif tool_name == "task":
                capability = "automate"
                params = {"instruction": arguments.get("instruction", "")}

        ctx = AgentContext(
            execution_id=f"mcp-{tool_name}-{id(arguments)}",
            idempotency_key=f"mcp-{tool_name}-{id(arguments)}",
            task_id=f"mcp-{tool_name}-{id(arguments)}",
            user_id=context_overrides.get("user_id", "mcp"),
            session_id=context_overrides.get("session_id", "mcp-session"),
            cancellation_token=CancellationToken(),
            dry_run=context_overrides.get("dry_run", False),
            timeout_seconds=context_overrides.get("timeout_seconds", 60),
            autonomy_mode=context_overrides.get("autonomy_mode", "autopilot"),
            locale=context_overrides.get("locale", "en-US"),
            timezone=context_overrides.get("timezone", "America/New_York"),
        )
        goal = AgentGoal(capability=capability, params=params)

        try:
            result = await agent.execute(goal, ctx)
            return {
                "status": result.status.value,
                "summary": result.summary,
                "confidence": result.confidence.score,
            }
        except Exception as exc:
            return {"status": "failure", "summary": str(exc)}

    async def _execute_observe(self, arguments: dict) -> dict:
        """Execute the observe tool (BATCH-27)."""
        try:
            from deskaoy.observation import ObservationConfig
            from deskaoy.observation_pipeline import ObservationPipeline

            config = ObservationConfig(
                preset=arguments.get("preset", "standard"),
                save_snapshot=arguments.get("save", False),
                include_annotation=arguments.get("annotate", False),
            )

            pipeline = ObservationPipeline()
            result = await pipeline.observe(config)

            return {
                "status": "success",
                "element_count": result.element_count,
                "steps_completed": result.steps_completed,
                "steps_skipped": result.steps_skipped,
                "active_window": result.observation.active_window,
                "snapshot_id": result.snapshot_id,
            }
        except Exception as exc:
            return {"status": "failure", "summary": str(exc)}

    async def _execute_clipboard(self, arguments: dict) -> dict:
        """Execute the clipboard tool (BATCH-28)."""
        try:
            agent = self._get_agent()
            action = arguments.get("action", "read")

            if action == "read":
                text = await agent.read_clipboard()
                return {"status": "success", "text": text}
            elif action == "write":
                text = arguments.get("text", "")
                await agent.write_clipboard(text)
                return {"status": "success", "action": "write"}
            elif action == "paste":
                result = await agent.paste()
                return {"status": "success" if result.ok else "failure", "ok": result.ok, "data": result.data}
            else:
                return {"status": "failure", "error": f"Unknown clipboard action: {action}"}
        except Exception as exc:
            return {"status": "failure", "summary": str(exc)}

    async def _execute_set_value(self, arguments: dict) -> dict:
        """Execute the set_value tool (BATCH-28)."""
        try:
            agent = self._get_agent()
            target = arguments.get("target", "")
            value = arguments.get("value", "")
            dry_run = arguments.get("dry_run", False)
            result = await agent.set_value(target, value, dry_run=dry_run)
            return {
                "status": "success" if result.ok else "failure",
                "ok": result.ok,
                "data": result.data,
            }
        except Exception as exc:
            return {"status": "failure", "summary": str(exc)}

    async def _execute_perform_action(self, arguments: dict) -> dict:
        """Execute the perform_action tool (BATCH-28)."""
        try:
            agent = self._get_agent()
            target = arguments.get("target", "")
            action = arguments.get("action", "")
            value = arguments.get("value", "")
            dry_run = arguments.get("dry_run", False)
            result = await agent.perform_action(target, action, value=value, dry_run=dry_run)
            return {
                "status": "success" if result.ok else "failure",
                "ok": result.ok,
                "data": result.data,
            }
        except Exception as exc:
            return {"status": "failure", "summary": str(exc)}

    async def _execute_chat_message(self, arguments: dict) -> dict:
        """Execute the chat_message tool (BATCH-29)."""
        try:
            from deskaoy.agent.chat import AgentChat

            agent = self._get_agent()
            chat = AgentChat(agent)
            message = arguments.get("message", "")
            result = await chat.process_command(message)
            return {
                "status": "success" if result.ok else "failure",
                "ok": result.ok,
                "output": result.output,
                "data": result.data,
            }
        except Exception as exc:
            return {"status": "failure", "summary": str(exc)}

    async def _execute_run_script(self, arguments: dict) -> dict:
        """Execute the run_script tool (BATCH-29)."""
        try:
            from deskaoy.agent.script_runner import ScriptRunner

            agent = self._get_agent()
            runner = ScriptRunner(agent)
            path = arguments.get("path", "")
            dry_run = arguments.get("dry_run", False)
            result = await runner.run(path, dry_run=dry_run)
            return {
                "status": "success" if result.ok else "failure",
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
            }
        except Exception as exc:
            return {"status": "failure", "summary": str(exc)}

    async def run(self) -> None:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue

            response = await self.handle_request(request)
            if response is not None:
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()


def run_mcp_server(compact: bool = False) -> int:
    """Entry point for `deskaoy mcp`. Returns exit code."""
    try:
        server = MCPServer(compact=compact)
        asyncio.run(server.run())
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"MCP server error: {exc}", file=sys.stderr)
        return 1
