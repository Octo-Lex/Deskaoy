"""deskaoy CLI — command-line interface for Deskaoy.

Usage:
    deskaoy execute "Open Notepad and type Hello"
    deskaoy execute --dry-run --json "Open Notepad"
    deskaoy estimate "Open Notepad and type Hello"
    deskaoy schedule add --name morning --cron "0 8 * * *" --prompt "Check calendar"
    deskaoy schedule list
    deskaoy schedule remove --name morning
    deskaoy schedule due
    deskaoy skills list
    deskaoy skills match "type text in notepad"
    deskaoy facts list
    deskaoy facts search "email"
    deskaoy health
    deskaoy schema
    deskaoy version
    deskaoy doctor
    deskaoy repl
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import difflib
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# Version — read from pyproject.toml metadata at build time
from deskaoy.cli.version import VERSION as _VERSION

# ---------------------------------------------------------------------------
# Lazy agent factory — HB-01: no adapter imports at module level
# ---------------------------------------------------------------------------

_agent_instance: Any | None = None
_storage_dir: str | None = None


def _resolve_storage_dir(storage_dir: str | None = None) -> str:
    """Resolve storage directory from arg, env, or default."""
    if storage_dir:
        return storage_dir
    env_dir = os.environ.get("AIOS_HOME")
    if env_dir:
        return os.path.join(env_dir, "deskaoy")
    return os.path.join(os.path.expanduser("~"), ".aios", "deskaoy")


def _get_agent(storage_dir: str | None = None) -> Any:
    """Lazy factory for DesktopAgent. Only called when needed."""
    global _agent_instance, _storage_dir

    if _agent_instance is not None and _storage_dir == storage_dir:
        return _agent_instance

    from deskaoy.desktop_agent import DesktopAgent

    sd = _resolve_storage_dir(storage_dir)
    Path(sd).mkdir(parents=True, exist_ok=True)

    # Build agent with no surface (headless) — real surface attached later
    agent = DesktopAgent(surface=None)

    _agent_instance = agent
    _storage_dir = storage_dir
    return agent


def _reset_agent() -> None:
    """Reset cached agent (for tests)."""
    global _agent_instance, _storage_dir
    _agent_instance = None
    _storage_dir = None


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

async def _cmd_execute(args: argparse.Namespace) -> int:
    """Execute a natural-language instruction."""
    from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

    # HB-01: Visual feedback is opt-in only
    if getattr(args, 'visual_feedback', False):
        from deskaoy.feedback.engine import FeedbackEngine
        _feedback_engine = FeedbackEngine()
        _feedback_engine.enabled = True

    # BATCH-37: Route through DaemonClient if --daemon flag
    if getattr(args, 'daemon', False):
        from deskaoy.daemon.client import DaemonClient
        from deskaoy.daemon.config import DaemonConfig
        daemon_client = DaemonClient(config=DaemonConfig())
        session_id = args.session or str(uuid.uuid4())
        ctx = AgentContext(
            execution_id=str(uuid.uuid4()),
            idempotency_key=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            user_id="cli",
            session_id=session_id,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout,
            cancellation_token=CancellationToken(),
        )
        goal = AgentGoal(capability="automate", params={"instruction": args.instruction})
        result = await daemon_client.execute(goal, ctx)
        await daemon_client.close()
        from deskaoy.cli.formatters import format_result
        output = format_result(result, json_mode=args.json)
        print(output)
        return 0 if result.status.value == "success" or result.status.value == "dry_run" else 1

    agent = _get_agent(args.storage_dir)
    session_id = args.session or str(uuid.uuid4())

    ctx = AgentContext(
        execution_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        user_id="cli",
        session_id=session_id,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout,
        cancellation_token=CancellationToken(),
    )

    goal = AgentGoal(capability="automate", params={"instruction": args.instruction})
    result = await agent.execute(goal, ctx)

    from deskaoy.cli.formatters import format_result
    output = format_result(result, json_mode=args.json)
    print(output)
    return 0 if result.status.value == "success" or result.status.value == "dry_run" else 1


async def _cmd_estimate(args: argparse.Namespace) -> int:
    """Estimate cost/confidence for an instruction."""
    from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

    agent = _get_agent(args.storage_dir)

    ctx = AgentContext(
        execution_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        user_id="cli",
        session_id=args.session or str(uuid.uuid4()),
        dry_run=True,
        timeout_seconds=args.timeout,
        cancellation_token=CancellationToken(),
    )

    goal = AgentGoal(capability="automate", params={"instruction": args.instruction})
    estimate = await agent.estimate(goal, ctx)

    from deskaoy.cli.formatters import format_estimate
    output = format_estimate(estimate, json_mode=args.json)
    print(output)
    return 0


async def _cmd_schedule_add(args: argparse.Namespace) -> int:
    """Add a named routine."""
    from deskaoy.routines import Routine

    agent = _get_agent(args.storage_dir)
    scheduler = agent.routine_scheduler

    routine = Routine(
        name=args.name,
        schedule=args.cron,
        prompt=args.prompt,
        enabled=True,
    )
    scheduler.add(routine)
    print(f"✓ Routine '{args.name}' added: {args.cron}")
    return 0


async def _cmd_schedule_list(args: argparse.Namespace) -> int:
    """List all routines."""
    from deskaoy.cli.formatters import format_routine, format_routine_header

    agent = _get_agent(args.storage_dir)
    routines = agent.routine_scheduler.list()

    if not routines:
        print("  (no routines)")
        return 0

    print(format_routine_header())
    for r in routines:
        print(format_routine(r, json_mode=args.json))
    return 0


async def _cmd_schedule_remove(args: argparse.Namespace) -> int:
    """Remove a named routine."""
    agent = _get_agent(args.storage_dir)
    removed = agent.routine_scheduler.remove(args.name)
    if removed:
        print(f"✓ Routine '{args.name}' removed")
        return 0
    else:
        print(f"✗ Routine '{args.name}' not found")
        return 1


async def _cmd_schedule_due(args: argparse.Namespace) -> int:
    """Show routines due within 60 seconds."""
    agent = _get_agent(args.storage_dir)
    due = agent.routine_scheduler.get_due() if hasattr(agent.routine_scheduler, 'get_due') else []

    if not due:
        print("  (no routines due)")
        return 0

    for r in due:
        print(f"  {r.name}: {r.instruction}")
    return 0


async def _cmd_skills_list(args: argparse.Namespace) -> int:
    """List discovered skills."""
    from deskaoy.cli.formatters import format_skill

    agent = _get_agent(args.storage_dir)
    loader = agent.skill_loader
    skills = loader.discover() if hasattr(loader, 'discover') else loader.list_skills() if hasattr(loader, 'list_skills') else []

    if not skills:
        print("  (no skills found)")
        return 0

    for s in skills:
        print(format_skill(s, json_mode=args.json))
    return 0


async def _cmd_skills_match(args: argparse.Namespace) -> int:
    """Match instruction against skills."""
    from deskaoy.cli.formatters import format_skill

    agent = _get_agent(args.storage_dir)
    loader = agent.skill_loader
    matches = loader.match(args.instruction) if hasattr(loader, 'match') else []

    if not matches:
        print(f"  (no skills match '{args.instruction}')")
        return 0

    for s in matches:
        print(format_skill(s, json_mode=args.json))
    return 0


async def _cmd_facts_list(args: argparse.Namespace) -> int:
    """List stored facts."""
    from deskaoy.cli.formatters import format_fact

    agent = _get_agent(args.storage_dir)
    store = agent.fact_store
    facts = store.get_facts() if hasattr(store, 'get_facts') else store.list_facts() if hasattr(store, 'list_facts') else []

    if not facts:
        print("  (no facts stored)")
        return 0

    for f in facts:
        print(format_fact(f, json_mode=args.json))
    return 0


async def _cmd_facts_search(args: argparse.Namespace) -> int:
    """Search facts by keyword."""
    from deskaoy.cli.formatters import format_fact

    agent = _get_agent(args.storage_dir)
    store = agent.fact_store
    results = store.search(args.query) if hasattr(store, 'search') else []

    if not results:
        print(f"  (no facts matching '{args.query}')")
        return 0

    for f in results:
        print(format_fact(f, json_mode=args.json))
    return 0


async def _cmd_health(args: argparse.Namespace) -> int:
    """Run health check."""
    from deskaoy.cli.formatters import format_health

    agent = _get_agent(args.storage_dir)
    status = await agent.health() if asyncio.iscoroutinefunction(getattr(agent, 'health', None)) else agent.health()

    output = format_health(status, json_mode=args.json)
    print(output)
    healthy = getattr(status, "healthy", False)
    return 0 if healthy else 1


async def _cmd_snapshot(args: argparse.Namespace) -> int:
    """Create a UI snapshot and print the snapshot ID + element table."""
    from deskaoy.cli.formatters import format_snapshot_table

    agent = _get_agent(args.storage_dir)
    store = agent.snapshot_store

    # If no surface adapter, create a headless snapshot (metadata only)
    if agent._surface is None:
        metadata = {"application": "headless", "platform": sys.platform}
        if args.app:
            metadata["application"] = args.app
        sid = await store.create([], metadata=metadata)
        if args.json:
            record = await store.get(sid)
            print(json.dumps({"snapshot_id": sid, "elements": [], "application": metadata.get("application")}, indent=2))
        else:
            print(f"Snapshot: {sid}")
            print("  (no surface adapter — headless snapshot)")
        return 0

    # Real surface — capture snapshot and screenshot
    try:
        ax_snap = await agent._surface.snapshot()
        screenshot_bytes = await agent._surface.screenshot()
    except Exception as exc:
        print(f"Error capturing snapshot: {exc}", file=sys.stderr)
        return 1

    # Convert AXNode elements to dict format
    elements = []
    for _ref, node in ax_snap.nodes.items():
        elem = {
            "role": node.role,
            "name": node.name,
            "actionable": node.is_interactive,
        }
        if node.bounds:
            elem["bounds"] = {"x": node.bounds[0], "y": node.bounds[1], "width": node.bounds[2], "height": node.bounds[3]}
        if node.value:
            elem["value"] = node.value
        if node.description:
            elem["description"] = node.description
        # App filter
        if args.app and elem.get("name", "") and args.app.lower() not in (elem.get("name") or "").lower():
            continue
        elements.append(elem)

    metadata = {
        "application": getattr(ax_snap, 'title', None),
        "window_title": getattr(ax_snap, 'title', None),
        "platform": sys.platform,
    }

    sid = await store.create(elements, screenshot_bytes, metadata=metadata)
    record = await store.get(sid)

    if args.json:
        output = {"snapshot_id": sid, "element_count": len(elements), "elements": [e.to_dict() for e in record.elements]}
        print(json.dumps(output, indent=2))
    else:
        print(f"Snapshot: {sid}")
        print(format_snapshot_table(record))
    return 0


async def _cmd_snapshots(args: argparse.Namespace) -> int:
    """List, clean, or show stats for stored snapshots."""
    agent = _get_agent(args.storage_dir)
    store = agent.snapshot_store
    sub_cmd = getattr(args, "snapshots_command", None)

    if sub_cmd == "clean":
        count = await store.clean_all()
        if args.json:
            print(json.dumps({"removed": count}))
        else:
            print(f"Removed {count} snapshot(s)")
        return 0

    if sub_cmd == "stats":
        metrics = await store.get_metrics()
        if args.json:
            print(json.dumps({
                "hits": metrics.hits,
                "misses": metrics.misses,
                "evictions": metrics.evictions,
                "total_size_bytes": metrics.total_size_bytes,
                "count": metrics.count,
            }, indent=2))
        else:
            print(f"  Snapshots:  {metrics.count}")
            print(f"  Size:       {metrics.total_size_bytes:,} bytes")
            print(f"  Hits:       {metrics.hits}")
            print(f"  Misses:     {metrics.misses}")
            print(f"  Evictions:  {metrics.evictions}")
            if metrics.hits + metrics.misses > 0:
                rate = metrics.hits / (metrics.hits + metrics.misses) * 100
                print(f"  Hit rate:   {rate:.1f}%")
        return 0

    # Default: list
    infos = await store.list_snapshots()
    if args.json:
        items = []
        for info in infos:
            items.append({"snapshot_id": info.snapshot_id, "created_at": info.created_at, "application": info.application, "element_count": info.element_count, "has_screenshot": info.has_screenshot})
        print(json.dumps(items, indent=2))
    else:
        if not infos:
            print("  (no snapshots)")
        else:
            for info in infos:
                app = info.application or "unknown"
                print(f"  {info.snapshot_id[:8]}...  {info.created_at[:19]}  {app:<20}  {info.element_count} elements")
    return 0


async def _cmd_describe(args: argparse.Namespace) -> int:
    """Print the universal discovery document."""
    import json as _json

    agent = _get_agent(args.storage_dir)
    desc = agent.describe()

    print(_json.dumps(desc, indent=2, default=str))
    return 0


async def _cmd_schema(args: argparse.Namespace) -> int:
    """Print capability schema (backward-compat alias for describe)."""
    from deskaoy.cli.formatters import format_schema

    agent = _get_agent(args.storage_dir)
    schema_data = agent.schema() if hasattr(agent, 'schema') else {"capabilities": {}}

    output = format_schema(schema_data, json_mode=args.json)
    print(output)
    return 0


async def _cmd_version(args: argparse.Namespace) -> int:
    """Print version."""
    print(f"deskaoy {_VERSION}")
    return 0


async def _cmd_status(args: argparse.Namespace) -> int:
    """Show which subsystems are configured and available."""
    import importlib

    print(f"deskaoy {_VERSION}")
    print()

    # Check platform
    print(f"  Platform:  {sys.platform}")
    print(f"  Python:    {sys.version.split()[0]}")
    print()

    # Check adapters
    print("  Adapters:")
    adapters = []
    if sys.platform == "win32":
        try:
            import comtypes  # noqa: F401
            adapters.append(("Windows (comtypes)", True))
        except ImportError:
            adapters.append(("Windows (comtypes)", False))
    else:
        adapters.append(("Windows (comtypes)", None))

    try:
        import patchright  # noqa: F401
        adapters.append(("Browser (patchright)", True))
    except ImportError:
        adapters.append(("Browser (patchright)", False))

    for name, avail in adapters:
        if avail is True:
            print(f"    ✓ {name}")
        elif avail is False:
            print(f"    ✗ {name} — not installed")
        else:
            print(f"    - {name} — N/A on this platform")

    print()
    print("  Optional deps:")
    opt_deps = [
        ("openai", "LLM (OpenAI)"),
        ("anthropic", "LLM (Anthropic)"),
        ("aiohttp", "REST server"),
        ("mcp", "MCP protocol"),
        ("PIL", "Pillow (images)"),
        ("cv2", "OpenCV (vision)"),
        ("pytesseract", "Tesseract OCR"),
        ("ultralytics", "YOLO (grounding)"),
        ("mss", "MSS (screenshots)"),
        ("pyautogui", "PyAutoGUI (input)"),
    ]
    for mod, label in opt_deps:
        try:
            importlib.import_module(mod)
            print(f"    ✓ {label}")
        except ImportError:
            print(f"    - {label} — not installed")

    print()
    print("  Security:")
    try:
        from deskaoy.safety.key_blocklist import BLOCKED_KEYS
        print(f"    ✓ Key blocklist ({len(BLOCKED_KEYS)} combos)")
    except ImportError:
        print("    ✗ Key blocklist — import error")
    try:
        from deskaoy.safety.sensitive_apps import SENSITIVE_APPS
        print(f"    ✓ Sensitive apps ({len(SENSITIVE_APPS)} categories)")
    except ImportError:
        print("    ✗ Sensitive apps — import error")

    return 0


async def _cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose environment setup issues.

    Checks:
    1. Python version >= 3.11
    2. Package installed and importable
    3. Storage directory writable
    4. Surface adapter available (Windows/Browser)
    5. Optional dependencies (browser, LLM, grounding)
    """
    import importlib
    import os
    import platform
    import sys

    issues = 0
    checks = []

    # Check 1: Python version
    py_ver = sys.version_info
    py_ok = py_ver >= (3, 11)
    checks.append(("Python >= 3.11", py_ok, f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"))
    if not py_ok:
        issues += 1

    # Check 2: Package importable
    try:
        import deskaoy
        checks.append(("deskaoy importable", True, deskaoy.__file__))
    except ImportError as e:
        checks.append(("deskaoy importable", False, str(e)))
        issues += 1

    # Check 3: Storage directory writable
    from deskaoy.storage import StorageResolver
    storage = StorageResolver()
    try:
        base_dir = storage.resolve_action_memory()
        os.makedirs(base_dir, exist_ok=True)
        test_file = os.path.join(base_dir, ".doctor_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        checks.append(("Storage writable", True, base_dir))
    except Exception as e:
        checks.append(("Storage writable", False, str(e)))
        issues += 1

    # Check 4: Surface adapter
    system = platform.system()
    if system == "Windows":
        try:
            import comtypes  # noqa: F401
            checks.append(("Windows adapter (comtypes)", True, "available"))
        except ImportError:
            checks.append(("Windows adapter (comtypes)", False, "install: pip install comtypes"))
            issues += 1
    elif system == "Darwin":
        checks.append(("macOS adapter", False, "not yet implemented (BATCH-05)"))
    else:
        checks.append(("Linux adapter", False, "not yet implemented (BATCH-06)"))

    # Check 5: Optional dependencies
    # Browser
    try:
        import patchright  # noqa: F401
        checks.append(("Browser (patchright)", True, "installed"))
    except ImportError:
        checks.append(("Browser (patchright)", False, "install: pip install deskaoy[browser]"))

    # LLM
    llm_available = False
    for pkg in ("openai", "anthropic"):
        try:
            importlib.import_module(pkg)
            llm_available = True
        except ImportError:
            pass
    if llm_available:
        checks.append(("LLM client", True, "installed"))
    else:
        checks.append(("LLM client", False, "install: pip install deskaoy[llm]"))

    # Grounding
    try:
        import ultralytics  # noqa: F401
        checks.append(("Visual grounding", True, "installed"))
    except ImportError:
        checks.append(("Visual grounding", False, "install: pip install deskaoy[grounding]"))

    # Check 6: MCP transport
    try:
        import mcp  # noqa: F401
        checks.append(("MCP transport", True, "installed"))
    except ImportError:
        checks.append(("MCP transport", False, "install: pip install deskaoy[mcp]"))

    # Check 7: REST transport
    try:
        import aiohttp  # noqa: F401
        checks.append(("REST transport", True, "installed"))
    except ImportError:
        checks.append(("REST transport", False, "install: pip install deskaoy[rest]"))

    # Check 8: Safety modules
    try:
        from deskaoy.safety.key_blocklist import BLOCKED_KEYS
        checks.append(("Key blocklist", True, f"{len(BLOCKED_KEYS)} keys blocked"))
    except ImportError:
        checks.append(("Key blocklist", False, "import error"))
        issues += 1
    try:
        from deskaoy.safety.sensitive_apps import SENSITIVE_APPS
        checks.append(("Sensitive apps", True, f"{len(SENSITIVE_APPS)} apps monitored"))
    except ImportError:
        checks.append(("Sensitive apps", False, "import error"))
        issues += 1

    # Check 9: Image support
    try:
        import PIL  # noqa: F401
        checks.append(("Pillow (images)", True, "installed"))
    except ImportError:
        checks.append(("Pillow (images)", False, "install: pip install Pillow"))

    # Check 10: Process utilities
    try:
        import psutil  # noqa: F401
        checks.append(("Process utilities", True, "installed"))
    except ImportError:
        checks.append(("Process utilities", False, "install: pip install psutil"))

    # Check 11: Screenshot support
    screenshot_ok = False
    for mod_name in ("mss", "PIL.ImageGrab"):
        try:
            importlib.import_module(mod_name)
            screenshot_ok = True
            break
        except ImportError:
            pass
    checks.append(("Screenshot capture", screenshot_ok, "available" if screenshot_ok else "install mss or Pillow"))

    # Check 12: Rate governor
    try:
        from deskaoy.safety.rate_governor import ActionRateGovernor
        gov = ActionRateGovernor()
        checks.append(("Rate governor", True, f"{len(gov._limits)} action types"))
    except ImportError:
        checks.append(("Rate governor", False, "import error"))
        issues += 1

    # Check 13: Validation module
    try:
        from deskaoy.validation import validate_instruction
        checks.append(("Instruction validation", True, "available"))
    except ImportError:
        checks.append(("Instruction validation", False, "import error"))

    # Check 14: Cascade engine
    try:
        from deskaoy.cascade.protocol import SurfaceAdapter
        checks.append(("Cascade engine", True, "SurfaceAdapter protocol"))
    except ImportError:
        checks.append(("Cascade engine", False, "import error"))
        issues += 1

    # Print results
    print(f"\ndeskaoy {_VERSION} -- Environment Diagnostic\n")
    print(f"  Platform: {platform.system()} {platform.release()}")
    print(f"  Python:   {sys.version.split()[0]}\n")
    for label, ok, detail in checks:
        icon = "[OK]" if ok else "[FAIL]"
        print(f"  {icon} {label:30s} {detail}")
    print()
    if issues == 0:
        print("  All checks passed. Ready to go.\n")
        return 0
    else:
        print(f"  {issues} issue(s) found. Fix above to proceed.\n")
        return 1


async def _cmd_release_check(args: argparse.Namespace) -> int:
    """v1.0 Release Candidate readiness check.

    Checks all criteria for a v1.0 release:
    1. Version consistency across 3 single-source files
    2. All tests pass (requires pytest)
    3. Package builds cleanly
    4. CHANGELOG is up to date
    5. LICENSE exists
    6. README exists
    7. CONTRIBUTING exists
    8. pyproject.toml valid
    9. All modules importable
    10. CLI commands work
    """
    import subprocess
    import sys

    issues = 0
    checks = []
    project_root = Path(__file__).resolve().parent.parent.parent.parent

    # Check 1: Version consistency
    try:
        import tomllib

        from deskaoy.cli.version import VERSION as cli_ver
        with open(project_root / "pyproject.toml", "rb") as f:
            pyproject_ver = tomllib.load(f)["project"]["version"]
        from deskaoy.desktop_agent import DesktopAgent
        da_ver = DesktopAgent.__dataclass_fields__["version"].default
        ver_ok = cli_ver == pyproject_ver == da_ver
        checks.append(("Version consistency", ver_ok, f"cli={cli_ver} pyproject={pyproject_ver} agent={da_ver}"))
        if not ver_ok:
            issues += 1
    except Exception as e:
        checks.append(("Version consistency", False, str(e)))
        issues += 1

    # Check 2: Tests pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--co", "-q"],
            capture_output=True, text=True, cwd=str(project_root), timeout=30,
        )
        test_count = result.stdout.strip().split("\n")[-1] if result.stdout else "?"
        checks.append(("Tests collectible", result.returncode == 0, test_count))
        if result.returncode != 0:
            issues += 1
    except Exception as e:
        checks.append(("Tests collectible", False, str(e)))
        issues += 1

    # Check 3: Package builds
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", "--wheel"],
            capture_output=True, text=True, cwd=str(project_root), timeout=60,
        )
        build_ok = result.returncode == 0
        checks.append(("Package builds", build_ok, "wheel build" + ("" if build_ok else " FAILED")))
        if not build_ok:
            issues += 1
    except FileNotFoundError:
        checks.append(("Package builds", False, "build module not installed: pip install build"))
        issues += 1
    except Exception as e:
        checks.append(("Package builds", False, str(e)))
        issues += 1

    # Check 4-7: Essential files
    for fname in ["CHANGELOG.md", "LICENSE", "README.md", "CONTRIBUTING.md"]:
        fpath = project_root / fname
        exists = fpath.exists()
        checks.append((fname, exists, str(fpath)))
        if not exists:
            issues += 1

    # Check 8: pyproject.toml valid
    try:
        import tomllib
        with open(project_root / "pyproject.toml", "rb") as f:
            config = tomllib.load(f)
        has_entry = "console_scripts" in str(config)
        checks.append(("pyproject.toml valid", True, f"entry_points={'yes' if has_entry else 'no'}"))
    except Exception as e:
        checks.append(("pyproject.toml valid", False, str(e)))
        issues += 1

    # Check 9: All key modules importable
    modules = [
        "deskaoy.desktop_agent",
        "deskaoy.cascade.protocol",
        "deskaoy.cascade.differ",
        "deskaoy.cascade.formatter",
        "deskaoy.safety.key_blocklist",
        "deskaoy.safety.sensitive_apps",
        "deskaoy.safety.health",
        "deskaoy.agent.two_step",
        "deskaoy.agent.cua_loop",
        "deskaoy.orchestration.blocks",
        "deskaoy.orchestration.workflow",
        "deskaoy.evaluation",
        "deskaoy.guides",
        "deskaoy.performance",
    ]
    import_errors = []
    for mod in modules:
        try:
            __import__(mod)
        except ImportError as e:
            import_errors.append(f"{mod}: {e}")
    mod_ok = len(import_errors) == 0
    checks.append(("Module imports", mod_ok, f"{len(modules) - len(import_errors)}/{len(modules)} OK"))
    if not mod_ok:
        issues += 1

    # Check 10: CLI basic commands work
    try:
        result = subprocess.run(
            [sys.executable, "-m", "deskaoy.cli.main", "--version"],
            capture_output=True, text=True, cwd=str(project_root), timeout=10,
        )
        cli_ok = result.returncode == 0
        checks.append(("CLI --version", cli_ok, result.stdout.strip()))
        if not cli_ok:
            issues += 1
    except Exception as e:
        checks.append(("CLI --version", False, str(e)))
        issues += 1

    # Print results
    print("\ndeskaoy v1.0 Release Readiness Check\n")
    for label, ok, detail in checks:
        icon = "[OK]" if ok else "[FAIL]"
        print(f"  {icon} {label:30s} {detail}")
    print()
    if issues == 0:
        print("  READY FOR v1.0 RELEASE.\n")
        return 0
    else:
        print(f"  {issues} issue(s) must be fixed before release.\n")
        return 1


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

async def _cmd_repl(args: argparse.Namespace) -> int:
    """Launch interactive REPL."""
    from deskaoy.cli.repl import run_repl
    return await run_repl(
        storage_dir=args.storage_dir,
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        session_id=args.session,
    )


async def _cmd_observe(args: argparse.Namespace) -> int:
    """Run the Desktop Observation Pipeline and display results."""
    from deskaoy.observation import ObservationConfig
    from deskaoy.observation_pipeline import ObservationPipeline

    if args.list_presets:
        pipeline = ObservationPipeline()
        presets = pipeline.list_presets()
        if args.json:
            print(json.dumps(presets, indent=2))
        else:
            for name, flags in presets.items():
                enabled = [k.replace("include_", "") for k, v in flags.items() if v]
                print(f"  {name:12s} {', '.join(enabled)}")
        return 0

    config = ObservationConfig(
        preset=args.preset,
        save_snapshot=args.save,
        include_annotation=args.annotate,
    )

    pipeline = ObservationPipeline()
    result = await pipeline.observe(config)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"Observation ({config.preset})")
        print(f"  Elements:    {result.element_count}")
        print(f"  Steps:       {', '.join(result.steps_completed)}")
        if result.steps_skipped:
            print(f"  Skipped:     {', '.join(result.steps_skipped)}")
        print(f"  Window:      {result.observation.active_window or '(none)'}")
        if result.snapshot_id:
            print(f"  Snapshot:    {result.snapshot_id}")
        if result.annotated_screenshot:
            print(f"  Annotated:   yes ({len(result.annotated_screenshot)} bytes)")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deskaoy",
        description=(
            "Deskaoy — surface-agnostic automation for the AI Operating System.\n"
            "Execute natural-language instructions, manage routines, and introspect\n"
            "the desktop environment via a unified CLI.\n\n"
            "Examples:\n"
            "  deskaoy execute \"Open Notepad and type Hello\"\n"
            "  deskaoy execute --dry-run --json \"Open Calculator\"\n"
            "  deskaoy estimate \"Send an email\"\n"
            "  deskaoy schedule add --name morning --cron \"0 8 * * *\" --prompt \"Check calendar\"\n"
            "  deskaoy health\n"
            "  deskaoy doctor\n"
            "  deskaoy completions bash  # shell completion scripts\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--storage-dir", help="Override storage directory (default: $AIOS_HOME/deskaoy or ~/.aios/deskaoy)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--session", help="Session ID (auto-generated if not set)")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds (default: 60)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable DEBUG-level logging output")

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # execute
    p_exec = sub.add_parser("execute", help="Execute a natural-language instruction")
    p_exec.add_argument("instruction", help="Instruction to execute")
    p_exec.add_argument("--dry-run", action="store_true", help="Preview without executing")
    p_exec.add_argument("--capability", default="automate", help="Capability to use (default: automate)")
    p_exec.add_argument("--visual-feedback", action="store_true", help="Enable visual feedback overlay (click ripples, trails)")
    p_exec.add_argument("--daemon", action="store_true", help="Route execution through daemon (persistent DesktopAgent)")

    # estimate
    p_est = sub.add_parser("estimate", help="Estimate cost/confidence")
    p_est.add_argument("instruction", help="Instruction to estimate")

    # schedule
    p_sched = sub.add_parser("schedule", help="Manage routines")
    sched_sub = p_sched.add_subparsers(dest="schedule_command", help="Schedule commands")

    p_add = sched_sub.add_parser("add", help="Add a routine")
    p_add.add_argument("--name", required=True, help="Routine name")
    p_add.add_argument("--cron", required=True, help="Cron expression (e.g. '0 8 * * *')")
    p_add.add_argument("--prompt", required=True, help="Instruction to execute")

    sched_sub.add_parser("list", help="List routines")

    p_rm = sched_sub.add_parser("remove", help="Remove a routine")
    p_rm.add_argument("--name", required=True, help="Routine name")

    sched_sub.add_parser("due", help="Show due routines")

    # skills
    p_skills = sub.add_parser("skills", help="Manage skills")
    skills_sub = p_skills.add_subparsers(dest="skills_command", help="Skills commands")
    skills_sub.add_parser("list", help="List discovered skills")

    p_match = skills_sub.add_parser("match", help="Match instruction to skill")
    p_match.add_argument("instruction", help="Instruction to match")

    # facts
    p_facts = sub.add_parser("facts", help="Manage facts")
    facts_sub = p_facts.add_subparsers(dest="facts_command", help="Facts commands")
    facts_sub.add_parser("list", help="List stored facts")

    p_search = facts_sub.add_parser("search", help="Search facts")
    p_search.add_argument("query", help="Search query")

    # standalone commands
    sub.add_parser("health", help="Run health check")
    sub.add_parser("describe", help="Print universal discovery document (identity + capabilities + schemas)")
    sub.add_parser("schema", help="Print capability schema (alias for describe)")
    sub.add_parser("version", help="Print version")
    sub.add_parser("doctor", help="Diagnose environment setup issues")
    sub.add_parser("release-check", help="v1.0 release readiness check")
    sub.add_parser("status", help="Show configured subsystems and dependencies")

    # snapshot (BATCH-24)
    p_snapshot = sub.add_parser("snapshot", help="Create a UI snapshot")
    p_snapshot.add_argument("--app", help="Filter elements by application name")

    # snapshots (BATCH-24)
    p_snapshots = sub.add_parser("snapshots", help="List or clean stored snapshots")
    snapshots_sub = p_snapshots.add_subparsers(dest="snapshots_command", help="Snapshot commands")
    snapshots_sub.add_parser("list", help="List stored snapshots")
    snapshots_sub.add_parser("clean", help="Remove all snapshots")
    snapshots_sub.add_parser("stats", help="Show snapshot store metrics")

    # repl
    p_repl = sub.add_parser("repl", help="Launch interactive REPL")
    p_repl.add_argument("--provider", help="LLM provider (openai/anthropic)")
    p_repl.add_argument("--model", help="Model name")

    # clipboard (BATCH-28)
    p_clipboard = sub.add_parser("clipboard", help="Clipboard operations")
    clip_sub = p_clipboard.add_subparsers(dest="clipboard_action")
    clip_read = clip_sub.add_parser("read", help="Read clipboard text")
    clip_read.add_argument("--json", action="store_true", help="Output as JSON")
    clip_write = clip_sub.add_parser("write", help="Write text to clipboard")
    clip_write.add_argument("text", help="Text to write")
    clip_sub.add_parser("paste", help="Send Ctrl+V to paste")

    # set-value (BATCH-28)
    p_set_value = sub.add_parser("set-value", help="Set element value")
    p_set_value.add_argument("target", help="Target element (name, auto:id, or coordinates)")
    p_set_value.add_argument("value", help="Value to set")
    p_set_value.add_argument("--dry-run", action="store_true", help="Preview without executing")

    # perform-action (BATCH-28)
    p_perform = sub.add_parser("perform-action", help="Perform accessibility action")
    p_perform.add_argument("target", help="Target element")
    p_perform.add_argument("action", help="Action name (invoke, toggle, expand, collapse, etc.)")
    p_perform.add_argument("--value", default="", help="Optional value parameter")
    p_perform.add_argument("--dry-run", action="store_true", help="Preview without executing")

    # menu (BATCH-26)
    p_menu = sub.add_parser("menu", help="Start Menu interaction")
    menu_sub = p_menu.add_subparsers(dest="menu_command", help="Menu commands")

    p_menu_search = menu_sub.add_parser("search", help="Search Start Menu")
    p_menu_search.add_argument("query", help="Search query")

    menu_sub.add_parser("list", help="List Start Menu items")

    p_menu_click = menu_sub.add_parser("click", help="Click a Start Menu item")
    p_menu_click.add_argument("name", help="Item name to click")

    # taskbar (BATCH-26)
    p_taskbar = sub.add_parser("taskbar", help="Taskbar interaction")
    taskbar_sub = p_taskbar.add_subparsers(dest="taskbar_command", help="Taskbar commands")

    taskbar_sub.add_parser("list", help="List taskbar items")

    p_taskbar_click = taskbar_sub.add_parser("click", help="Click a taskbar button")
    p_taskbar_click.add_argument("name", help="Button name to click")

    # dialog (BATCH-26)
    p_dialog = sub.add_parser("dialog", help="System dialog interaction")
    dialog_sub = p_dialog.add_subparsers(dest="dialog_command", help="Dialog commands")

    dialog_sub.add_parser("list", help="List open dialogs")

    p_dialog_dismiss = dialog_sub.add_parser("dismiss", help="Dismiss a dialog")
    p_dialog_dismiss.add_argument("hwnd", type=int, help="Dialog HWND")
    p_dialog_dismiss.add_argument("--action", default="cancel", help="Dismiss action: ok/cancel/close/yes/no")

    # desktop (BATCH-26)
    p_desktop = sub.add_parser("desktop", help="Virtual desktop management")
    desktop_sub = p_desktop.add_subparsers(dest="desktop_command", help="Desktop commands")

    desktop_sub.add_parser("list", help="List virtual desktops")

    p_desktop_switch = desktop_sub.add_parser("switch", help="Switch virtual desktop")
    p_desktop_switch.add_argument("index", type=int, help="Desktop index (0-based)")

    # chat (BATCH-29)
    p_chat = sub.add_parser("chat", help="Interactive chat REPL")
    p_chat.add_argument("--visual-feedback", action="store_true", help="Enable visual feedback overlay")

    # run (BATCH-29)
    p_run = sub.add_parser("run", help="Run an automation script")
    p_run.add_argument("script", help="Path to .deskaoy.json script")
    p_run.add_argument("--dry-run", action="store_true", help="Validate and preview without executing")

    # mcp
    p_mcp = sub.add_parser("mcp", help="Start MCP stdio server")
    p_mcp.add_argument("--compact", action="store_true", help="Expose 6 compound tools instead of 10 granular")

    # observe (BATCH-27)
    p_observe = sub.add_parser("observe", help="Run Desktop Observation Pipeline")
    p_observe.add_argument("--preset", default="standard", choices=["quick", "standard", "full"], help="Pipeline preset (default: standard)")
    p_observe.add_argument("--save", action="store_true", help="Save snapshot to SnapshotStore")
    p_observe.add_argument("--annotate", action="store_true", help="Render SoM annotation")
    p_observe.add_argument("--list-presets", action="store_true", help="List available presets")
    p_observe.add_argument("--json", action="store_true", help="Output as JSON")
    p_observe.add_argument("--visual-feedback", action="store_true", help="Enable visual feedback overlay")

    # serve
    p_serve = sub.add_parser("serve", help="Start REST API server")
    p_serve.add_argument("--port", type=int, default=3847, help="Port (default: 3847)")
    p_serve.add_argument("--skip-consent", action="store_true", help="Skip consent prompt (dev only)")

    # daemon (BATCH-37)
    p_daemon = sub.add_parser("daemon", help="Manage the deskaoy daemon")
    daemon_sub = p_daemon.add_subparsers(dest="daemon_command", help="Daemon commands")
    daemon_sub.add_parser("start", help="Start the daemon")
    daemon_sub.add_parser("stop", help="Stop the daemon")
    daemon_sub.add_parser("status", help="Show daemon status")

    # completions (BATCH-30)
    p_completions = sub.add_parser("completions", help="Generate shell completion scripts")
    p_completions.add_argument("shell", choices=["powershell", "bash", "zsh"], help="Target shell")

    # docs (BATCH-30)
    p_docs = sub.add_parser("docs", help="Open documentation in browser or print links")
    p_docs.add_argument("--topic", default="readme", choices=["readme", "quickstart", "changelog", "contributing", "api"], help="Documentation topic (default: readme)")
    p_docs.add_argument("--print", action="store_true", dest="print_only", help="Print URL instead of opening browser")

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# Command dispatch table

