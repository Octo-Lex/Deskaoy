BATCH BLUEPRINT
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-07
Blueprint Version:        1.0
Cycle Mode:               STANDARD
Lead Programmer:          Lead AI Instance
Date Issued:              2026-05-03
Review SLA:               30 min
Execution SLA per Task:   60 min
Partial Sign-Off SLA:     15 min
Task Sequencing:          Sequential

───────────────────────────────────────────────────────────
BATCH GOAL
───────────────────────────────────────────────────────────
Add typed workflow blocks (Skyvern pattern) that integrate with the existing
DAGExecutor to provide structured, validated, retryable multi-step desktop
automation — for loops, conditional waits, downloads, form fills, and
validation blocks.

───────────────────────────────────────────────────────────
SCOPE STATEMENT
───────────────────────────────────────────────────────────
What the code MUST do:
  - Define typed block types: ForLoop, Wait, Download, Validation, FormFill, CodeBlock
  - Each block validates its parameters before execution
  - Each block has defined retry semantics and error classification
  - Blocks compile to DAGNode lists for the existing DAGExecutor
  - WorkflowBuilder provides a fluent API for composing block sequences
  - All existing 2,691 tests continue to pass

What the code MUST NOT do:
  - Must NOT break any existing test
  - Must NOT change the DAGExecutor or DAGNode interfaces
  - Must NOT add external dependencies
  - Must NOT execute arbitrary code (CodeBlock is sandboxed)

───────────────────────────────────────────────────────────
HARD BOUNDARIES
───────────────────────────────────────────────────────────
  HB-01: Block compilation to DAGNode is deterministic (same input → same DAG).
  HB-02: CodeBlock MUST be sandboxed (restricted builtins, no file/network access).
  HB-03: Each block type MUST have at least 2 unit tests.
  HB-04: The existing test count of 2,691 MUST NOT decrease.
  HB-05: No file outside src/agent_core/ may be modified except test files,
         CHANGELOG.md, and docs/aiv/BATCH-07/.

───────────────────────────────────────────────────────────
DATA MODELS / SCHEMA
───────────────────────────────────────────────────────────

WorkflowBlock (base):
  id: str
  block_type: str
  params: dict[str, Any]
  retry_count: int = 0
  timeout: float = 60.0
  validate() -> list[str]    # returns list of validation errors
  compile(agent) -> list[DAGNode]  # converts to executable DAG

Block types:
  ForLoopBlock: items list, body block, max_iterations
  WaitBlock: condition (callable or str), timeout, poll_interval
  DownloadBlock: url, target_path, verify_checksum (optional)
  ValidationBlock: assertion (callable or str), error_message
  FormFillBlock: fields dict[str, str], submit: bool
  CodeBlock: code: str, allowed_builtins: list[str]

WorkflowBuilder:
  add(block) -> self       # fluent API
  compile(agent) -> DAG    # compile all blocks
  to_dag_nodes() -> list[DAGNode]

WorkflowResult:
  blocks_total: int
  blocks_completed: int
  blocks_failed: int
  results: list[DAGNodeResult]
  duration_ms: float

───────────────────────────────────────────────────────────
DEPENDENCY MAP
───────────────────────────────────────────────────────────
  BATCH-06 (Snapshot Diffing): DONE
  orchestration/dag.py (DAGExecutor): exists, stable

───────────────────────────────────────────────────────────
TEST BASELINE
───────────────────────────────────────────────────────────
  Baseline: 2,691 existing tests
  Expected delta: +25 new tests
  Expected total: ~2,716

───────────────────────────────────────────────────────────
TASK LIST
───────────────────────────────────────────────────────────

TASK-01: BATCH-07/TASK-01 — Block Types + Validation
  Description:      Create orchestration/blocks.py with typed block classes
  Files in scope:   src/agent_core/orchestration/blocks.py (new)
  Required Tests:   15+ tests covering all 6 block types
  Acceptance Criteria:
    AC-01-01: All 6 block types validate parameters
    AC-01-02: Invalid parameters return non-empty error lists
    AC-01-03: Valid parameters return empty error lists

TASK-02: BATCH-07/TASK-02 — WorkflowBuilder + DAG Compilation
  Description:      Create orchestration/workflow.py with builder and compilation
  Files in scope:   src/agent_core/orchestration/workflow.py (new)
  Depends on:       TASK-01
  Required Tests:   10+ tests
  Acceptance Criteria:
    AC-02-01: WorkflowBuilder fluent API works
    AC-02-02: compile() produces valid DAGNode list
    AC-02-03: ForLoopBlock compiles to repeated DAG nodes

TASK-03: BATCH-07/TASK-03 — CHANGELOG + Certificate
  Files in scope:   CHANGELOG.md, docs/aiv/BATCH-07/
  Depends on:       TASK-01, TASK-02
  Acceptance Criteria:
    AC-03-01: Version bumped to 0.20.1
    AC-03-02: CHANGELOG updated

═══════════════════════════════════════════════════════════
