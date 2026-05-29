# BATCH BLUEPRINT — BATCH-24

```
BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-24
Blueprint Version:        1.1
Cycle Mode:               STANDARD
Lead Programmer:          Craft Agent (Lead)
Date Issued:              2026-05-10
Review SLA:               30 min
Execution SLA per Task:   60 min
Partial Sign-Off SLA:     15 min
Task Sequencing:          MIXED (TASK-01 first, then TASK-02 + TASK-03 parallel, then TASK-04)

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────

Implement a Peekaboo-inspired Snapshot State System that persists UI element
snapshots with unique element IDs to disk, enabling reliable multi-command
automation workflows where `see → click → type → verify` chains resolve
elements by ID rather than by re-detection.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────

What the code MUST do:
  - Persist AXSnapshot objects to disk with unique snapshot IDs (UUID)
  - Assign stable element IDs to detected elements (E1, E2, T1, B1, etc.)
  - Store raw screenshot alongside snapshot JSON in a snapshot directory
  - Provide SnapshotStore API: create, get, find_elements, list, clean, clean_all
  - Integrate SnapshotStore into DesktopAgent facade so snapshots survive across commands
  - Add CLI `peekaboo see`-style workflow: snapshot → inspect → target by element ID
  - Support stale snapshot detection (window moved, resized, or closed)
  - Implement LRU eviction with configurable max_snapshots (default 50)
  - Add `desktop-agent snapshot` and `desktop-agent click --on E1 --snapshot <id>` commands

What the code MUST NOT do:
  - Modify the existing SurfaceAdapter ABC signature (add methods only via non-abstract defaults)
  - Change the health check 3-state model (already fixed in BATCH-23)
  - Break any of the existing 2,943 tests
  - Depend on any new external packages (stdlib only)
  - Create a daemon or background process (snapshots are request-scoped)

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────

  Lint command:  python -m pytest tests/ --tb=no -q --ignore=tests/integration --ignore=tests/test_agent/test_cua_live.py -x

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: The system MUST NOT store snapshots outside ~/.desktop-agent/snapshots/
         without an explicit override path parameter. No temp directories,
         no CWD-relative paths as default.

  HB-02: Element IDs MUST be deterministic for the same snapshot — re-loading
         a snapshot from disk MUST produce the same element ID for the same
         element. IDs are assigned by ordinal position in the AX tree traversal,
         not by random UUID.

  HB-03: Snapshot files MUST NOT contain credentials, API keys, or environment
         variables. The snapshot JSON is restricted to: elements, window metadata,
         capture timestamp, and snapshot ID.

  HB-04: No existing test may change from PASS to FAIL. The baseline of 2,943
         tests must remain green throughout all Tasks.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

Snapshot directory structure:
  ~/.desktop-agent/snapshots/<snapshot-id>/
    snapshot.json          — serialized snapshot metadata + elements
    raw.png                — raw screenshot (if captured)

snapshot.json schema:
  {
    "snapshot_id": "uuid-v4",
    "created_at": "ISO-8601",
    "application": "Notepad",
    "window_title": "Untitled - Notepad",
    "window_bounds": {"x": 100, "y": 100, "width": 800, "height": 600},
    "bundle_id": null,
    "pid": 12345,
    "platform": "windows",
    "elements": [
      {
        "element_id": "E1",
        "role": "window",
        "name": "Untitled - Notepad",
        "bounds": {"x": 100, "y": 100, "width": 800, "height": 600},
        "actionable": true,
        "value": null,
        "description": null
      }
    ]
  }

New module: src/agent_core/cascade/snapshot_store.py
  class SnapshotStore:
      SNAPSHOT_DIR: Path = Path.home() / ".desktop-agent" / "snapshots"
      MAX_SNAPSHOTS: int = 50

      async def create(elements, screenshot_bytes, metadata) -> str
      async def get(snapshot_id: str) -> SnapshotRecord | None
      async def find_elements(snapshot_id: str, query: str) -> list[UIElement]
      async def get_element(snapshot_id: str, element_id: str) -> UIElement | None
      async def list_snapshots() -> list[SnapshotInfo]
      async def is_stale(snapshot_id: str) -> StaleResult
      async def clean(snapshot_id: str) -> bool
      async def clean_all() -> int

New dataclass: src/agent_core/cascade/snapshot_types.py
  @dataclass
  class SnapshotRecord:
      snapshot_id: str
      created_at: str
      application: str | None
      window_title: str | None
      window_bounds: dict | None
      bundle_id: str | None
      pid: int | None
      platform: str
      elements: list[SnapshotElement]
      screenshot_path: Path | None

  @dataclass
  class SnapshotElement:
      element_id: str       # E1, E2, T1, B1, etc.
      role: str
      name: str | None
      bounds: dict | None
      actionable: bool
      value: str | None
      description: str | None

  @dataclass
  class SnapshotInfo:
      snapshot_id: str
      created_at: str
      application: str | None
      element_count: int
      has_screenshot: bool

  @dataclass
  class StaleResult:
      is_stale: bool
      reason: str    # "window_moved", "window_closed", "window_resized", ""

Element ID assignment logic:
  - Role prefixes: E (generic), T (text/edit), B (button), M (menu), C (checkbox), S (slider)
  - Sequential numbering within each prefix: E1, E2, T1, T2, B1, B2
  - Assignment order: depth-first AX tree traversal
  - Deterministic: same tree → same IDs

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────

  AR-01: Only SnapshotStore.create() may write snapshot files. No other code
         may create files under ~/.desktop-agent/snapshots/.

  AR-02: Element IDs are immutable once assigned. A loaded snapshot must not
         reassign IDs.

  AR-03: Stale snapshot detection uses window bounds + title comparison.
         A snapshot is stale if the captured window bounds differ from current
         by more than 10 pixels in any dimension, or the window title changed.

  AR-04: LRU eviction runs on every create(). When MAX_SNAPSHOTS is exceeded,
         the oldest snapshot (by created_at) is deleted along with its files.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────

  BATCH-01 through BATCH-23: COMPLETED
  Current version: v0.31.0
  Current test count: 2,943 passing
  This Batch depends on:
    - cascade/types.py (AXSnapshot, AXNode — from BATCH-05)
    - cascade/protocol.py (SurfaceAdapter.snapshot() — from BATCH-05)
    - adapters/windows.py (WindowsAdapter — from BATCH-16)
    - cli/main.py (CLI commands — from BATCH-05)
    - safety/health.py (health checks — from BATCH-23)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────

  Baseline at Blueprint issuance:  2,943 existing tests
  Expected delta (all Tasks):      +44 new tests
  Expected total at Batch close:   2,987

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-24/TASK-01 — Snapshot Data Types & Store Core
  Description:
    Create the snapshot_types.py module with SnapshotRecord, SnapshotElement,
    SnapshotInfo, and StaleResult dataclasses. Create the SnapshotStore class
    with create(), get(), list_snapshots(), clean(), clean_all() methods.
    Implement element ID assignment logic (role-based prefixes + sequential numbering).
    Implement LRU eviction. All operations use pathlib and json (stdlib only).

  Files in scope:
    - src/agent_core/cascade/snapshot_types.py   (NEW — data models)
    - src/agent_core/cascade/snapshot_store.py    (NEW — store implementation)
    - src/agent_core/cascade/__init__.py           (MODIFY — export new types)

  Depends on: None (foundational Task)

  Required Tests:
    | Test ID          | Type      | Behavior Verified                    | Failure Mode                    | Falsified By                     | Pass Criteria                              |
    |:-----------------|:----------|:-------------------------------------|:--------------------------------|:---------------------------------|:-------------------------------------------|
    | TEST-24-01-01    | unit      | SnapshotRecord construction          | Missing required fields         | Instantiate with partial data    | All fields populated, no TypeError         |
    | TEST-24-01-02    | unit      | SnapshotElement element_id format    | Wrong ID format                 | Check ID matches E\d+, T\d+ etc  | IDs match ^[ETBMCS]\d+$ regex              |
    | TEST-24-01-03    | unit      | Element ID assignment is deterministic| Same tree → different IDs       | Create IDs twice, compare        | IDs identical across two calls             |
    | TEST-24-01-04    | unit      | Role prefixes correct                | Button gets "T" prefix          | Create button element, check ID  | Button → B1, text → T1, generic → E1      |
    | TEST-24-01-05    | unit      | SnapshotStore.create() writes files  | Files not created on disk       | Call create, check path exists   | snapshot.json + raw.png exist              |
    | TEST-24-01-06    | unit      | SnapshotStore.get() loads correctly  | Returns None for valid snapshot | Create then get, check data      | Record matches what was created            |
    | TEST-24-01-07    | unit      | SnapshotStore.get() returns None     | Returns data for missing ID     | Get with random UUID             | Returns None                               |
    | TEST-24-01-08    | unit      | LRU eviction deletes oldest          | Oldest snapshot survives        | Create MAX+1, check oldest gone  | Oldest deleted, newest remains             |
    | TEST-24-01-09    | unit      | SnapshotStore.list_snapshots() works | Returns empty or wrong count    | Create 3, list, check count      | Returns 3 SnapshotInfo objects             |
    | TEST-24-01-10    | unit      | SnapshotStore.clean() removes files | Directory remains after clean   | Create then clean, check path    | Directory removed, returns True            |
    | TEST-24-01-11    | unit      | SnapshotStore.clean_all() count      | Wrong deletion count            | Create 5, clean_all, check count | Returns 5                                 |
    | TEST-24-01-12    | unit      | Snapshot JSON has no credentials     | API key leaked into JSON        | Inspect JSON keys for secret-like| No keys matching *key*, *token*, *secret* |
    | TEST-24-01-13    | unit      | MAX_SNAPSHOTS default is 50          | Wrong default                   | Check class constant             | MAX_SNAPSHOTS == 50                        |

  Acceptance Criteria:
    AC-01-01: All 13 tests PASS
    AC-01-02: SnapshotStore uses only stdlib (pathlib, json, uuid, time)
    AC-01-03: Element IDs are deterministic for the same AX tree
    AC-01-04: No files written outside ~/.desktop-agent/snapshots/

───────────────────────────────────────────────────────────

TASK-02: BATCH-24/TASK-02 — Stale Snapshot Detection
  Description:
    Implement is_stale() in SnapshotStore that compares stored window metadata
    against current window state. Detect: window moved (>10px), window resized
    (>10px), window closed (no matching window), window title changed.
    Integrate with WindowsAdapter to provide current window bounds on demand.

  Files in scope:
    - src/agent_core/cascade/snapshot_store.py    (MODIFY — add is_stale)
    - src/agent_core/adapters/windows.py           (MODIFY — add get_window_metadata helper)

  Depends on: TASK-01

  Required Tests:
    | Test ID          | Type      | Behavior Verified                    | Failure Mode                    | Falsified By                     | Pass Criteria                              |
    |:-----------------|:----------|:-------------------------------------|:--------------------------------|:---------------------------------|:-------------------------------------------|
    | TEST-24-02-01    | unit      | Fresh snapshot not stale              | is_stale returns True           | Create then immediately check    | is_stale == False, reason == ""            |
    | TEST-24-02-02    | unit      | Moved window detected as stale       | is_stale returns False          | Move bounds by 50px, check      | is_stale == True, reason contains "moved"  |
    | TEST-24-02-03    | unit      | Small jitter (<10px) not stale        | is_stale returns True           | Move by 5px, check              | is_stale == False                          |
    | TEST-24-02-04    | unit      | Resized window detected as stale      | is_stale returns False          | Change width by 50px            | is_stale == True, reason contains "resized"|
    | TEST-24-02-05    | unit      | Title change detected as stale        | is_stale returns False          | Change title, check             | is_stale == True, reason contains "title"  |
    | TEST-24-02-06    | unit      | Closed window detected as stale       | is_stale returns False          | Remove window, check            | is_stale == True, reason contains "closed" |
    | TEST-24-02-07    | unit      | StaleResult has correct fields        | Missing reason field            | Check StaleResult dataclass     | is_stale: bool, reason: str present        |
    | TEST-24-02-08    | unit      | Missing snapshot ID returns stale     | Returns not stale for missing   | Check non-existent ID           | is_stale == True, reason contains "not found"|

  Acceptance Criteria:
    AC-02-01: All 8 tests PASS
    AC-02-02: 10px jitter tolerance prevents false stale detection
    AC-02-03: WindowsAdapter.get_window_metadata() works without focus change

───────────────────────────────────────────────────────────

TASK-03: BATCH-24/TASK-03 — find_elements & get_element by ID
  Description:
    Implement find_elements(snapshot_id, query) that searches snapshot elements
    by name (case-insensitive substring), role, or element_id.
    Implement get_element(snapshot_id, element_id) that returns a single element.
    Both methods load from disk (no in-memory cache in this batch).

  Files in scope:
    - src/agent_core/cascade/snapshot_store.py    (MODIFY — add find_elements, get_element)

  Depends on: TASK-01

  Required Tests:
    | Test ID          | Type      | Behavior Verified                    | Failure Mode                    | Falsified By                     | Pass Criteria                              |
    |:-----------------|:----------|:-------------------------------------|:--------------------------------|:---------------------------------|:-------------------------------------------|
    | TEST-24-03-01    | unit      | find_elements by name substring      | Returns empty for valid query   | Search "button", check results  | Returns matching elements                  |
    | TEST-24-03-02    | unit      | find_elements case insensitive       | Only matches exact case         | Search "BUTTON" vs "Button"     | Both return same results                   |
    | TEST-24-03-03    | unit      | find_elements by role                | Role filter ignored             | Search role="button"            | Returns only button elements               |
    | TEST-24-03-04    | unit      | find_elements by element_id          | Returns multiple for unique ID  | Search "E1"                     | Returns exactly 1 element                  |
    | TEST-24-03-05    | unit      | find_elements no match returns []    | Returns None or raises          | Search "nonexistent"            | Returns empty list                         |
    | TEST-24-03-06    | unit      | get_element returns correct element  | Returns wrong element           | Get E2 from 5-element snapshot  | Returns element with element_id "E2"       |
    | TEST-24-03-07    | unit      | get_element missing returns None     | Raises exception                | Get "E999"                      | Returns None                               |
    | TEST-24-03-08    | unit      | get_element missing snapshot returns None | Returns empty element       | Get E1 from non-existent snapshot| Returns None                             |

  Acceptance Criteria:
    AC-03-01: All 8 tests PASS
    AC-03-02: Search is O(n) in element count (no index needed at <100 elements)
    AC-03-03: Both methods handle missing snapshots gracefully (return None/[])

───────────────────────────────────────────────────────────

TASK-04: BATCH-24/TASK-04 — CLI Integration & Health Check
  Description:
    Add `desktop-agent snapshot` command that creates a snapshot and prints
    the snapshot ID + element table. Add `--snapshot <id>` and `--on <element_id>`
    flags to `click` and `type` commands so they target elements from a persisted
    snapshot. Add snapshot store to health checks (9th check). Add `desktop-agent snapshots`
    command to list stored snapshots. Add `desktop-agent snapshots clean` to prune.

  Files in scope:
    - src/agent_core/cli/main.py                   (MODIFY — add snapshot/snapshots commands)
    - src/agent_core/cli/formatters.py              (MODIFY — add snapshot formatting)
    - src/agent_core/safety/health.py               (MODIFY — add snapshot_store check)
    - src/agent_core/desktop_agent.py               (MODIFY — add snapshot methods to facade)

  Depends on: TASK-01, TASK-02, TASK-03

  Required Tests:
    | Test ID          | Type      | Behavior Verified                    | Failure Mode                    | Falsified By                     | Pass Criteria                              |
    |:-----------------|:----------|:-------------------------------------|:--------------------------------|:---------------------------------|:-------------------------------------------|
    | TEST-24-04-01    | unit      | `snapshot` command returns snapshot_id| Returns empty output            | Run snapshot command, parse output| Output contains snapshot ID (UUID format)   |
    | TEST-24-04-02    | unit      | `snapshot --json` valid JSON         | Invalid JSON output             | Parse output as JSON             | JSON parseable, has snapshot_id field      |
    | TEST-24-04-03    | unit      | `snapshots list` lists snapshots     | Returns empty after creating    | Create 2, list, check count     | Output shows 2 snapshots                   |
    | TEST-24-04-04    | unit      | `snapshots clean` removes all        | Snapshots remain after clean    | Create 3, clean, list           | List returns 0 snapshots                   |
    | TEST-24-04-05    | unit      | Health check includes snapshot_store | Missing from health checks      | Run health, check output        | snapshot_store present in checks           |
    | TEST-24-04-06    | unit      | Health N/A when no snapshots dir     | Health FAILS without dir        | Health before first snapshot    | snapshot_store is N/A (not FAIL)           |
    | TEST-24-04-07    | unit      | click --on resolves element          | Element not found in snapshot   | Click E1 from snapshot          | Click dispatched to correct coordinates    |
    | TEST-24-04-08    | unit      | click --on stale snapshot fails      | Click executes on stale data    | Click after window moved        | Returns SNAPSHOT_STALE error               |
    | TEST-24-04-09    | unit      | type --on resolves text field        | Types in wrong element          | Type T1 from snapshot           | Text dispatched to correct element         |
    | TEST-24-04-10    | unit      | DesktopAgent.snapshot_store property | AttributeError                  | Access agent.snapshot_store     | Returns SnapshotStore instance             |
    | TEST-24-04-11    | unit      | Snapshot element table formatted     | Raw JSON in output              | Check --json output format      | Elements have element_id, role, name       |
    | TEST-24-04-12    | unit      | `snapshot --app` filters by app     | Ignores app filter                | Pass --app Notepad, check output| Only Notepad elements in output            |
    | TEST-24-04-13    | unit      | Existing tests still pass            | Regression in baseline          | Run full test suite             | 2,943 baseline + 44 new = 2,987 all pass  |
    | TEST-24-04-14    | integration| Full see-click-verify workflow       | Click misses target             | Snapshot → click E1 → verify   | Action succeeds, confidence > 0.5          |
    | TEST-24-04-15    | integration| Snapshot survives process restart    | Data lost on restart            | Create snapshot, restart store  | Snapshot loadable after new store instance |

  Acceptance Criteria:
    AC-04-01: All 15 tests PASS
    AC-04-02: `desktop-agent snapshot` and `desktop-agent snapshots` commands work
    AC-04-03: `click --on E1 --snapshot <id>` resolves element from disk
    AC-04-04: Full test suite passes: 2,987 (2,943 baseline + 44 new)
    AC-04-05: Health check 9th item: snapshot_store (N/A when not used, PASS when working)

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  BAC-01: SnapshotStore persists snapshots to ~/.desktop-agent/snapshots/<uuid>/
  BAC-02: Element IDs are deterministic (same tree → same IDs across loads)
  BAC-03: CHANGELOG.md updated with BATCH-24 entry.
  BAC-04: All documents archived under /docs/aiv/BATCH-24/.
  BAC-05: Version bumped to v0.32.0 in cli/version.py + pyproject.toml.
  BAC-06: Full test suite passes: 2,987 tests (2,943 baseline + 44 new).
  BAC-07: No files written outside declared scope (HB-01 verified).
  BAC-08: Stale snapshot detection works for moved, resized, closed, retitled windows.
  BAC-09: CLI `snapshot` + `snapshots` + `click --on` + `type --on` all functional.
  BAC-10: Health check expanded from 8 to 9 items (snapshot_store added).

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────

Reviewer Report ID:       REVIEW-BATCH-24-2026-05-10
Review Cycle:             1
Lead Decision:            [x] ACCEPT WITH MODIFICATIONS

If ACCEPT WITH MODIFICATIONS — list each Reviewer flag acted on:
  FLAG-01 (CHK-14) → Test delta corrected from +52 to +44 (13+8+8+15=44, not 52)
  FLAG-02 (CHK-16) → Scope item changed from "Integrate into WindowsAdapter" to "Integrate into DesktopAgent facade" — matches TASK-04 actual scope
  FLAG-03 (CHK-17) → TEST-24-04-12 removed (references undeclared --mode flag). Replaced with test for --app filter which IS in the command design.
  FLAG-04 (CHK-17) → Traceability typo fixed: TEST-04-04 → TEST-24-04-04

Blueprint Version after response: 1.1
Lead Sign:                Craft Agent — 2026-05-10 10:50 GMT+3

═══════════════════════════════════════════════════════════
```

