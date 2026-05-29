BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-38
Blueprint Version:        1.1
Cycle Mode:               STANDARD
Lead Programmer:          Lead (Session 260520-apt-topaz)
Date Issued:              2026-05-21
Review SLA:               30 min
Execution SLA per Task:   90 min
Partial Sign-Off SLA:     15 min
Task Sequencing:          Mixed (TASK-02 depends on TASK-01; TASK-03 depends on TASK-02)

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────

Add DesktopAgent.with_browser() factory method that creates a UnifiedSurface
with lazy browser initialization. When the user calls with_browser(), DesktopAgent
auto-detects the platform adapter (Windows/Linux), optionally attaches SuperBrowser
(via lazy import), and routes desktop vs. browser actions through UnifiedSurface.
Browser session starts on first browser-routed action, not at construction time.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────

What the code MUST do:
  - DesktopAgent.with_browser() returns a fully configured DesktopAgent
    with both desktop and browser surfaces
  - Browser session (Patchright) starts lazily on first browser action,
    not at DesktopAgent construction time
  - UnifiedSurface._ensure_browser() creates BrowserSession, PageHandle,
    MultimodalController, and BrowserAdapter on demand
  - async context manager (__aenter__/__aexit__) cleans up browser session
  - Works when super_browser is not installed (graceful fallback to desktop-only)
  - Existing DesktopAgent(surface=...) constructor continues to work unchanged

What the code MUST NOT do:
  - Import super_browser at module level (must be lazy, inside method bodies)
  - Start Patchright at DesktopAgent construction time (must be deferred)
  - Break any of the existing 3,471 tests
  - Modify SurfaceAdapter protocol, MultimodalController, or BrowserAdapter
  - Add browser-specific code to agent_core (all browser code stays in super_browser)

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: No import of any super_browser module at agent_core module level.
         All super_browser imports MUST be inside function/method bodies.
         Violation is detectable by: `python -c "import agent_core"` succeeds
         when super_browser is not installed.

  HB-02: Browser session MUST NOT start until the first browser-routed action.
         Violation is detectable by: DesktopAgent.with_browser() construction
         completes in <100ms (no Patchright process launched).

  HB-03: Existing DesktopAgent(surface=adapter) constructor MUST NOT change
         its signature or behavior. All existing 3,471 tests MUST pass unchanged.
         Violation is detectable by: running existing test suite produces 0 failures.

  HB-04: DesktopAgent.with_browser() MUST NOT raise when super_browser is not
         installed. It MUST return a desktop-only DesktopAgent and log a warning.
         Violation is detectable by: uninstalling super_browser and calling
         with_browser() returns a working desktop agent with no browser surface.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

New factory method signature on DesktopAgent:

    @classmethod
    def with_browser(
        cls,
        *,
        desktop_adapter: Optional[SurfaceAdapter] = None,
        browser_config: Optional[dict] = None,
        llm: Any = None,
    ) -> DesktopAgent

Existing types used (no changes):
    - SurfaceAdapter (agent_core.cascade.protocol.SurfaceAdapter)
    - UnifiedSurface (agent_core.cascade.unified_surface.UnifiedSurface)
    - BrowserAdapter (super_browser.adapters.browser.BrowserAdapter)
    - BrowserSession (super_browser.browser.session.BrowserSession)
    - SessionConfig (super_browser.browser.config.SessionConfig)
    - MultimodalController (super_browser.interaction.controller.MultimodalController)
    - Environment.create_adapter() (agent_core.adapters.environment.Environment)