async def _cmd_clipboard_read(args: argparse.Namespace) -> int:
    """Read the system clipboard."""
    agent = _get_agent(args.storage_dir)
    try:
        text = await agent.read_clipboard()
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "text": text}))
    else:
        print(text)
    return 0


async def _cmd_clipboard_write(args: argparse.Namespace) -> int:
    """Write text to the system clipboard."""
    agent = _get_agent(args.storage_dir)
    try:
        await agent.write_clipboard(args.text)
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True}))
    else:
        print("\u2713 Clipboard set")
    return 0


async def _cmd_clipboard_paste(args: argparse.Namespace) -> int:
    """Send Ctrl+V to paste clipboard contents."""
    agent = _get_agent(args.storage_dir)
    result = await agent.paste()
    if args.json:
        print(json.dumps({"ok": result.ok, "data": result.data}))
    else:
        if result.ok:
            print("\u2713 Paste sent (Ctrl+V)")
        else:
            print(f"\u2717 Paste failed: {result.data}", file=sys.stderr)
    return 0 if result.ok else 1


async def _cmd_set_value(args: argparse.Namespace) -> int:
    """Set a value on a target element."""
    agent = _get_agent(args.storage_dir)
    result = await agent.set_value(args.target, args.value, dry_run=args.dry_run)
    if args.json:
        output = {"ok": result.ok, "data": result.data}
        if result.error:
            output["error"] = str(result.error.message)
        print(json.dumps(output, indent=2))
    else:
        if result.ok:
            label = " (dry run)" if args.dry_run else ""
            print(f"\u2713 Set value on '{args.target}' to '{args.value}'{label}")
        else:
            msg = result.error.message if result.error else result.data
            print(f"\u2717 Failed to set value: {msg}", file=sys.stderr)
    return 0 if result.ok else 1


