"""AgentChat — Interactive chat REPL for desktop automation.

Provides a slash-command based REPL that delegates each command to the
DesktopAgent facade. Runs locally — no API calls unless the user configures
an LLM provider (HB-01).

Usage:
    chat = AgentChat(agent)
    await chat.run()

Commands:
    /help       Show available commands
    /observe    Run Desktop Observation Pipeline
    /click <t>  Click on a target element
    /type <t>   Type text into the focused element
    /snapshot   Capture accessibility tree
    /screenshot Capture screenshot
    /exit       Exit the REPL
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chat result — structured output from each command
# ---------------------------------------------------------------------------

@dataclass
class ChatResult:
    """Structured result from a chat command."""
    ok: bool = True
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AgentChat REPL
# ---------------------------------------------------------------------------

class AgentChat:
    """Interactive chat REPL that delegates to DesktopAgent.

    Each slash-command maps to a DesktopAgent method:
      /observe  → observation pipeline
      /click    → execute(capability="click")
      /type     → execute(capability="type_text")
      /snapshot → execute(capability="snapshot")
      /screenshot → execute(capability="screenshot")

    Free-text lines are dispatched as natural-language instructions
    via execute(capability="automate").
    """

    PROMPT = "agent> "

    def __init__(
        self,
        agent: Any,
        *,
        input_fn: Any | None = None,
        output_fn: Any | None = None,
        session_id: str | None = None,
    ) -> None:
        self._agent = agent
        self._input = input_fn or input
        self._output = output_fn or print
        self._session_id = session_id or "chat-session"
        self._running = False

    # ─── Public API ──────────────────────────────

    async def run(self) -> int:
        """Run the interactive REPL loop. Returns exit code (0)."""
        self._running = True
        self._output("AgentChat ready. Type /help for commands, /exit to quit.")

        try:
            while self._running:
                try:
                    line = self._input(self.PROMPT).strip()
                except EOFError:
                    self._output("")
                    break
                except KeyboardInterrupt:
                    self._output("")
                    break

                if not line:
                    continue

                result = await self._dispatch(line)
                if result is not None:
                    self._output(result.output)

        finally:
            self._running = False

        return 0

    async def process_command(self, line: str) -> ChatResult:
        """Process a single command string and return the result.

        This is the programmatic entry point used by MCP/REST handlers.
        """
        return await self._dispatch(line)

    def stop(self) -> None:
        """Signal the REPL loop to stop."""
        self._running = False

    # ─── Command dispatch ────────────────────────

    async def _dispatch(self, line: str) -> ChatResult | None:
        """Parse and dispatch a single line of input."""
        if line.startswith("/"):
            parts = line.split(maxsplit=1)
            cmd = parts[0].lower()
            rest = parts[1] if len(parts) > 1 else ""
            return await self._handle_command(cmd, rest)

        # Free-text → natural-language instruction
        return await self._cmd_automate(line)

    async def _handle_command(self, cmd: str, rest: str) -> ChatResult:
        """Route slash-commands to handlers."""
        handlers = {
            "/help": self._cmd_help,
            "/observe": self._cmd_observe,
            "/click": self._cmd_click,
            "/type": self._cmd_type,
            "/snapshot": self._cmd_snapshot,
            "/screenshot": self._cmd_screenshot,
            "/exit": self._cmd_exit,
            "/quit": self._cmd_exit,
        }
        handler = handlers.get(cmd)
        if handler is None:
            return ChatResult(
                ok=False,
                output=f"Unknown command: {cmd}. Type /help for available commands.",
            )
        return await handler(rest)

    # ─── Command handlers ────────────────────────

    async def _cmd_help(self, rest: str) -> ChatResult:
        """Show available commands."""
        help_text = (
            "Available commands:\n"
            "  /help           Show this help\n"
            "  /observe        Run Desktop Observation Pipeline\n"
            "  /click <target> Click on a target element\n"
            "  /type <text>    Type text into focused element\n"
            "  /snapshot       Capture accessibility tree\n"
            "  /screenshot     Capture screenshot\n"
            "  /exit           Exit the chat\n"
            "  <free text>     Execute as natural-language instruction"
        )
        return ChatResult(ok=True, output=help_text)

    async def _cmd_observe(self, rest: str) -> ChatResult:
        """Run the Desktop Observation Pipeline."""
        try:
            from deskaoy.observation import ObservationConfig
            from deskaoy.observation_pipeline import ObservationPipeline

            config = ObservationConfig(preset="standard")
            pipeline = ObservationPipeline()
            result = await pipeline.observe(config)

            output = (
                f"Observation complete:\n"
                f"  Elements: {result.element_count}\n"
                f"  Steps: {', '.join(result.steps_completed)}\n"
                f"  Window: {result.observation.active_window or '(none)'}"
            )
            return ChatResult(
                ok=True,
                output=output,
                data={"element_count": result.element_count},
            )
        except Exception as exc:
            return ChatResult(ok=False, output=f"Observe failed: {exc}")

    async def _cmd_click(self, rest: str) -> ChatResult:
        """Click on a target element."""
        if not rest:
            return ChatResult(ok=False, output="Usage: /click <target>")

        try:
            from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

            ctx = AgentContext(
                execution_id="chat-click",
                idempotency_key="chat-click",
                task_id="chat-click",
                user_id="chat",
                session_id=self._session_id,
                cancellation_token=CancellationToken(),
            )
            goal = AgentGoal(capability="click", params={"target": rest})
            result = await self._agent.execute(goal, ctx)

            status = "OK" if result.status.value == "success" else "FAIL"
            return ChatResult(
                ok=result.status.value == "success",
                output=f"Click '{rest}': {status} — {result.summary}",
                data={"status": result.status.value},
            )
        except Exception as exc:
            return ChatResult(ok=False, output=f"Click failed: {exc}")

    async def _cmd_type(self, rest: str) -> ChatResult:
        """Type text into the focused element."""
        if not rest:
            return ChatResult(ok=False, output="Usage: /type <text>")

        try:
            from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

            ctx = AgentContext(
                execution_id="chat-type",
                idempotency_key="chat-type",
                task_id="chat-type",
                user_id="chat",
                session_id=self._session_id,
                cancellation_token=CancellationToken(),
            )
            goal = AgentGoal(capability="type_text", params={"text": rest})
            result = await self._agent.execute(goal, ctx)

            status = "OK" if result.status.value == "success" else "FAIL"
            return ChatResult(
                ok=result.status.value == "success",
                output=f"Type: {status} — {result.summary}",
                data={"status": result.status.value},
            )
        except Exception as exc:
            return ChatResult(ok=False, output=f"Type failed: {exc}")

    async def _cmd_snapshot(self, rest: str) -> ChatResult:
        """Capture accessibility tree snapshot."""
        try:
            from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

            ctx = AgentContext(
                execution_id="chat-snapshot",
                idempotency_key="chat-snapshot",
                task_id="chat-snapshot",
                user_id="chat",
                session_id=self._session_id,
                cancellation_token=CancellationToken(),
            )
            goal = AgentGoal(capability="snapshot", params={})
            result = await self._agent.execute(goal, ctx)

            status = "OK" if result.status.value == "success" else "FAIL"
            return ChatResult(
                ok=result.status.value == "success",
                output=f"Snapshot: {status} — {result.summary}",
                data={"status": result.status.value},
            )
        except Exception as exc:
            return ChatResult(ok=False, output=f"Snapshot failed: {exc}")

    async def _cmd_screenshot(self, rest: str) -> ChatResult:
        """Capture a screenshot."""
        try:
            from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

            ctx = AgentContext(
                execution_id="chat-screenshot",
                idempotency_key="chat-screenshot",
                task_id="chat-screenshot",
                user_id="chat",
                session_id=self._session_id,
                cancellation_token=CancellationToken(),
            )
            goal = AgentGoal(capability="screenshot", params={})
            result = await self._agent.execute(goal, ctx)

            status = "OK" if result.status.value == "success" else "FAIL"
            return ChatResult(
                ok=result.status.value == "success",
                output=f"Screenshot: {status} — {result.summary}",
                data={"status": result.status.value},
            )
        except Exception as exc:
            return ChatResult(ok=False, output=f"Screenshot failed: {exc}")

    async def _cmd_exit(self, rest: str) -> ChatResult | None:
        """Exit the REPL."""
        self._running = False
        return ChatResult(ok=True, output="Goodbye!")

    async def _cmd_automate(self, instruction: str) -> ChatResult:
        """Execute a natural-language instruction."""
        try:
            from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

            ctx = AgentContext(
                execution_id="chat-auto",
                idempotency_key="chat-auto",
                task_id="chat-auto",
                user_id="chat",
                session_id=self._session_id,
                cancellation_token=CancellationToken(),
            )
            goal = AgentGoal(
                capability="automate",
                params={"instruction": instruction},
            )
            result = await self._agent.execute(goal, ctx)

            status = "OK" if result.status.value == "success" else "FAIL"
            return ChatResult(
                ok=result.status.value == "success",
                output=f"{status} — {result.summary}",
                data={"status": result.status.value},
            )
        except Exception as exc:
            return ChatResult(ok=False, output=f"Error: {exc}")
