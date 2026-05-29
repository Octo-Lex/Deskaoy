BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-39
Blueprint Version:        1.1
Cycle Mode:               STANDARD
Lead Programmer:          Lead (Session 260520-apt-topaz)
Date Issued:              2026-05-21
Review SLA:               30 min
Execution SLA per Task:   90 min
Partial Sign-Off SLA:     15 min
Task Sequencing:          Sequential (TASK-02 depends on TASK-01; TASK-03 depends on TASK-02)

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────

Create a standalone pyproject.toml for the super-browser package so it can be
released independently as `pip install super-browser`. Update the root
desktop-agent pyproject.toml so `[browser]` extra depends on `super-browser>=1.0.0`
instead of listing browser deps directly. Verify both packages build and their
tests pass in isolation.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────

What the code MUST do:
  - Create `src/super_browser/pyproject.toml` defining the `super-browser` package
  - super-browser depends on `desktop-agent` (agent_core provides shared types)
  - super-browser depends on `patchright>=1.0`, `psutil>=5.9`, `Pillow>=10.0`, `curl_cffi>=0.15`
  - Root pyproject.toml `[browser]` extra becomes `super-browser>=1.0.0`
  - Root pyproject.toml hatch build continues to ship both packages in one wheel
    (monorepo build — the split is for independent pip install, not separate wheels)
  - `pip install -e .[browser]` from the monorepo still works (dev workflow)
  - `pip install super-browser` (when published) pulls in desktop-agent automatically
  - All 3,492 existing tests continue passing