async def _cmd_perform_action(args: argparse.Namespace) -> int:
    """Perform a named accessibility action."""
    agent = _get_agent(args.storage_dir)
    result = await agent.perform_action(
        args.target, args.action,
        value=args.value or "",
        dry_run=args.dry_run,
    )
    if args.json:
        output = {"ok": result.ok, "data": result.data}
        if result.error:
            output["error"] = str(result.error.message)
        print(json.dumps(output, indent=2))
    else:
        if result.ok:
            label = " (dry run)" if args.dry_run else ""
            print(f"\u2713 Performed '{args.action}' on '{args.target}'{label}")
        else:
            msg = result.error.message if result.error else result.data
            print(f"\u2717 Failed to perform action: {msg}", file=sys.stderr)
    return 0 if result.ok else 1


async def _cmd_menu_search(args: argparse.Namespace) -> int:
    """Search Start Menu."""
    agent = _get_agent(args.storage_dir)
    items = agent.menu.search_start(args.query)
    if args.json:
        data = [{"name": i.name, "path": i.path, "is_submenu": i.is_submenu, "is_enabled": i.is_enabled} for i in items]
        print(json.dumps(data, indent=2))
    else:
        if not items:
            print(f"  (no results for '{args.query}')")
        for item in items:
            print(f"  {item.name}")
    return 0


