# DESKTOP-AGENT — MASTER ROADMAP (AIV Framework v3.0)

**Project:** desktop-agent — Surface-agnostic desktop agent for the AI Operating System
**Lead Programmer:** Lead AI Instance
**Current Version:** v1.0.0 | **3,515 tests passing**
**Source:** 235 source files, 30,848 source lines | 173 test files
**Framework:** AIV v3.0 — Plan → Review → Execute → Verify

---

## A. PROJECT STATUS

### Completed Batches (Pre-AIV, now frozen)

| Batch | Version | What | Tests |
|-------|---------|------|-------|
| Phase 0 | v0.1.0 | 5 critical + 8 high + 10 medium bug fixes | 1,086 |
| Phase 1 | v0.1.5 | agent-core extraction + input layer | 1,221 |
| Phase 2 | v0.2.0 | Visual grounding + stealth + BrowserAdapter | 1,388 |
| Phase 3A | v0.3.0 | Windows adapter + memory + feedback + LLM client | 1,661 |
| Phase 3B | v0.5.0 | OpenCLI gems + wiring | 1,766 |
| AIOS-1..7 | v0.6.0 | AI-OS realignment | 1,817 |
| AIOS-8..9 | v0.7.0 | Learning + stealth gate + artifacts | 1,842 |
| Bridge | v0.8.0 | Policy + trace + recovery wiring | 1,858 |
| gogcli | v0.9.0 | Circuit breaker + retry + action guards | 1,903 |
| LangExtract | v0.10.0 | Grounding verification + validation + context | 1,961 |
| Hardening | v0.11.0 | Rate governor + crash recovery + latency + cost + health | 2,036 |
| Orchestration | v0.12.0 | Blackboard + DAG + AppAgent + HostAgent | 2,107 |
| CI/Bench | v0.12.1 | Smoke tests + benchmark harness | 2,139 |
| det-acp | v0.13.0 | Evidence ledger + session budget + policy evolution | 2,190 |
| Compensation | v0.14.0 | Rollback plans + compensating actions | 2,238 |
| Routines | v0.15.0 | Routines + SKILL.md + fact extraction | 2,349 |
| Ref Patterns | v0.16.0 | Schedule tz + pyautogui fix + validation + timeout + resource + observation | 2,457 |

### Current Architecture

```
desktop-agent v0.16.0
├── agent_core/           17,600 lines — surface-agnostic engine
│   ├── os_types.py       AI-OS contract v2.2 types
│   ├── desktop_agent.py  DesktopAgent (execute/estimate/undo/compensate)
│   ├── adapters/         Windows (UIA) ✅ | macOS 🔲 | Linux 🔲
│   ├── agent/            AgentLoop + ToolRegistry + Delegator
│   ├── safety/           Rate governor + cost tracker + latency + session budget + evidence ledger + policy evolution + compensation + action validator + timeout guard + resource tracker
│   ├── grounding/        YOLO + OCR + fusion + caption pipeline
│   ├── input/            Bézier + jitter + humanization
│   ├── memory/           Action memory + self-healing + facts + soul
│   ├── routines/         Cron scheduling + timezone support
│   ├── skills/           SKILL.md loader + builtin skills
│   ├── pipeline/         Deterministic zero-LLM action pipelines
│   ├── orchestration/    Blackboard + DAG + AppAgent + HostAgent
│   ├── recovery/         Checkpoint + watchdogs + crash recovery + error classifier
│   ├── verification/     Look-act-verify + grounding verification
│   ├── llm/              SimpleLLMClient (OpenAI + Anthropic)
│   └── vision/           VLM providers + OCR + grounding factory
│
└── super_browser/        5,375 lines — browser adapter
    ├── BrowserAdapter    SurfaceAdapter impl wrapping MultimodalController
    ├── interaction/       3-tier cascade + memory + fuzzy matching
    ├── stealth/           curl_cffi Chrome 146 TLS fingerprint
    └── browser/           CDP bridge + Patchright session
```

---

## B. REMAINING WORK — AIV BATCHES

### Overview