New internal attributes on UnifiedSurface:
    _browser_session: Optional[BrowserSession]  # Stashed for lazy init
    _browser_initialized: bool  # Tracks whether lazy init has happened

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────

  AUTH-01: DesktopAgent.with_browser() is a classmethod factory. It does not
           call __init__ directly — it constructs objects and passes them to
           the existing __init__. No new constructor paths are created.

  AUTH-02: UnifiedSurface._ensure_browser() is a private async method. It is
           the ONLY code path that starts a browser session. It is called only
           when UnifiedSurface routing determines the target is a browser action
           (navigate, URL hint, browser window focused).

  AUTH-03: Browser session lifecycle (start/stop) is owned by the code that
           created it. If DesktopAgent created it (via with_browser), DesktopAgent
           destroys it (via __aexit__). If the user created it manually, the user
           is responsible.

  AUTH-04: The platform auto-detection in with_browser() delegates to
           Environment.create_adapter(), which is the existing authority for
           platform adapter selection. No new platform detection code.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────

  Prior Batches:
    BATCH-05 (SurfaceAdapter + UnifiedSurface) — REQUIRED, done
    BATCH-32 (UnifiedSurface browser routing) — REQUIRED, done
    BATCH-37 (Daemon architecture) — not required for this Batch

  External:
    super_browser package — OPTIONAL dependency, lazily imported
    patchright — OPTIONAL dependency, comes via super_browser[browser]

  Unresolved:
    None. All dependencies are already in the codebase.