What the code MUST NOT do:
  - Change the monorepo directory structure (src/agent_core/ and src/super_browser/ stay put)
  - Remove any existing test or break any existing import
  - Add a separate build pipeline for super-browser in this batch (that's a future concern)
  - Modify any source code in src/ (only pyproject.toml files change)
  - Make desktop-agent depend on super-browser at runtime (dependency is optional, one-way)

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────

  HB-01: `pip install -e .` from the monorepo root MUST still install agent_core
         and all tests MUST pass. Violation: any test that currently passes fails
         after the pyproject.toml changes.

  HB-02: `import agent_core` MUST NOT trigger any super_browser import.
         Violation: `python -c "import agent_core"` fails when super_browser is not
         installed. (Same as BATCH-38 HB-01, carried forward.)

  HB-03: The `[browser]` extra in desktop-agent's pyproject.toml MUST list exactly
         `super-browser>=1.0.0` and nothing else. The old direct deps (patchright,
         psutil, etc.) move to super-browser's pyproject.toml.
         Violation: `[browser]` still lists patchright directly.

  HB-04: No source code changes. Only pyproject.toml files are modified.
         Violation: any .py file in src/ is modified.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

New file: `src/super_browser/pyproject.toml`

    [build-system]
    requires = ["hatchling"]
    build-backend = "hatchling.build"

    [project]
    name = "super-browser"
    version = "1.0.0"
    description = "Browser automation for AI agents — 3-tier cascade (selector → coordinate → vision)"
    requires-python = ">=3.11"
    dependencies = [
        "desktop-agent>=1.0.0",   # agent_core shared types
        "patchright>=1.0",
        "psutil>=5.9",
        "Pillow>=10.0",
        "curl_cffi>=0.15",
    ]

    [tool.hatch.build.targets.wheel]
    packages = ["src/super_browser"]

Modified: Root `pyproject.toml`

    [project.optional-dependencies]
    browser = ["super-browser>=1.0.0"]    # was: patchright, psutil, Pillow, curl_cffi

───────────────────────────────────────────────────────────
AUTHORITY RULES
───────────────────────────────────────────────────────────

  AUTH-01: super-browser's pyproject.toml is the authority for browser-specific
           dependencies (patchright, curl_cffi). desktop-agent's pyproject.toml
           no longer lists them.

  AUTH-02: desktop-agent's `[browser]` extra is a thin pointer to super-browser.
           It does not duplicate any dependency declarations.

  AUTH-03: The monorepo root pyproject.toml continues to build both packages
           via hatch's `packages = ["src/agent_core", "src/super_browser"]`.
           The super-browser pyproject.toml is for independent publishing only.

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────

  Prior Batches:
    BATCH-38 (with_browser factory + lazy init) — REQUIRED, done

  External:
    hatchling — build backend (already used)
    patchright, psutil, Pillow, curl_cffi — browser deps (moving to super-browser)

  Unresolved:
    None.

───────────────────────────────────────────────────────────
STATE.md STATUS
───────────────────────────────────────────────────────────

  State file exists: YES (populated at BATCH-38 close)
  STATE.md path:     [project root]/STATE.md
  Last verified:     BATCH-38 close (2026-05-21)

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────

  Baseline at Blueprint issuance:  3,492 tests
  Expected delta (all Tasks):      +7 new tests
  Expected total at Batch close:   3,499

───────────────────────────────────────────────────────────
LINT COMMAND
───────────────────────────────────────────────────────────

  N/A — no Python source changes. Validate TOML syntax only:
  python -c "import tomllib; tomllib.load(open('src/super_browser/pyproject.toml','rb'))"

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-39/TASK-01 — Create super-browser pyproject.toml
────────────────────────────────────────────────────────────────
  Description:
    Create `src/super_browser/pyproject.toml` as a standalone package definition.
    Lists desktop-agent as a dependency (provides agent_core shared types).
    Lists browser-specific deps (patchright, psutil, Pillow, curl_cffi).
    Uses hatchling as the build backend (consistent with monorepo).

  Files in scope:
    - src/super_browser/pyproject.toml (new file)

  Depends on: None

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-39-01-01 | unit | super_browser/pyproject.toml is valid TOML | Syntax error in file | Remove a closing bracket | tomllib.load() succeeds without exception |
    | TEST-39-01-02 | unit | Package name is super-browser (PEP 503 normalized) | Name is super_browser with underscore | Change name to super_browser | parsed["project"]["name"] == "super-browser" |
    | TEST-39-01-03 | unit | super-browser depends on desktop-agent | Missing dependency | Remove desktop-agent from dependencies list | "desktop-agent" in parsed["project"]["dependencies"] |
    | TEST-39-01-04 | unit | super-browser depends on patchright | Browser deps not listed | Remove patchright line | "patchright" found in dependencies |

  Acceptance Criteria:
    AC-01-01: super_browser/pyproject.toml exists and is valid TOML
    AC-01-02: Package name is "super-browser" (PEP 503 normalized, not "super_browser")
    AC-01-03: Package declares dependency on desktop-agent>=1.0.0
    AC-01-04: Package declares browser-specific dependencies (patchright, psutil, Pillow, curl_cffi)

  AC-to-Test Traceability:
    AC-01-01 → TEST-39-01-01
    AC-01-02 → TEST-39-01-02
    AC-01-03 → TEST-39-01-03
    AC-01-04 → TEST-39-01-04


TASK-02: BATCH-39/TASK-02 — Update root pyproject.toml [browser] extra
────────────────────────────────────────────────────────────────────────
  Description:
    Replace the `[browser]` extra in the root pyproject.toml. Remove the direct
    browser dependency list (patchright, psutil, Pillow, curl_cffi) and replace
    with a single `super-browser>=1.0.0` entry. Update the `[all]` extra if needed.

  Files in scope:
    - pyproject.toml (modify [project.optional-dependencies] browser section)

  Depends on: TASK-01

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-39-02-01 | unit | [browser] extra contains super-browser only | Still lists patchright directly | Revert to old browser deps list | browser_extra == ["super-browser>=1.0.0"] |
    | TEST-39-02-02 | unit | [browser] extra does NOT contain patchright directly | Duplicated dep in both packages | Add patchright back to [browser] | "patchright" not in browser_extra |

  Acceptance Criteria:
    AC-02-01: [browser] extra lists exactly `super-browser>=1.0.0`
    AC-02-02: [browser] extra does not list patchright, psutil, Pillow, or curl_cffi directly

  AC-to-Test Traceability:
    AC-02-01 → TEST-39-02-01
    AC-02-02 → TEST-39-02-02


TASK-03: BATCH-39/TASK-03 — Verify build + test regression
────────────────────────────────────────────────────────────────────────
  Description:
    Run the full test suite to verify no regressions from the pyproject.toml changes.
    Verify that `pip install -e .` still works from the monorepo root.
    Verify that `import agent_core` still works without super_browser installed.
    Run the browser tests to confirm super_browser still imports correctly.

  Files in scope:
    - No new files (validation only)

  Depends on: TASK-01, TASK-02

  Required Tests:
    | Test ID | Type | Behavior Verified | Failure Mode | Falsified By | Pass Criteria |
    |:--------|:-----|:------------------|:-------------|:-------------|:--------------|
    | TEST-39-03-01 | integration | All 3,492 existing tests pass | pyproject.toml change broke an import | Change the hatch packages list | pytest exits with 0 failures |
    | TEST-39-03-02 | integration | pip install -e . succeeds from monorepo root | Hatch build fails with new config | Remove src/super_browser/pyproject.toml | pip install -e . exits 0 |
    | TEST-39-03-03 | integration | import super_browser succeeds after editable install | Package not found on sys.path | Change the packages list in pyproject.toml | python -c "import super_browser" exits 0 |

  Acceptance Criteria:
    AC-03-01: Full test suite passes with 0 failures (HB-01)
    AC-03-02: Editable install succeeds from monorepo root
    AC-03-03: No source code was modified (HB-04) — verified by git diff

  AC-to-Test Traceability:
    AC-03-01 → TEST-39-03-01
    AC-03-02 → TEST-39-03-02
    AC-03-03 → TEST-39-03-03

───────────────────────────────────────────────────────────
BATCH-LEVEL ACCEPTANCE CRITERIA
───────────────────────────────────────────────────────────

  BAC-01: super-browser pyproject.toml exists with correct dependencies.
  BAC-02: Root [browser] extra lists only super-browser>=1.0.0 (HB-03).
  BAC-03: All 3,492 existing tests pass unchanged (HB-01).
  BAC-04: No source code files modified — only pyproject.toml files (HB-04).
  BAC-05: CHANGELOG.md updated with BATCH-39 entry.
  BAC-06: Documents archived under /docs/aiv/BATCH-39/.

───────────────────────────────────────────────────────────
LEAD RESPONSE TO REVIEW REPORT
───────────────────────────────────────────────────────────

Reviewer Report ID:       REVIEW-BATCH-39-2026-05-21
Review Cycle:             1
Lead Decision:            [X] ACCEPT WITH MODIFICATIONS

Flags acted on:
  FLAG-01 (CHK-13: no package name test) → Added TEST-39-01-02 and AC-01-02
  FLAG-02 (CHK-17: hatch build path) → Fixed in implementation (omit [tool.hatch.build] section, let hatchling auto-detect)

═══════════════════════════════════════════════════════════