| Batch ID | What | Version Target | Est. Hours | New Tests | Status |
|----------|------|---------------|------------|-----------|--------|
| BATCH-01 | CLI Entry Point + REPL | v0.17.0 | ~3h | ~30 | ✅ DONE |
| BATCH-02 | Real-World Demo + Integration Proof | v0.17.1 | ~1.5h | ~10 | ✅ DONE |
| BATCH-03 | AI-OS B38 Alignment: Runtime Execution Hardening | v0.18.0 | ~4h | 17 | ✅ DONE |
| BATCH-04 | PyPI Release Prep | v0.18.1 | ~1.5h | 0 | ✅ DONE |
| BATCH-05 | CLI Crash Fix + Version + Safety + MCP/REST Transport | v0.19.0 | ~6h | 44 | ✅ DONE |
| BATCH-06 | Snapshot Differ + Two-Step Verifier | v0.20.0 | ~3h | 34 | ✅ DONE |
| BATCH-07 | Typed Workflow Blocks (Skyvern Pattern) | v0.20.1 | ~4h | 34 | ✅ DONE |
| BATCH-08 | CUA Integration (Computer Use Agent) | v0.22.0 | ~4h | 15 | ✅ DONE |
| BATCH-09 | Environment Interface (UI-TARS Pattern) | v0.22.1 | ~2h | 12 | ✅ DONE |
| BATCH-10 | Real-World Evaluation Framework | v0.23.0 | ~3h | 21 | ✅ DONE |
| BATCH-11 | Per-App JSON Guides | v0.24.0 | ~2h | 11 | ✅ DONE |
| BATCH-12 | Security Audit + Hardening | v0.24.0 | ~4h | 6 | ✅ DONE |
| BATCH-13 | Performance Optimization + Profiling | v0.25.0 | ~3h | 35 | ✅ DONE |
| BATCH-14 | Documentation + API Reference | v0.25.0 | ~3h | 0 | ✅ DONE |
| BATCH-15 | v1.0 Release Candidate | v1.0.0rc1 | ~2h | 53 | ✅ DONE |

**Total estimated effort: ~51 hours**
**Total estimated new tests: ~290**
**Projected final test count: ~2,747**

---

## C. BATCH DETAILS

### BATCH-01: CLI Entry Point + REPL ✅
**Version:** v0.17.0 | **Tests:** 49 | **Status:** CLOSED

CLI entry point with 14 subcommands, REPL, formatters. All 5 AIV docs archived.

---

### BATCH-02: Real-World Demo + Integration Proof ✅
**Version:** v0.17.1 | **Tests:** 10 | **Status:** CLOSED

E2E demo, routines+skills+facts demo, 10 integration tests. All 5 AIV docs archived.

---

### BATCH-03: AI-OS B38 Alignment — Runtime Execution Hardening
**Version:** v0.18.0 | **Effort:** ~4h | **New Tests:** ~40