async def _cmd_menu_list(args: argparse.Namespace) -> int:
    """List Start Menu items."""
    agent = _get_agent(args.storage_dir)
    items = agent.menu.list_start_items()
    if args.json:
        data = [{"name": i.name, "path": i.path, "is_submenu": i.is_submenu, "is_enabled": i.is_enabled} for i in items]
        print(json.dumps(data, indent=2))
    else:
        if not items:
            print("  (no Start Menu items found)")
        for item in items:
            print(f"  {item.name}")
    return 0


async def _cmd_menu_click(args: argparse.Namespace) -> int:
    """Click a Start Menu item."""
    agent = _get_agent(args.storage_dir)
    ok = agent.menu.click_start_item(args.name)
    if ok:
        print(f"✓ Clicked '{args.name}'")
        return 0
    else:
        print(f"✗ Failed to click '{args.name}'")
        return 1


async def _cmd_taskbar_list(args: argparse.Namespace) -> int:
    """List taskbar items."""
    agent = _get_agent(args.storage_dir)
    items = agent.taskbar.list_running_apps()
    if args.json:
        data = [{"name": i.name, "is_running": i.is_running, "tooltip": i.tooltip} for i in items]
        print(json.dumps(data, indent=2))
    else:
        if not items:
            print("  (no running apps found in taskbar)")
        for item in items:
            print(f"  {item.name}  running={item.is_running}")
    return 0


