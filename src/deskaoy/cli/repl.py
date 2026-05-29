"""Interactive REPL for the deskaoy CLI.

Manages session lifecycle (configure_session on entry, terminate_session on exit).
Supports dot-commands for introspection and natural-language instruction dispatch.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

from deskaoy.cli.main import _get_agent

# ---------------------------------------------------------------------------
# Dot-command handlers
# ---------------------------------------------------------------------------

async def _dot_help(agent: Any, session_id: str) -> None:
    """Print available REPL commands."""
    print("""
  Commands:
    <instruction>     Execute a natural-language instruction
    .help             Show this help
    .health           Run health check
    .facts            List stored facts
    .soul             Show soul aspects
    .skills           List loaded skills
    .schema           Show capability schema
    .estimate <inst>  Preview without executing
    .undo <id>        Undo a previous execution
    .exit             Exit REPL (also Ctrl+C / Ctrl+D)
""")


async def _dot_health(agent: Any, session_id: str) -> None:
    """Run health check."""
    from deskaoy.cli.formatters import format_health
    status = await agent.health_check() if asyncio.iscoroutinefunction(getattr(agent, 'health_check', None)) else agent.health_check()
    print(format_health(status))


async def _dot_facts(agent: Any, session_id: str) -> None:
    """List stored facts."""
    from deskaoy.cli.formatters import format_fact
    store = agent.fact_store
    facts = store.get_facts() if hasattr(store, 'get_facts') else []
    if not facts:
        print("  (no facts stored)")
        return
    for f in facts:
        print(format_fact(f))


async def _dot_soul(agent: Any, session_id: str) -> None:
    """Show soul aspects."""
    store = agent.fact_store
    souls = store.get_soul_aspects() if hasattr(store, 'get_soul_aspects') else []
    if not souls:
        print("  (no soul aspects)")
        return
    for s in souls:
        content = getattr(s, 'content', str(s))
        category = getattr(s, 'category', '?')
        print(f"  [{category}] {content}")


async def _dot_skills(agent: Any, session_id: str) -> None:
    """List loaded skills."""
    from deskaoy.cli.formatters import format_skill
    loader = agent.skill_loader
    skills = loader.discover() if hasattr(loader, 'discover') else []
    if not skills:
        print("  (no skills found)")
        return
    for s in skills:
        print(format_skill(s))


async def _dot_schema(agent: Any, session_id: str) -> None:
    """Show capability schema."""
    from deskaoy.cli.formatters import format_schema
    schema_data = agent.schema() if hasattr(agent, 'schema') else {"capabilities": {}}
    print(format_schema(schema_data))


async def _dot_estimate(agent: Any, session_id: str, instruction: str) -> None:
    """Preview without executing."""
    from deskaoy.cli.formatters import format_estimate
    from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

    ctx = AgentContext(
        execution_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        user_id="cli",
        session_id=session_id,
        dry_run=True,
        timeout_seconds=60,
        cancellation_token=CancellationToken(),
    )
    goal = AgentGoal(capability="automate", params={"instruction": instruction})
    estimate = await agent.estimate(goal, ctx)
    print(format_estimate(estimate))


async def _dot_undo(agent: Any, session_id: str, execution_id: str) -> None:
    """Undo a previous execution."""
    result = await agent.undo(execution_id, None) if hasattr(agent, 'undo') else None
    if result:
        success = getattr(result, 'success', False)
        summary = getattr(result, 'summary', 'no result')
        icon = "✓" if success else "✗"
        print(f"  {icon} {summary}")
    else:
        print(f"  ✗ Undo not available for {execution_id}")


# ---------------------------------------------------------------------------
# Dot-command dispatch
# ---------------------------------------------------------------------------

_DOT_COMMANDS = {
    ".help": lambda agent, sid, rest: _dot_help(agent, sid),
    ".health": lambda agent, sid, rest: _dot_health(agent, sid),
    ".facts": lambda agent, sid, rest: _dot_facts(agent, sid),
    ".soul": lambda agent, sid, rest: _dot_soul(agent, sid),
    ".skills": lambda agent, sid, rest: _dot_skills(agent, sid),
    ".schema": lambda agent, sid, rest: _dot_schema(agent, sid),
    ".estimate": lambda agent, sid, rest: _dot_estimate(agent, sid, rest),
    ".undo": lambda agent, sid, rest: _dot_undo(agent, sid, rest.strip()),
    ".exit": None,  # handled inline
}


# ---------------------------------------------------------------------------
# REPL loop
# ---------------------------------------------------------------------------

async def run_repl(
    *,
    storage_dir: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
) -> int:
    """Run the interactive REPL. Returns exit code."""
    agent = _get_agent(storage_dir)
    sid = session_id or str(uuid.uuid4())

    # HB-04: configure session on entry
    try:
        agent.configure_session(sid)
    except Exception:
        pass  # May fail in headless mode, that's ok

    print(f"deskaoy repl (session: {sid[:8]}...)")
    print("Type .help for commands, .exit to quit.\n")

    try:
        while True:
            try:
                line = input("deskaoy> ").strip()
            except EOFError:
                print()
                break

            if not line:
                continue

            # Dot-commands
            if line.startswith("."):
                parts = line.split(maxsplit=1)
                cmd = parts[0].lower()
                rest = parts[1] if len(parts) > 1 else ""

                if cmd == ".exit" or cmd == ".quit":
                    break

                handler = _DOT_COMMANDS.get(cmd)
                if handler:
                    await handler(agent, sid, rest)
                else:
                    print(f"  Unknown command: {cmd}. Type .help for commands.")
                continue

            # Normal instruction dispatch
            try:
                from deskaoy.cli.formatters import format_result
                from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

                ctx = AgentContext(
                    execution_id=str(uuid.uuid4()),
                    idempotency_key=str(uuid.uuid4()),
                    task_id=str(uuid.uuid4()),
                    user_id="cli",
                    session_id=sid,
                    dry_run=False,
                    timeout_seconds=60,
                    cancellation_token=CancellationToken(),
                )
                goal = AgentGoal(capability="automate", params={"instruction": line})
                result = await agent.execute(goal, ctx)
                print(format_result(result))

            except Exception as exc:
                print(f"  Error: {exc}")

    except KeyboardInterrupt:
        print("\n")
    finally:
        # HB-04: terminate session on exit
        with contextlib.suppress(Exception):
            agent.terminate_session(sid)
        print("Session closed.")

    return 0
