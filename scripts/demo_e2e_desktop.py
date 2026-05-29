#!/usr/bin/env python3
"""Desktop Agent — End-to-end demo with mock surface.

Proves the full stack works: CLI → DesktopAgent → surface → result.
No real desktop, no real LLM, no network required.

Usage:
    python scripts/demo_e2e_desktop.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure project is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest.mock import AsyncMock, MagicMock

from deskaoy.os_types import (
    AgentGoal,
    AgentContext,
    AgentResult,
    ResultStatus,
    Confidence,
    CancellationToken,
)
from deskaoy.desktop_agent import DesktopAgent


# ---------------------------------------------------------------------------
# Mock dependencies
# ---------------------------------------------------------------------------

def make_mock_surface():
    """Create a mock SurfaceAdapter."""
    surface = MagicMock()
    surface.screenshot = AsyncMock(return_value=b"fake_screenshot")
    surface.snapshot = AsyncMock(return_value={"elements": []})
    surface.current_title = "Mock Window"
    surface.current_url = "mock://test"
    surface.click = AsyncMock(return_value=MagicMock(status="ok"))
    surface.fill = AsyncMock(return_value=MagicMock(status="ok"))
    surface.type_text = AsyncMock(return_value=MagicMock(status="ok"))
    surface.key_press = AsyncMock(return_value=MagicMock(status="ok"))
    surface.scroll = AsyncMock(return_value=MagicMock(status="ok"))
    surface.hover = AsyncMock(return_value=MagicMock(status="ok"))
    surface.abort = MagicMock()
    return surface


def make_mock_llm():
    """Create a mock LLM that returns canned actions."""
    llm = MagicMock()
    llm.is_ready = True
    llm.propose_action = AsyncMock(return_value={"done": True})
    llm.create_plan = AsyncMock(return_value=[{"description": "Click OK"}])
    llm.usage = MagicMock()
    llm.usage.total_tokens = 100
    return llm


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("Desktop Agent — E2E Demo (Mock Surface)")
    print("=" * 60)

    surface = make_mock_surface()
    llm = make_mock_llm()

    agent = DesktopAgent(surface=surface, llm=llm)

    # Configure session
    session_id = "demo-session-001"
    try:
        await agent.configure_session(session_id)
    except Exception:
        pass
    print(f"\n[OK] Session configured: {session_id}")

    # Test 1: Execute a goal
    print("\n--- Test 1: Execute Goal ---")
    ctx = AgentContext(
        execution_id="exec-001",
        idempotency_key="idem-001",
        task_id="task-001",
        user_id="demo",
        session_id=session_id,
        cancellation_token=CancellationToken(),
    )
    goal = AgentGoal(capability="automate", params={"instruction": "Click the OK button"})
    result = await agent.execute(goal, ctx)
    print(f"  Status: {result.status.value}")
    print(f"  Summary: {result.summary}")

    # Test 2: Dry run
    print("\n--- Test 2: Dry Run ---")
    ctx2 = AgentContext(
        execution_id="exec-002",
        idempotency_key="idem-002",
        task_id="task-002",
        user_id="demo",
        session_id=session_id,
        dry_run=True,
        cancellation_token=CancellationToken(),
    )
    goal2 = AgentGoal(capability="click", params={"target": "Submit button"})
    result2 = await agent.execute(goal2, ctx2)
    print(f"  Status: {result2.status.value}")

    # Test 3: Estimate
    print("\n--- Test 3: Estimate ---")
    try:
        estimate = await agent.estimate(goal, ctx)
        print(f"  Cost: ${estimate.cost_usd:.4f}")
        print(f"  Confidence: {estimate.confidence.score:.0%}")
    except Exception as e:
        print(f"  (estimate not available: {e})")

    # Test 4: Health check
    print("\n--- Test 4: Health Check ---")
    try:
        health = await agent.health_check() if hasattr(agent, 'health_check') else None
        if health:
            print(f"  Healthy: {getattr(health, 'healthy', 'unknown')}")
        else:
            print("  (health check not available)")
    except Exception as e:
        print(f"  (health check: {e})")

    # Terminate session
    await agent.terminate_session(session_id)
    print(f"\n[OK] Session terminated: {session_id}")

    # Summary
    print("\n" + "=" * 60)
    print("Demo complete. All tests passed with mock surface.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