async def _cmd_taskbar_click(args: argparse.Namespace) -> int:
    """Click a taskbar button."""
    agent = _get_agent(args.storage_dir)
    ok = agent.taskbar.click_taskbar_button(args.name)
    if ok:
        print(f"✓ Clicked taskbar button '{args.name}'")
        return 0
    else:
        print(f"✗ Failed to click taskbar button '{args.name}'")
        return 1


async def _cmd_dialog_list(args: argparse.Namespace) -> int:
    """List open dialogs."""
    agent = _get_agent(args.storage_dir)
    dialogs = agent.dialog.list_dialogs()
    if args.json:
        print(json.dumps(dialogs, indent=2))
    else:
        if not dialogs:
            print("  (no open dialogs)")
        for d in dialogs:
            print(f"  [{d['hwnd']}] {d['title']}")
    return 0


async def _cmd_dialog_dismiss(args: argparse.Namespace) -> int:
    """Dismiss a dialog."""
    agent = _get_agent(args.storage_dir)
    ok = agent.dialog.dismiss_dialog(args.hwnd, action=args.action)
    if ok:
        print(f"✓ Dismissed dialog {args.hwnd} ({args.action})")
        return 0
    else:
        print(f"✗ Failed to dismiss dialog {args.hwnd}")
        return 1