───────────────────────────────────────────────────────────
STATE.md STATUS
───────────────────────────────────────────────────────────

  State file exists: [ ] NO — first Batch under v5.3
  STATE.md path:     [project root]/STATE.md
  Last verified:     BATCH-37 close (not populated — template only)
  Status:            Placeholder. Will be populated at BATCH-38 close.

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────

  Baseline at Blueprint issuance:  3,471 existing tests
  Expected delta (all Tasks):      +21 new tests
  Expected total at Batch close:   3,492

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────

  ruff check src/agent_core/desktop_agent.py src/agent_core/cascade/unified_surface.py
  mypy src/agent_core/desktop_agent.py src/agent_core/cascade/unified_surface.py

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-38/TASK-01 — DesktopAgent.with_browser() Factory Method
────────────────────────────────────────────────────────────────────────
  Description:
    Add a @classmethod factory method to DesktopAgent that creates a
    DesktopAgent with both desktop and browser surfaces. Auto-detects
    the desktop adapter via Environment.create_adapter(). Attempts to
    import super_browser (lazy, inside method body). If available, creates
    a BrowserSession and stashes it on UnifiedSurface for lazy init.
    If not available, falls back to desktop-only with a warning log.

    Also add __aenter__/__aexit__ to DesktopAgent for async context
    manager support. __aexit__ stops the browser session if one was
    started.

  Files in scope:
    - src/agent_core/desktop_agent.py (add with_browser classmethod, __aenter__, __aexit__)

  Depends on: None

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-38-01-01 | unit | with_browser() returns a DesktopAgent instance | Returns None or wrong type | Remove the @classmethod decorator | isinstance(result, DesktopAgent) is True |
    | TEST-38-01-02 | unit | with_browser() sets up UnifiedSurface when super_browser available | surface is plain SurfaceAdapter, not Unified | Skip the UnifiedSurface construction | isinstance(result._surface, UnifiedSurface) when super_browser importable |
    | TEST-38-01-03 | unit | with_browser() falls back to desktop-only when super_browser not installed | Raises ImportError on missing super_browser | Remove the try/except ImportError guard | result._surface is not UnifiedSurface and agent functions correctly |
    | TEST-38-01-04 | unit | with_browser() stashes browser_session on UnifiedSurface | No _browser_session attribute set | Remove the session stashing line | hasattr(result._surface, '_browser_session') and value is not None (when super_browser available) |
    | TEST-38-01-05 | unit | with_browser() accepts custom desktop_adapter | Ignores the parameter, uses auto-detect instead | Remove the if desktop_adapter is None branch | result._surface._desktop is the provided adapter |
    | TEST-38-01-06 | unit | with_browser() accepts browser_config dict | Config is ignored | Remove the config = browser_config or {} line | SessionConfig constructed with provided headless/viewport values |
    | TEST-38-01-07 | unit | DesktopAgent.__aenter__ returns self | Returns something else | Return a different object from __aenter__ | async with DesktopAgent() as agent: assert agent is the original |
    | TEST-38-01-08 | unit | DesktopAgent.__aexit__ stops browser session | Browser session not cleaned up | Remove the __aexit__ browser cleanup branch | UnifiedSurface._browser_session.stop() was called (mock-verified) |
    | TEST-38-01-09 | unit | No super_browser import at agent_core module level | Module-level import makes agent_core importable only with super_browser installed | Add `from super_browser import X` at top of desktop_agent.py | `import agent_core` succeeds when super_browser is not installed |
    | TEST-38-01-10 | unit | with_browser() passes llm parameter to DesktopAgent | llm param is silently dropped | Remove the `llm=llm` argument from `cls(...)` call | `result._llm is the provided llm client |

  Acceptance Criteria:
    AC-01-01: DesktopAgent.with_browser() is a @classmethod that returns DesktopAgent
    AC-01-02: No super_browser imports at module level in agent_core (HB-01)
    AC-01-03: Factory gracefully degrades to desktop-only when super_browser absent (HB-04)
    AC-01-04: DesktopAgent supports async context manager protocol
    AC-01-05: with_browser() passes llm parameter through to DesktopAgent

  AC-to-Test Traceability:
    AC-01-01 → TEST-38-01-01
    AC-01-02 → TEST-38-01-09
    AC-01-03 → TEST-38-01-03
    AC-01-04 → TEST-38-01-07, TEST-38-01-08
    AC-01-05 → TEST-38-01-10


TASK-02: BATCH-38/TASK-02 — UnifiedSurface Lazy Browser Initialization
────────────────────────────────────────────────────────────────────────
  Description:
    Add _ensure_browser() async method to UnifiedSurface. When called,
    checks if browser adapter exists. If not, starts the stashed
    BrowserSession, creates a PageHandle, MultimodalController, and
    BrowserAdapter, and stores it as self._browser.

    Wire navigate() to call _ensure_browser() before delegating.
    Non-browser methods (click via desktop, screenshot, snapshot, keyboard)
    remain unchanged — they go through _desktop directly.

  Files in scope:
    - src/agent_core/cascade/unified_surface.py (add _ensure_browser, wire browser methods)

  Depends on: TASK-01 (UnifiedSurface needs _browser_session attribute)

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-38-02-01 | unit | _ensure_browser() creates BrowserAdapter on first call | Returns None or raises | Remove the BrowserAdapter construction | After call, isinstance(surface._browser, BrowserAdapter) |
    | TEST-38-02-02 | unit | _ensure_browser() is idempotent — no second init | Creates new session on every call | Remove the if self._browser is not None guard | Session.start() called exactly once across two _ensure_browser() calls |
    | TEST-38-02-03 | unit | _ensure_browser() raises RuntimeError when no session configured | Silently returns None or wrong type | Remove the RuntimeError guard | pytest.raises(RuntimeError) matches "No browser session configured" |
    | TEST-38-02-04 | unit | navigate() triggers lazy browser init | navigate() fails without calling _ensure_browser | Remove the _ensure_browser() call from navigate() | After navigate(), surface._browser is not None and _browser_initialized is True |
    | TEST-38-02-05 | unit | Desktop click does NOT trigger browser init | Every action starts browser | Route click through _ensure_browser | After click(), surface._browser is None (browser never started) |
    | TEST-38-02-06 | unit | Browser session start time is deferred past construction | Patchright launches at construction | Move session.start() into __init__ | with_browser() completes in <200ms (mock Patchright, verify start() not called) |
    | TEST-38-02-07 | unit | _ensure_browser() handles session start failure gracefully | Silently sets browser to None, next action crashes | Remove try/except around session.start() | action_result(ok=False) with error containing 'Browser session failed to start' |

  Acceptance Criteria:
    AC-02-01: _ensure_browser() lazily creates BrowserAdapter on demand
    AC-02-02: Browser session starts only on first browser-routed action (HB-02)
    AC-02-03: Desktop actions (click, fill, key_press, screenshot) never trigger browser init
    AC-02-04: _ensure_browser() is idempotent — no double initialization
    AC-02-05: _ensure_browser() handles session startup failure gracefully

  AC-to-Test Traceability:
    AC-02-01 → TEST-38-02-01
    AC-02-02 → TEST-38-02-04, TEST-38-02-06
    AC-02-03 → TEST-38-02-05
    AC-02-04 → TEST-38-02-02
    AC-02-05 → TEST-38-02-07


TASK-03: BATCH-38/TASK-03 — Integration Test — Full Lifecycle
────────────────────────────────────────────────────────────────
  Description:
    Write integration tests that exercise the complete lifecycle:
    DesktopAgent.with_browser() -> desktop action -> browser action -> stop.
    Tests use mocks for Patchright (no real browser needed) but verify
    the wiring is correct end-to-end.

    Also verify that existing DesktopAgent(surface=adapter) path still
    works identically — regression guard.

  Files in scope:
    - tests/test_browser_integration/test_with_browser_lifecycle.py (new file)
    - tests/test_browser_integration/__init__.py (new file)

  Depends on: TASK-01, TASK-02

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-38-03-01 | integration | Full lifecycle: with_browser() -> desktop click -> browser navigate -> stop | Any step fails silently | Remove any wiring step | All steps complete, browser session started and stopped |
    | TEST-38-03-02 | integration | Existing DesktopAgent(surface=WindowsAdapter(mock)) still works | Constructor signature changed | Revert to old constructor | DesktopAgent(surface=mock_adapter) creates agent, execute() routes to adapter |
    | TEST-38-03-03 | integration | with_browser() + browser navigate routes to BrowserAdapter | Routes to desktop adapter instead | Remove _route() URL detection | navigate() delegates to BrowserAdapter.navigate, not desktop |
    | TEST-38-03-04 | integration | with_browser() desktop click routes to desktop adapter | Routes to browser instead | Remove _route() default-to-desktop logic | click() delegates to desktop adapter, browser not initialized |

  Acceptance Criteria:
    AC-03-01: Full lifecycle test passes end-to-end with mocked Patchright
    AC-03-02: Existing constructor regression test passes (HB-03)
    AC-03-03: Routing works correctly — browser actions go to browser, desktop to desktop
    AC-03-04: All existing 3,471 tests still pass (HB-03)

  AC-to-Test Traceability:
    AC-03-01 → TEST-38-03-01
    AC-03-02 → TEST-38-03-02
    AC-03-03 → TEST-38-03-03
    AC-03-04 → TEST-38-03-04

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  BAC-01: DesktopAgent.with_browser() is callable and returns a working DesktopAgent.
  BAC-02: No super_browser imports at agent_core module level (HB-01).
  BAC-03: Browser session starts lazily on first browser action, not at construction (HB-02).
  BAC-04: All existing 3,471 tests pass unchanged (HB-03).
  BAC-05: with_browser() degrades gracefully when super_browser not installed (HB-04).
  BAC-06: CHANGELOG.md updated with BATCH-38 entry.
  BAC-07: All documents archived under /docs/aiv/BATCH-38/.
  BAC-08: ruff check and mypy pass on all modified files.

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────

Reviewer Report ID:       REVIEW-BATCH-38-2026-05-21
Review Cycle:             1
Lead Decision:            [X] ACCEPT WITH MODIFICATIONS

Flags acted on:
  FLAG-01 (CHK-13: no test for llm passthrough) → Added TEST-38-01-10 and AC-01-05
  FLAG-02 (CHK-13: no test for session start failure) → Added TEST-38-02-07 and AC-02-05

Blueprint Version after response: 1.1
Lead Sign:                Lead (260520-apt-topaz) 2026-05-21 01:52 +03:00

Notes: Reviewer session unavailable. Review Report written by Lead
per AIV v5.3 §4.5 (Reviewer Fallback Procedure). Does not count as
a Review Cycle.

═══════════════════════════════════════════════════════════