---

## AC-to-Test Traceability Matrix

| AC | Task | Tests Covering It |
|----|------|-------------------|
| AC-01-01 | TASK-01 | TEST-24-01-01 through TEST-24-01-13 |
| AC-01-02 | TASK-01 | TEST-24-01-12 (stdlib only — no imports checked) |
| AC-01-03 | TASK-01 | TEST-24-01-03, TEST-24-01-04 (deterministic IDs) |
| AC-01-04 | TASK-01 | TEST-24-01-05 (writes to correct dir) |
| AC-02-01 | TASK-02 | TEST-24-02-01 through TEST-24-02-08 |
| AC-02-02 | TASK-02 | TEST-24-02-03 (10px jitter) |
| AC-02-03 | TASK-02 | TEST-24-02-02, TEST-24-02-04, TEST-24-02-05, TEST-24-02-06 |
| AC-03-01 | TASK-03 | TEST-24-03-01 through TEST-24-03-08 |
| AC-03-02 | TASK-03 | TEST-24-03-01 (O(n) search, no index) |
| AC-03-03 | TASK-03 | TEST-24-03-05, TEST-24-03-07, TEST-24-03-08 |
| AC-04-01 | TASK-04 | TEST-24-04-01 through TEST-24-04-15 |
| AC-04-02 | TASK-04 | TEST-24-04-01, TEST-24-04-02, TEST-24-04-03, TEST-24-04-04 |
| AC-04-03 | TASK-04 | TEST-24-04-07, TEST-24-04-08, TEST-24-04-09 |
| AC-04-04 | TASK-04 | TEST-24-04-13 |
| AC-04-05 | TASK-04 | TEST-24-04-05, TEST-24-04-06 |
| BAC-01 | ALL | TEST-24-01-05, TEST-24-01-06 |
| BAC-02 | ALL | TEST-24-01-03 |
| BAC-03 | ALL | CHANGELOG.md entry (manual) |
| BAC-04 | ALL | Archive under docs/aiv/BATCH-24/ (manual) |
| BAC-05 | ALL | Version bump (manual) |
| BAC-06 | ALL | TEST-24-04-13 (full suite) |
| BAC-07 | ALL | TEST-24-01-05 (correct dir), TEST-24-01-12 (no secrets) |
| BAC-08 | ALL | TEST-24-02-02 through TEST-24-02-06 |
| BAC-09 | ALL | TEST-24-04-01 through TEST-24-04-09 |
| BAC-10 | ALL | TEST-24-04-05, TEST-24-04-06 |