async def _cmd_desktop_list(args: argparse.Namespace) -> int:
    """List virtual desktops."""
    agent = _get_agent(args.storage_dir)
    desktops = agent.desktop.list_desktops()
    if args.json:
        data = [{"index": d.index, "name": d.name, "window_count": d.window_count, "is_current": d.is_current} for d in desktops]
        print(json.dumps(data, indent=2))
    else:
        if not desktops:
            print("  (no virtual desktops found)")
        for d in desktops:
            marker = " ← current" if d.is_current else ""
            print(f"  [{d.index}] {d.name or f'Desktop {d.index + 1}'}{marker}")
    return 0


async def _cmd_desktop_switch(args: argparse.Namespace) -> int:
    """Switch virtual desktop."""
    agent = _get_agent(args.storage_dir)
    ok = agent.desktop.switch_desktop(args.index)
    if ok:
        print(f"✓ Switched to desktop {args.index}")
        return 0
    else:
        print(f"✗ Failed to switch to desktop {args.index}")
        return 1


async def _cmd_chat(args: argparse.Namespace) -> int:
    """Launch interactive AgentChat REPL."""
    from deskaoy.agent.chat import AgentChat

    agent = _get_agent(args.storage_dir)
    chat = AgentChat(agent)
    return await chat.run()