**Scope:**
- Canonical preflight: formalized 12-check preflight (desktop-relevant subset of B38's 28 checks)
- Policy obligation enforcement: mechanical enforcement of `dry_run_required`, `approval_required`, `quarantine_on_failure`
- Attempt lifecycle: `pending` → `preflight_passed` → `running` → terminal state
- Truthful receipt: `RuntimeExecutionReceipt` extending AgentResult with B38 truth fields
- Adapter capability declarations: surface adapters declare what they support
- Preflight fingerprint: hash of registry + policy + health state for TOCTOU safety

**Dependencies:** BATCH-01 (CLI), v0.13.0+ (policy bridge, evidence ledger)
**Analysis:** `plans/AIOS-BATCH38-GAP-ANALYSIS.md`

---

### BATCH-04: PyPI Release Prep
**Version:** v0.18.1 | **Effort:** ~1.5h | **New Tests:** ~5

**Scope:**
- pyproject.toml: entry points, classifiers, license, URLs
- README badges (tests, version, python)
- LICENSE file (MIT)
- `pip install desktop-agent` works end-to-end
- Dependency group validation (core/browser/llm/grounding/dev all installable)
- Smoke test: fresh venv → pip install → `desktop-agent version`

**Dependencies:** BATCH-01

---

### BATCH-04: macOS Adapter (AXUIElement)
**Version:** v0.19.0 | **Effort:** ~6h | **New Tests:** ~40

**Scope:**
- `adapters/macos.py` — AXUIElement-based SurfaceAdapter
- Tree walking via AXUIElementCopyAttributeValue (AXChildren)
- Element actions: click, fill, type_text, key_press, scroll, hover
- Screenshot via screencapture / Quartz
- Window management via NSWorkspace
- All 17 SurfaceAdapter protocol methods
- dry_run support on all mutating actions
- Graceful degradation when not on macOS

**Dependencies:** v0.16.0 (SurfaceAdapter protocol frozen)
**Design:** Mirror WindowsAdapter pattern — comtypes → pyobjc bridge

---

### BATCH-05: Linux Adapter (AT-SPI)
**Version:** v0.19.1 | **Effort:** ~6h | **New Tests:** ~40

**Scope:**
- `adapters/linux.py` — AT-SPI-based SurfaceAdapter
- Tree walking via pyatspi.Registry.getDesktop(0)
- Element actions via Accessible Action interface
- Screenshot via scrot / GNOME Screenshot / Pillow
- Window management via wnck / xdotool
- All 17 SurfaceAdapter protocol methods
- dry_run support
- Graceful degradation when not on Linux/X11

**Dependencies:** v0.16.0 (SurfaceAdapter protocol frozen)

---

### BATCH-06: Two-Step Actions (Stagehand Pattern)
**Version:** v0.20.0 | **Effort:** ~3h | **New Tests:** ~15

**Scope:**
- AgentLoop option: `two_step=True` enables post-action LLM follow-up
- After primary action execution, take new observation
- Send diff to LLM → LLM proposes follow-up action
- Execute follow-up → return combined result
- Use cases: dropdown→select, hover→submenu, dialog→confirm

**Dependencies:** BATCH-01 (CLI may use two-step)

---

### BATCH-07: Typed Workflow Blocks (Skyvern Pattern)
**Version:** v0.20.1 | **Effort:** ~4h | **New Tests:** ~20

**Scope:**
- Block types: ForLoop, CodeBlock, Download, Validation, Wait, SendEmail
- Parameter validation per block type
- Error classification per block type
- Retry semantics per block type
- Integration with DAGExecutor

**Dependencies:** v0.16.0 (DAG executor already exists)

---

### BATCH-08: Snapshot Diffing (Stagehand Pattern)
**Version:** v0.21.0 | **Effort:** ~1.5h | **New Tests:** ~10

**Scope:**
- `cascade/differ.py` — compute diff between two AX snapshots
- Diff format: added elements, removed elements, changed elements
- Token savings: send only diff to LLM instead of full tree
- Integration with formatter (diff-formatted output)

**Dependencies:** v0.16.0 (formatter + snapshot exist)

---

### BATCH-09: CUA Integration (Computer Use Agent)
**Version:** v0.22.0 | **Effort:** ~4h | **New Tests:** ~20

**Scope:**
- Support OpenAI CUA API (computer_use tool)
- Support Anthropic CUA API (computer_20241022 tool)
- Screenshot-based action loop: screenshot → CUA proposes → execute → repeat
- Integration with DesktopAgent as alternative to AgentLoop
- Fallback to AgentLoop when CUA unavailable

**Dependencies:** BATCH-01 (CLI entry point)

---

### BATCH-10: Environment Interface (UI-TARS Pattern)
**Version:** v0.22.1 | **Effort:** ~2h | **New Tests:** ~10

**Scope:**
- `adapters/environment.py` — Environment protocol
- Lifecycle: initialize → on_before_tool → on_after_tool → on_dispose
- Environment implementations: LocalDesktop, DockerDesktop, RemoteVM
- Swap environments without changing agent logic

**Dependencies:** BATCH-04 + BATCH-05 (at least one adapter exists)

---

### BATCH-11: Real-World Evaluation Framework
**Version:** v0.23.0 | **Effort:** ~3h | **New Tests:** ~15

**Scope:**
- OSWorld-compatible task config format
- JSON task definitions: instruction, setup, evaluator, metric
- Built-in evaluators: exact_match, contains, file_exists, screenshot_diff
- Benchmark runner: execute task → evaluate → score
- Sample task suite (10 tasks for Windows desktop)

**Dependencies:** BATCH-01 + observation protocol (v0.16.0)

---

### BATCH-12: Documentation + API Reference
**Version:** v0.24.0 | **Effort:** ~3h | **New Tests:** ~0

**Scope:**
- API reference for all public classes/functions (autodoc or hand-written)
- Architecture guide (updated from MASTER-PLAN.md)
- Quick-start guide (install → first action → schedule → REPL)
- Adapter development guide (how to add a new OS adapter)
- CONTRIBUTING.md

**Dependencies:** BATCH-01 through BATCH-05

---

### BATCH-13: Performance Optimization + Profiling
**Version:** v0.25.0 | **Effort:** ~3h | **New Tests:** ~10

**Scope:**
- Profile hot paths: AgentLoop, cascade, formatter, memory lookup
- Optimize formatter (currently 4-pass, may benefit from single-pass)
- Optimize memory fingerprint hashing (consider xxhash over hashlib)
- Benchmark regression tests
- Latency targets: click <50ms dispatch, snapshot <200ms, full loop <2s

**Dependencies:** BATCH-01 (CLI enables real profiling)

---

### BATCH-14: Security Audit + Hardening
**Version:** v0.26.0 | **Effort:** ~4h | **New Tests:** ~20

**Scope:**
- Audit all user-provided string inputs for injection
- Validate LLM response parsing (no arbitrary code execution)
- Credential storage audit (no secrets in logs, memory, or disk)
- Sandbox evaluation (restrict `evaluate()` to read-only)
- Rate limit enforcement audit
- Policy evolution security review
- Evidence ledger integrity verification

**Dependencies:** All feature batches complete

---

### BATCH-15: v1.0 Release Candidate
**Version:** v1.0.0rc1 | **Effort:** ~2h | **New Tests:** ~10

**Scope:**
- Final integration test pass (all platforms)
- CI pipeline finalization (all Python 3.11+3.12+3.13)
- Release notes + CHANGELOG
- Tag + GitHub release
- PyPI publish dry-run

**Dependencies:** BATCH-01 through BATCH-14

---

## D. DEPENDENCY GRAPH

```
BATCH-01 (CLI)
├── BATCH-02 (Demos)
├── BATCH-03 (PyPI)
├── BATCH-06 (Two-Step)
├── BATCH-09 (CUA)
└── BATCH-11 (Eval Framework)

BATCH-04 (macOS) ──┐
BATCH-05 (Linux) ──┼── BATCH-10 (Environment Interface)
                    │
BATCH-07 (Blocks) ──┤
BATCH-08 (Diffing) ─┤
                    │
BATCH-12 (Docs) ────┤
BATCH-13 (Perf) ────┤
                    └── BATCH-14 (Security) ── BATCH-15 (v1.0 RC)
```

**Critical path:** BATCH-01 → BATCH-03 → BATCH-04/05 → BATCH-10 → BATCH-14 → BATCH-15

**Parallelizable:** BATCH-04 + BATCH-05 can run concurrently. BATCH-06/07/08 can run concurrently.

---

## E. AIV PROCESS PER BATCH

Each batch follows the AIV Framework v3.0 cycle:

```
┌─────────────────────────────────────────────────────┐
│ PHASE I    Lead writes Blueprint                     │
│            → docs/aiv/BATCH-XX/BATCH_XX_BLUEPRINT.md │
├─────────────────────────────────────────────────────┤
│ PHASE I-B  Reviewer evaluates Blueprint              │
│            → docs/aiv/BATCH-XX/REVIEW-BATCH-XX.md    │
│            Lead responds: ACCEPT / MODIFY / REJECT   │
├─────────────────────────────────────────────────────┤
│ PHASE II   Assistant implements                      │
│            → Code + tests + BATCH_XX.md              │
│            → docs/aiv/BATCH-XX/REPORT-BATCH-XX.md    │
├─────────────────────────────────────────────────────┤
│ PHASE III  Lead verifies + signs off                 │
│            → docs/aiv/BATCH-XX/CERT-BATCH-XX.md      │
│            Sprint closed                             │
└─────────────────────────────────────────────────────┘
```

### Documents Per Batch (5 documents, audit trail)

| # | Document | File | Author |
|---|----------|------|--------|
| 1 | Blueprint | `docs/aiv/BATCH-XX/BATCH_XX_BLUEPRINT.md` | Lead |
| 2 | Review Report | `docs/aiv/BATCH-XX/REVIEW-BATCH-XX.md` | Reviewer |
| 3 | Blueprint (with Lead Response) | Updated in Blueprint | Lead |
| 4 | Implementation Report | `docs/aiv/BATCH-XX/REPORT-BATCH-XX.md` | Assistant |
| 5 | Sign-Off Certificate | `docs/aiv/BATCH-XX/CERT-BATCH-XX.md` | Lead |

---

## F. VERSION TARGETS

| Milestone | Batch Range | Version | Significance |
|-----------|-------------|---------|-------------|
| **Alpha** | v0.17–0.18 | v0.18.0 | CLI + PyPI installable |
| **Cross-Platform** | v0.19 | v0.19.1 | All 3 OS adapters |
| **Advanced Features** | v0.20–0.22 | v0.22.1 | Two-step + blocks + CUA + environments |
| **Production Ready** | v0.23–0.26 | v0.26.0 | Eval + docs + perf + security |
| **1.0** | v1.0.0rc1 | v1.0.0 | Release candidate |

---

## G. TEST TARGETS

| Metric | Current (v0.16.0) | Target (v1.0.0) |
|--------|-------------------|------------------|
| Total tests | 2,457 | ~2,710 |
| Unit tests | ~2,350 | ~2,550 |
| Integration tests | ~30 | ~80 |
| Smoke tests | 25 | 40 |
| Benchmark tests | 7 | 17 |
| Test lines | ~25,000 | ~28,000 |
| Coverage | ~85% (estimated) | >90% |

---

*Roadmap v1.0 — Issued by Lead Programmer — 2026-04-26*
*All subsequent work follows the AIV Framework v3.0 process.*
