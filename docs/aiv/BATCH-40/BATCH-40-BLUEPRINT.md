BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-40
Blueprint Version:        1.0
Cycle Mode:               STANDARD
Lead Programmer:          Lead (Session 260520-apt-topaz)
Date Issued:              2026-05-21
Review SLA:               30 min
Execution SLA per Task:   90 min
Partial Sign-Off SLA:     15 min
Task Sequencing:          Mixed (TASK-02 depends on TASK-01; TASK-03 depends on TASK-01)

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────

Make `from super_browser import SuperBrowser` a clean standalone API with no
Desktop-Agent knowledge required. Update __init__.py to export the public API.
Add a `super-browser` CLI entry point with `serve` subcommand. Write standalone
usage docs (README for the super_browser package).

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────

What the code MUST do:
  - `from super_browser import SuperBrowser` works as the primary entry point
  - `from super_browser import SessionConfig, ActionResult, action_result` works
  - `__init__.py` exports: SuperBrowser, SuperBrowserConfig, SessionConfig,
    ActionResult, action_result, CompletionReason, __version__
  - `super-browser version` prints the version
  - `super-browser serve` starts a browser session and exposes an API
  - All existing 3,501 tests continue passing

What the code MUST NOT do:
  - Add any import of agent_core at super_browser.__init__ module level
    (super_browser depends on agent_core, but __init__ must not trigger heavy imports)
  - Break any existing import path (existing code still imports from submodules)
  - Modify the SuperBrowser facade class itself
  - Require DesktopAgent to be instantiated for SuperBrowser to work

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: All 3,501 existing tests MUST pass unchanged.
         Violation: any test that currently passes fails.

  HB-02: `from super_browser import SuperBrowser` MUST complete without
         importing DesktopAgent (no `from agent_core.desktop_agent import ...`
         at __init__.py level).
         Violation: `python -c "from super_browser import SuperBrowser"` triggers
         DesktopAgent import chain.

  HB-03: Existing import paths (e.g. `from super_browser.browser.session import
         BrowserSession`) MUST continue to work unchanged.
         Violation: any existing import from a submodule breaks.

  HB-04: CLI entry point `super-browser` MUST be defined in the super-browser
         pyproject.toml, not in the root desktop-agent pyproject.toml.
         Violation: CLI defined in root pyproject.toml.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

Modified: `src/super_browser/__init__.py`

    """Super Browser — Browser automation for AI agents."""
    from super_browser.agent.facade import SuperBrowser
    from super_browser.browser.config import SessionConfig
    from super_browser.results.types import (
        ActionResult, action_result, CompletionReason,
    )
    __version__ = "1.0.0"
    __all__ = [
        "SuperBrowser", "SessionConfig", "ActionResult",
        "action_result", "CompletionReason", "__version__",
    ]

New: `src/super_browser/cli.py`

    """super-browser CLI entry point."""
    # argparse-based CLI with: version, serve subcommands