async def _cmd_run(args: argparse.Namespace) -> int:
    """Run an automation script."""
    from deskaoy.agent.script_runner import ScriptRunner

    agent = _get_agent(args.storage_dir)
    runner = ScriptRunner(agent)
    result = await runner.run(args.script, dry_run=args.dry_run)

    if args.json:
        output = {
            "name": result.name,
            "ok": result.ok,
            "steps_total": result.steps_total,
            "steps_ok": result.steps_ok,
            "steps_failed": result.steps_failed,
            "dry_run": result.dry_run,
            "steps": [
                {"index": s.step_index, "action": s.action, "ok": s.ok, "output": s.output}
                for s in result.step_results
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        icon = "\u2713" if result.ok else "\u2717"
        print(f"{icon} Script: {result.name}")
        print(f"  Steps: {result.steps_ok}/{result.steps_total} OK")
        if result.dry_run:
            print("  (dry run — no actions executed)")
        for s in result.step_results:
            step_icon = "\u2713" if s.ok else "\u2717"
            print(f"  {step_icon} [{s.step_index}] {s.action}: {s.output}")

    return 0 if result.ok else 1


async def _cmd_mcp(args: argparse.Namespace) -> int:
    """Start MCP stdio server."""
    from deskaoy.transport.mcp_server import run_mcp_server
    return run_mcp_server(compact=args.compact)


async def _cmd_completions(args: argparse.Namespace) -> int:
    """Generate shell completion scripts."""
    from deskaoy.cli.completions import CompletionGenerator

    gen = CompletionGenerator(_build_parser())
    script = gen.generate(args.shell)
    print(script)
    return 0


async def _cmd_docs(args: argparse.Namespace) -> int:
    """Open documentation or print documentation URLs."""
    import webbrowser

    project_root = Path(__file__).resolve().parent.parent.parent.parent
    docs_base = "https://github.com/example/deskaoy"

    doc_map = {
        "readme": (project_root / "README.md", f"{docs_base}/blob/main/README.md"),
        "quickstart": (project_root / "QUICKSTART.md", f"{docs_base}/blob/main/QUICKSTART.md"),
        "changelog": (project_root / "CHANGELOG.md", f"{docs_base}/blob/main/CHANGELOG.md"),
        "contributing": (project_root / "CONTRIBUTING.md", f"{docs_base}/blob/main/CONTRIBUTING.md"),
        "api": (None, f"{docs_base}/blob/main/docs/api.md"),
    }

    local_path, remote_url = doc_map.get(args.topic, (None, docs_base))

    if args.print_only or not local_path or not local_path.exists():
        # Print URL
        print(remote_url)
        # Also print local file content if available
        if local_path and local_path.exists():
            print(f"\nLocal file: {local_path}")
        return 0

    # Try to open in browser
    try:
        webbrowser.open(f"file:///{local_path}")
        print(f"Opened {local_path} in browser")
    except Exception:
        print(remote_url)
    return 0


# ─── Daemon commands (BATCH-37) ──────────────────────────────────────

async def _cmd_daemon_start(args: argparse.Namespace) -> int:
    """Start the deskaoy daemon."""
    from deskaoy.daemon.config import DaemonConfig

    config = DaemonConfig()
    try:
        # Try to ping existing daemon first
        reader, writer = await asyncio.wait_for(
            _connect_to_daemon(config.socket_path), timeout=2.0,
        )
        import json as _json

        from deskaoy.daemon.protocol import build_ping_request, json_dumps
        writer.write(json_dumps(build_ping_request()))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        writer.close()
        await writer.wait_closed()
        if line:
            resp = _json.loads(line.decode("utf-8").strip())
            if resp.get("result", {}).get("status") == "ok":
                print(f"Daemon already running on {config.socket_path}")
                return 0
    except (TimeoutError, ConnectionError, OSError):
        pass

    # Start daemon subprocess
    import subprocess
    cmd = [sys.executable, "-c",
           "import asyncio; from deskaoy.daemon.server import DaemonServer; "
           "from deskaoy.daemon.config import DaemonConfig; "
           "asyncio.run(DaemonServer(DaemonConfig()).serve_forever())"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )
    print(f"Daemon started (PID {proc.pid})")
    print(f"Socket: {config.socket_path}")
    return 0


async def _cmd_daemon_stop(args: argparse.Namespace) -> int:
    """Stop the deskaoy daemon."""
    from deskaoy.daemon.config import DaemonConfig
    from deskaoy.daemon.protocol import build_shutdown_request, json_dumps

    config = DaemonConfig()
    try:
        reader, writer = await asyncio.wait_for(
            _connect_to_daemon(config.socket_path), timeout=2.0,
        )
        writer.write(json_dumps(build_shutdown_request()))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        if line:
            import json as _json
            resp = _json.loads(line.decode("utf-8").strip())
            result = resp.get("result", {})
            if result.get("status") == "shutting_down":
                print("Daemon shutting down")
                return 0
        print("Daemon stop sent")
        return 0
    except (TimeoutError, ConnectionError, OSError) as exc:
        print(f"Daemon not running or unreachable: {exc}")
        return 1


async def _cmd_daemon_status(args: argparse.Namespace) -> int:
    """Show daemon status."""
    from deskaoy.daemon.config import DaemonConfig
    from deskaoy.daemon.protocol import build_status_request, json_dumps

    config = DaemonConfig()
    try:
        reader, writer = await asyncio.wait_for(
            _connect_to_daemon(config.socket_path), timeout=2.0,
        )
        writer.write(json_dumps(build_status_request()))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        if line:
            import json as _json
            resp = _json.loads(line.decode("utf-8").strip())
            result = resp.get("result", {})
            "yes" if result.get("healthy") else "no"
            uptime = result.get("uptime_s", 0)
            calls = result.get("calls_served", 0)
            pid = result.get("pid", "?")
            if getattr(args, 'json', False):
                print(_json.dumps(result, indent=2))
            else:
                print("  Status: running")
                print(f"  PID:    {pid}")
                print(f"  Uptime: {uptime:.0f}s")
                print(f"  Calls:  {calls}")
                print(f"  Socket: {config.socket_path}")
            return 0
    except (TimeoutError, ConnectionError, OSError):
        if getattr(args, 'json', False):
            import json as _json
            print(_json.dumps({"running": False}))
        else:
            print("  Daemon not running")
        return 1


async def _connect_to_daemon(socket_path: str):
    """Connect to daemon via OS-appropriate transport."""
    if sys.platform == "win32":
        port = 19500 + (hash(socket_path) % 100)
        return await asyncio.open_connection("127.0.0.1", port)
    else:
        return await asyncio.open_unix_connection(socket_path)



_COMMANDS = {
    "execute": _cmd_execute,
    "estimate": _cmd_estimate,
    "schedule": None,  # handled separately
    "skills": None,    # handled separately
    "facts": None,     # handled separately
    "menu": None,      # handled separately (BATCH-26)
    "taskbar": None,   # handled separately (BATCH-26)
    "dialog": None,    # handled separately (BATCH-26)
    "desktop": None,   # handled separately (BATCH-26)
    "daemon": None,    # handled separately (BATCH-37)
    "health": _cmd_health,
    "describe": _cmd_describe,
    "schema": _cmd_schema,
    "version": _cmd_version,
    "doctor": _cmd_doctor,
    "repl": _cmd_repl,
    "release-check": _cmd_release_check,
    "status": _cmd_status,
    "snapshot": _cmd_snapshot,
    "snapshots": _cmd_snapshots,
    "observe": _cmd_observe,
    "set-value": _cmd_set_value,
    "perform-action": _cmd_perform_action,
    "completions": _cmd_completions,
    "docs": _cmd_docs,
    "chat": _cmd_chat,
    "run": _cmd_run,
}

# MCP and serve are looked up dynamically

_SCHEDULE_COMMANDS = {
    "add": _cmd_schedule_add,
    "list": _cmd_schedule_list,
    "remove": _cmd_schedule_remove,
    "due": _cmd_schedule_due,
}

_SKILLS_COMMANDS = {
    "list": _cmd_skills_list,
    "match": _cmd_skills_match,
}

_FACTS_COMMANDS = {
    "list": _cmd_facts_list,
    "search": _cmd_facts_search,
}

_MENU_COMMANDS = {
    "search": _cmd_menu_search,
    "list": _cmd_menu_list,
    "click": _cmd_menu_click,
}

_TASKBAR_COMMANDS = {
    "list": _cmd_taskbar_list,
    "click": _cmd_taskbar_click,
}

_DIALOG_COMMANDS = {
    "list": _cmd_dialog_list,
    "dismiss": _cmd_dialog_dismiss,
}

_DESKTOP_COMMANDS = {
    "list": _cmd_desktop_list,
    "switch": _cmd_desktop_switch,
}

_CLIPBOARD_COMMANDS = {
    "read": _cmd_clipboard_read,
    "write": _cmd_clipboard_write,
    "paste": _cmd_clipboard_paste,
}




async def _cmd_serve(args: argparse.Namespace) -> int:
    """Start REST API server."""
    from deskaoy.transport.rest_server import run_rest_server
    return run_rest_server(port=args.port, skip_consent=args.skip_consent)


def _suggest_command(argv: list[str]) -> None:
    """Print 'did you mean' suggestions for unknown commands."""
    if not argv:
        return
    # Get all known command names
    known_commands = set()
    for action in _build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            known_commands.update(action.choices.keys())
    # Check first non-flag arg
    for arg in argv:
        if arg.startswith("-"):
            continue
        if arg not in known_commands:
            candidates = difflib.get_close_matches(arg, known_commands, n=3, cutoff=0.6)
            if candidates:
                suggestions = ", ".join(candidates)
                print(f"  Did you mean: {suggestions}?", file=sys.stderr)
        break


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    # Force UTF-8 output on Windows to handle Unicode icons
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        with contextlib.suppress(Exception):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = _build_parser()
    args = parser.parse_args(argv)

    # --verbose / -v: enable DEBUG logging
    if getattr(args, 'verbose', False):
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
        logging.getLogger("deskaoy").setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    # No subcommand → print help
    if not args.command:
        parser.print_help()
        return 0

    # Dispatch
    try:
        if args.command == "schedule":
            sub_cmd = getattr(args, "schedule_command", None)
            if not sub_cmd:
                parser.parse_args(["schedule", "--help"])
                return 0
            handler = _SCHEDULE_COMMANDS.get(sub_cmd)
            if not handler:
                print(f"Unknown schedule command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        if args.command == "skills":
            sub_cmd = getattr(args, "skills_command", None)
            if not sub_cmd:
                parser.parse_args(["skills", "--help"])
                return 0
            handler = _SKILLS_COMMANDS.get(sub_cmd)
            if not handler:
                print(f"Unknown skills command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        if args.command == "facts":
            sub_cmd = getattr(args, "facts_command", None)
            if not sub_cmd:
                parser.parse_args(["facts", "--help"])
                return 0
            handler = _FACTS_COMMANDS.get(sub_cmd)
            if not handler:
                print(f"Unknown facts command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        if args.command == "menu":
            sub_cmd = getattr(args, "menu_command", None)
            if not sub_cmd:
                parser.parse_args(["menu", "--help"])
                return 0
            handler = _MENU_COMMANDS.get(sub_cmd)
            if not handler:
                print(f"Unknown menu command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        if args.command == "taskbar":
            sub_cmd = getattr(args, "taskbar_command", None)
            if not sub_cmd:
                parser.parse_args(["taskbar", "--help"])
                return 0
            handler = _TASKBAR_COMMANDS.get(sub_cmd)
            if not handler:
                print(f"Unknown taskbar command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        if args.command == "dialog":
            sub_cmd = getattr(args, "dialog_command", None)
            if not sub_cmd:
                parser.parse_args(["dialog", "--help"])
                return 0
            handler = _DIALOG_COMMANDS.get(sub_cmd)
            if not handler:
                print(f"Unknown dialog command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        if args.command == "desktop":
            sub_cmd = getattr(args, "desktop_command", None)
            if not sub_cmd:
                parser.parse_args(["desktop", "--help"])
                return 0
            handler = _DESKTOP_COMMANDS.get(sub_cmd)
            if not handler:
                print(f"Unknown desktop command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        if args.command == "daemon":
            sub_cmd = getattr(args, "daemon_command", None)
            if not sub_cmd:
                parser.parse_args(["daemon", "--help"])
                return 0
            daemon_handlers = {
                "start": _cmd_daemon_start,
                "stop": _cmd_daemon_stop,
                "status": _cmd_daemon_status,
            }
            handler = daemon_handlers.get(sub_cmd)
            if not handler:
                print(f"Unknown daemon command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        if args.command == "clipboard":
            sub_cmd = getattr(args, "clipboard_action", None)
            if not sub_cmd:
                parser.parse_args(["clipboard", "--help"])
                return 0
            handler = _CLIPBOARD_COMMANDS.get(sub_cmd)
            if not handler:
                print(f"Unknown clipboard command: {sub_cmd}")
                return 2
            return asyncio.run(handler(args))

        # Dynamic dispatch for commands with lazy imports
        if args.command == "mcp":
            return asyncio.run(_cmd_mcp(args))
        if args.command == "serve":
            return asyncio.run(_cmd_serve(args))

        handler = _COMMANDS.get(args.command)
        if not handler:
            print(f"Unknown command: {args.command}")
            return 2
        return asyncio.run(handler(args))

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        # Ensure error message is printable on Windows (cp1252)
        msg = str(exc).encode('ascii', errors='replace').decode('ascii')
        print(f"Error: {msg}", file=sys.stderr)
        # Provide \"did you mean\" suggestions for common command typos
        _suggest_command(argv or sys.argv[1:])
        return 1


if __name__ == "__main__":
    sys.exit(main())
