#!/usr/bin/env python3
"""Desktop Agent — End-to-end integration proof.

Proves the entire stack works on a real Windows desktop:
  1. Launches Notepad (or targets an existing window)
  2. Connects DesktopAgent with WindowsAdapter + LLM
  3. Executes a natural-language instruction via AgentLoop
  4. Verifies the result via UIA tree inspection
  5. Reports step-by-step trace

Usage:
    set OPENAI_API_KEY=sk-...
    python scripts/demo_desktop_agent.py --task "Type Hello World in Notepad"

    # Or with Anthropic:
    set ANTHROPIC_API_KEY=...
    python scripts/demo_desktop_agent.py --provider anthropic --task "Type Hello World"
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-30s %(message)s")
logger = logging.getLogger("demo_desktop_agent")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_notepad_hwnd() -> int | None:
    """Find an existing Notepad window handle."""
    try:
        import win32gui
        result = [None]

        def _callback(hwnd, _):
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            if "Notepad" in cls or "Notepad" in title:
                result[0] = hwnd
            return True

        win32gui.EnumWindows(_callback, None)
        return result[0]
    except ImportError:
        return None


def launch_notepad() -> subprocess.Popen:
    """Launch Notepad and return the process."""
    proc = subprocess.Popen("notepad.exe")
    time.sleep(1.5)  # Wait for window to appear
    return proc


def get_hwnd_from_pid(pid: int) -> int | None:
    """Find the window handle for a process ID."""
    try:
        import win32gui
        import win32process

        result = [None]

        def _callback(hwnd, _):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid and win32gui.IsWindowVisible(hwnd):
                result[0] = hwnd
            return True

        win32gui.EnumWindows(_callback, None)
        return result[0]
    except ImportError:
        return None


def register_desktop_tools(registry, adapter) -> None:
    """Register WindowsAdapter methods as agent tools."""
    from deskaoy.agent.registry import ToolDefinition, ToolParameter

    tools = [
        ToolDefinition(
            name="click",
            description="Click on a desktop element. Target can be an element name, ref (e.g. 'e5'), or description.",
            parameters=(
                ToolParameter(name="target", type_name="str", required=True, description="Element name, ref, or description to click"),
                ToolParameter(name="description", type_name="str", required=False, description="Natural language description of what to click"),
            ),
            handler=adapter.click,
            security_level="sensitive",
            action_class="sensitive",
            impact_level="low",
        ),
        ToolDefinition(
            name="type_text",
            description="Type text character by character with human-like delays into the focused element.",
            parameters=(
                ToolParameter(name="text", type_name="str", required=True, description="Text to type"),
                ToolParameter(name="target", type_name="str", required=False, description="Optional element to focus first"),
            ),
            handler=adapter.type_text,
            security_level="sensitive",
            action_class="sensitive",
            impact_level="medium",
        ),
        ToolDefinition(
            name="fill",
            description="Fill a text field with a value, replacing existing content.",
            parameters=(
                ToolParameter(name="target", type_name="str", required=True, description="Element to fill"),
                ToolParameter(name="value", type_name="str", required=True, description="Value to fill"),
            ),
            handler=adapter.fill,
            security_level="sensitive",
            action_class="sensitive",
            impact_level="medium",
        ),
        ToolDefinition(
            name="key_press",
            description="Press a key or key combination (e.g. 'Enter', 'ctrl+a', 'alt+F4').",
            parameters=(
                ToolParameter(name="key", type_name="str", required=True, description="Key or key combination"),
            ),
            handler=adapter.key_press,
            security_level="recoverable",
            action_class="recoverable",
            impact_level="low",
        ),
        ToolDefinition(
            name="scroll",
            description="Scroll in a direction.",
            parameters=(
                ToolParameter(name="direction", type_name="str", required=True, description="One of: up, down, left, right"),
                ToolParameter(name="amount", type_name="int", required=False, description="Number of scroll clicks"),
            ),
            handler=adapter.scroll,
            security_level="safe",
            action_class="recoverable",
            impact_level="low",
        ),
        ToolDefinition(
            name="screenshot",
            description="Take a screenshot of the target window. Returns image data.",
            parameters=(),
            handler=adapter.screenshot,
            security_level="safe",
            action_class="read_only",
            impact_level="none",
            cost_estimate=0.0,
        ),
        ToolDefinition(
            name="snapshot",
            description="Capture the accessibility tree of the target window. Returns element list with names, roles, and refs.",
            parameters=(),
            handler=adapter.snapshot,
            security_level="safe",
            action_class="read_only",
            impact_level="none",
            cost_estimate=0.0,
        ),
        ToolDefinition(
            name="hover",
            description="Move the mouse to hover over an element without clicking.",
            parameters=(
                ToolParameter(name="target", type_name="str", required=True, description="Element to hover over"),
            ),
            handler=adapter.hover,
            security_level="safe",
            action_class="recoverable",
            impact_level="none",
        ),
    ]

    for td in tools:
        registry.register_definition(td)


def verify_notepad_text(hwnd: int, expected: str) -> bool:
    """Verify text exists in the Notepad window via UIA tree."""
    try:
        from deskaoy.adapters.uia_walker import UIAWalker
        walker = UIAWalker()
        snap = walker.walk_to_snapshot(hwnd=hwnd, url="win32://Notepad", title="Notepad")
        for node in snap.nodes.values():
            if expected.lower() in (node.name or "").lower():
                return True
            if node.value and expected.lower() in node.value.lower():
                return True
        # If UIA can't read value, try win32gui
        import win32gui
        text = win32gui.GetWindowText(hwnd)
        if expected.lower() in text.lower():
            return True
    except Exception as exc:
        logger.warning("Verification failed: %s", exc)
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_demo(task: str, provider: str, model: str | None, launch: bool) -> None:
    from deskaoy.adapters.windows import WindowsAdapter
    from deskaoy.agent.loop import AgentLoop
    from deskaoy.agent.registry import ToolRegistry
    from deskaoy.desktop_agent import DesktopAgent
    from deskaoy.llm.client import SimpleLLMClient
    from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

    # ── 1. Find or launch target window ─────────────────
    print("\n" + "=" * 60)
    print("  Desktop Agent — Integration Proof")
    print("=" * 60)
    print(f"\n[1/6] {'Launching' if launch else 'Finding'} target window...")

    proc = None
    hwnd = None

    if launch:
        proc = launch_notepad()
        hwnd = get_hwnd_from_pid(proc.pid)
        if hwnd is None:
            # Fallback: try finding by class
            hwnd = find_notepad_hwnd()
    else:
        hwnd = find_notepad_hwnd()

    if hwnd is None:
        print("      ✗ Could not find Notepad window.")
        print("        Run with --launch or open Notepad first.")
        if proc:
            proc.terminate()
        sys.exit(1)

    import win32gui
    title = win32gui.GetWindowText(hwnd)
    print(f"      → hwnd=0x{hwnd:X}, title=\"{title}\"")

    # ── 2. Connect DesktopAgent ─────────────────────────
    print("\n[2/6] Connecting DesktopAgent...")

    adapter = WindowsAdapter(hwnd=hwnd)
    registry = ToolRegistry()
    register_desktop_tools(registry, adapter)
    print(f"      → WindowsAdapter(hwnd=0x{hwnd:X})")
    print(f"      → ToolRegistry: {len(registry._tools)} tools")

    llm = SimpleLLMClient(provider=provider, model=model)
    if not llm.is_ready:
        print("      ✗ No LLM API key found!")
        print("        Set OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable.")
        if proc:
            proc.terminate()
        sys.exit(1)
    print(f"      → SimpleLLMClient(provider={llm.provider}, model={llm.model})")

    loop = AgentLoop(
        controller=adapter,
        registry=registry,
        llm_client=llm,
        max_steps=10,
        step_timeout=60.0,
    )

    agent = DesktopAgent(
        surface=adapter,
        agent_loop=loop,
    )
    print("      → DesktopAgent ready")

    # ── 3. Execute ──────────────────────────────────────
    print(f"\n[3/6] Executing: \"{task}\"")

    goal = AgentGoal(
        capability="automate",
        params={"instruction": task},
    )
    context = AgentContext(
        execution_id=f"demo-{int(time.time())}",
        timeout_seconds=120,
        cancellation_token=CancellationToken(),
    )

    result = await agent.execute(goal, context)

    # Print step trace
    if result.data and "steps" in result.data:
        for step in result.data["steps"]:
            action = step.get("action", "?")
            ok = "✓" if step.get("ok") else "✗"
            dur = step.get("duration_ms", 0)
            print(f"      Step {step.get('step', '?')}: {action} → {ok} ({dur:.0f}ms)")

    print(f"\n      Completion: {result.data.get('completion_reason', 'unknown') if result.data else 'unknown'}")

    # ── 4. Verification ─────────────────────────────────
    print("\n[4/6] Verification...")

    # Extract key terms from the task for verification
    # Simple heuristic: look for quoted strings or capitalized words
    verify_terms = []
    import re
    quotes = re.findall(r'"([^"]+)"', task)
    if quotes:
        verify_terms.extend(quotes)
    # Look for "Type X" or "write X" patterns
    type_match = re.search(r'(?:type|write|enter)\s+["\']?([^"\']+?)["\']?\s*(?:in|into|on|$)', task, re.IGNORECASE)
    if type_match:
        verify_terms.append(type_match.group(1).strip())

    if verify_terms:
        verified = verify_notepad_text(hwnd, verify_terms[0])
        status = "✅" if verified else "❌"
        print(f"      → Checking for \"{verify_terms[0]}\" in Notepad: {status}")
    else:
        print(f"      → Status: {result.status.value}")
        verified = result.status.value == "success"

    # ── 5. Memory ───────────────────────────────────────
    print("\n[5/6] Memory...")
    try:
        mem = agent.memory
        anchors = mem.list_anchors()
        print(f"      → {len(anchors)} anchor(s) recorded")
        for a in anchors[:3]:
            print(f"        • {a.action} → {a.selector_tier} (confidence={a.confidence:.2f})")
    except Exception as exc:
        print(f"      → Memory query: {exc}")

    # ── 6. Result ───────────────────────────────────────
    print(f"\n[6/6] Result: {result.status.value.upper()}")
    print(f"      Confidence: {result.confidence.score:.2f} ({result.confidence.reason})")
    print(f"      Duration: {result.metadata.get('duration_ms', 0):.0f}ms")

    # LLM usage
    if llm.usage.request_count > 0:
        print(f"      LLM: {llm.usage.request_count} requests, "
              f"{llm.usage.total_tokens} tokens, "
              f"{llm.usage.total_latency_ms:.0f}ms total")

    print()
    if verified:
        print("  ✅ Demo passed!")
    else:
        print("  ❌ Demo failed — check step trace above for details.")
    print()

    # Cleanup
    if proc:
        print("Cleaning up... closing Notepad.")
        proc.terminate()

    sys.exit(0 if verified else 1)


def main():
    parser = argparse.ArgumentParser(description="Desktop Agent integration proof")
    parser.add_argument(
        "--task", "-t",
        default="Type Hello World",
        help="Task instruction for the agent (default: 'Type Hello World')",
    )
    parser.add_argument(
        "--provider", "-p",
        default="auto",
        choices=["auto", "openai", "anthropic"],
        help="LLM provider (default: auto-detect from env vars)",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="LLM model name (default: gpt-4o-mini or claude-haiku-4-20250414)",
    )
    parser.add_argument(
        "--launch", "-l",
        action="store_true",
        default=True,
        help="Launch Notepad automatically (default: True)",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Don't launch Notepad; use existing window",
    )
    args = parser.parse_args()

    launch = not args.no_launch
    asyncio.run(run_demo(args.task, args.provider, args.model, launch))


if __name__ == "__main__":
    main()