Modified: `src/super_browser/pyproject.toml`
    [project.scripts]
    super-browser = "super_browser.cli:main"

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────

  AUTH-01: super_browser/__init__.py is the public API surface. Only types that
           are intended for end-users are exported here. Internal types stay in
           their submodules.

  AUTH-02: The CLI module (super_browser.cli) owns the `super-browser` command.
           It does not import from agent_core.cli.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────

  Prior Batches:
    BATCH-38 (with_browser factory) — not required
    BATCH-39 (package split) — REQUIRED, done

  External:
    argparse — stdlib (CLI)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────

  Baseline at Blueprint issuance:  3,501 tests
  Expected delta (all Tasks):      +8 new tests
  Expected total at Batch close:   3,509

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: Update super_browser/__init__.py public API exports
────────────────────────────────────────────────────────────
  Description:
    Update __init__.py to export the clean standalone API:
    SuperBrowser, SessionConfig, ActionResult, action_result,
    CompletionReason, __version__. Add __all__ for explicit
    public surface.

  Files in scope:
    - src/super_browser/__init__.py

  Depends on: None

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-40-01-01 | unit | from super_browser import SuperBrowser works | ImportError | Remove the import | SuperBrowser is a class |
    | TEST-40-01-02 | unit | from super_browser import SessionConfig works | ImportError | Remove the import | SessionConfig is a dataclass |
    | TEST-40-01-03 | unit | from super_browser import ActionResult works | ImportError | Remove the import | ActionResult is importable |
    | TEST-40-01-04 | unit | No DesktopAgent import at __init__ level | Heavy import chain triggered | Add from agent_core.desktop_agent import DesktopAgent to __init__ | import tracking shows no desktop_agent module loaded |
    | TEST-40-01-05 | unit | __version__ is "1.0.0" | Wrong version | Change version string | super_browser.__version__ == "1.0.0" |

  Acceptance Criteria:
    AC-01-01: All 5 public names importable from super_browser
    AC-01-02: No DesktopAgent import triggered at __init__ level (HB-02)

  AC-to-Test Traceability:
    AC-01-01 → TEST-40-01-01, TEST-40-01-02, TEST-40-01-03, TEST-40-01-05
    AC-01-02 → TEST-40-01-04


TASK-02: Add super-browser CLI entry point
───────────────────────────────────────────
  Description:
    Create src/super_browser/cli.py with argparse-based CLI.
    Subcommands: `version` (prints version), `serve` (starts browser session).
    Register `super-browser` script in super_browser/pyproject.toml.

  Files in scope:
    - src/super_browser/cli.py (new file)
    - src/super_browser/pyproject.toml (add [project.scripts])

  Depends on: TASK-01

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-40-02-01 | unit | CLI main() returns 0 for version subcommand | Returns non-zero | Remove version handler | subprocess exit code 0 |
    | TEST-40-02-02 | unit | CLI version prints "1.0.0" | Wrong version output | Hardcode wrong version | "1.0.0" in stdout |
    | TEST-40-02-03 | unit | CLI --help exits 0 | Raises exception | Remove argparse setup | subprocess exit code 0 |

  Acceptance Criteria:
    AC-02-01: `super-browser version` prints correct version
    AC-02-02: CLI entry point registered in super_browser/pyproject.toml (HB-04)

  AC-to-Test Traceability:
    AC-02-01 → TEST-40-02-01, TEST-40-02-02
    AC-02-02 → verified by pyproject.toml content check


TASK-03: Regression + existing import paths
────────────────────────────────────────────
  Description:
    Verify all existing import paths still work. Run regression tests.
    Verify existing tests pass unchanged.

  Files in scope:
    - No new files (validation only)

  Depends on: TASK-01

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-40-03-01 | integration | from super_browser.browser.session import BrowserSession works | ImportError | Change __init__.py to re-export everything | Module imports without error |
    | TEST-40-03-02 | integration | from super_browser.interaction.controller import MultimodalController works | ImportError | Break the module | Module imports without error |
    | TEST-40-03-03 | integration | All 3,501 tests pass | Test failures | Any change that breaks an import | pytest exit code 0 on critical subsets |

  Acceptance Criteria:
    AC-03-01: Existing submodule imports work unchanged (HB-03)
    AC-03-02: All existing tests pass (HB-01)

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  BAC-01: `from super_browser import SuperBrowser` is the clean standalone API.
  BAC-02: No DesktopAgent import at __init__ level (HB-02).
  BAC-03: `super-browser version` prints correct version.
  BAC-04: CLI defined in super_browser/pyproject.toml (HB-04).
  BAC-05: All 3,501 existing tests pass (HB-01).
  BAC-06: CHANGELOG.md updated with BATCH-40 entry.
  BAC-07: Documents archived under /docs/aiv/BATCH-40/.

═══════════════════════════════════════════════════════════
