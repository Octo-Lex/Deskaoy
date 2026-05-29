# MAKE IT POWERFUL — Batch Blueprint Sequence

**Program:** Desktop-Agent v1.0 → v1.3  
**Lead:** Lead Programmer  
**Framework:** AIV v5.3  
**Date Issued:** 2026-05-11  
**Test Baseline:** 3,703 tests (3,703 passed, 1 flaky, 62 skipped)

---

## STRATEGIC NARRATIVE

Desktop-Agent is complete as a library. It sees the screen, acts on it, verifies results, and recovers from failures. But it's **slow** — every call cold-starts the agent, re-initializes the surface, re-discovers the UI tree. And it's **blind to change** — it can't wait for things to happen, can't annotate what it sees for VLMs, can't keep state warm between calls.

Three capabilities transform it from a tool you call into an agent that works alongside you:

| Capability | Transformation | Speedup |
|-----------|---------------|---------|
| **Client-Daemon Architecture** | Persistent background process, zero cold starts | 10-40× |
| **Annotated Screenshots** | VLM can see labeled bounding boxes on every element | Qualitative |
| **Rich Wait Predicates** | Wait for windows, text, processes, UI state changes | Reliability |

The sequence is ordered by **risk-first**: the hardest, most architecturally impactful work comes first. If Client-Daemon fails, the other two are still useful but the product is fundamentally limited. If Annotated Screenshots fail, we still have a fast agent.

---

## BATCH SEQUENCE OVERVIEW

### BATCH-37: Client-Daemon Architecture (Risk Sprint)
**Goal:** Persistent background daemon that keeps surface adapter initialized and accepts commands over IPC. Zero cold starts for repeated calls.
**Hypothesis:** A Unix-domain-socket / named-pipe daemon can keep a DesktopAgent instance warm and serve multiple clients with <5ms overhead per call vs ~2s cold start.
**Risk:** COM threading model on Windows may prevent sharing UIA objects across threads. Named-pipe security model on Windows may be fragile.
**Cycle:** STANDARD (3 Tasks: daemon core, IPC protocol, client library)

### BATCH-38: Daemon Health & Lifecycle
**Goal:** Daemon auto-restart, health monitoring, graceful shutdown, stale connection cleanup. Production-hardened daemon process.
**Hypothesis:** Watchdog + heartbeat pattern keeps the daemon alive for days without manual intervention.
**Risk:** UIAutomation handles leaking over long sessions (COM reference accumulation).
**Cycle:** STANDARD (2 Tasks: health watchdog, lifecycle management)

### BATCH-39: Rich Wait Predicates
**Goal:** Composable wait predicates — wait_for_window(title), wait_for_text(text), wait_for_element(role, name), wait_for_process(name), wait_for_idle(timeout). All usable from any transport.
**Hypothesis:** A polling-based predicate system with configurable intervals eliminates 80% of timing-based flakiness in automation scripts.
**Risk:** None — pure polling layer on existing adapters.
**Cycle:** STANDARD (3 Tasks: predicate types, adapter integration, transport exposure)

### BATCH-40: Annotated Screenshots (SoM Enhancement)
**Goal:** Production-grade Set-of-Mark rendering — labeled bounding boxes on every interactable element, rendered onto the screenshot as a PNG. Callable from any transport with a single `annotate` parameter.
**Hypothesis:** Existing `som_renderer` + `grounding/pipeline` provide 70% of the infrastructure. The remaining 30% is making it fast (<100ms) and complete (all roles labeled).
**Risk:** Rendering performance on high-DPI screens with 500+ elements.
**Cycle:** STANDARD (2 Tasks: SoM renderer enhancement, pipeline integration)

### BATCH-41: VLM Vision Integration
**Goal:** Connect annotated screenshots to VLM providers (GPT-4o, Gemini) via OpenLimit. Desktop-Agent can use vision as a fallback tier when accessibility tree is insufficient.
**Hypothesis:** VLM as tier-4 (after UIA → AX/AT-SPI → pyautogui) catches the 5-10% of elements invisible to accessibility.
**Risk:** Latency (VLM call adds 1-3s per step) and cost ($0.01-0.03 per screenshot analysis).
**Cycle:** STANDARD (2 Tasks: VLM client, tiered grounding fallback)

### BATCH-42: Performance Baseline & Benchmarks
**Goal:** Establish performance baselines for cold-start vs daemon, with/without wait predicates, with/without VLM. CI benchmark suite.
**Hypothesis:** Daemon mode shows ≥10× improvement in multi-call scenarios. Wait predicates reduce flaky-step rate from ~15% to <2%.
**Risk:** Benchmark variance on shared CI runners.
**Cycle:** SIMPLIFIED (1 Task: benchmark suite + baseline capture)

### BATCH-43: Integration Test Suite (Power Features)
**Goal:** End-to-end tests combining daemon + wait + screenshots. Notepad automation that clicks, waits for dialog, types, waits for save, verifies content. Full happy path.
**Hypothesis:** Three features together produce a reliable, fast automation experience that works without any `time.sleep()` hacks.
**Risk:** Test environment variability (different Windows builds, DPI settings).
**Cycle:** STANDARD (2 Tasks: integration test suite, CI integration)

### BATCH-44: Version Bump & Release Prep (v1.1.0)
**Goal:** Version bump to v1.1.0. Update pyproject.toml, CHANGELOG, README with new features. PyPI release checklist. Optional `pip install desktop-agent[daemon]` extra.
**Hypothesis:** New daemon mode is the headline feature that makes v1.1.0 a meaningful release.
**Risk:** None — documentation and packaging only.
**Cycle:** SIMPLIFIED (1 Task: version bump + changelog + README)

---

## BATCH SEQUENCE DEPENDENCY MAP

```
BATCH-37 (Daemon Core)
    │
    ├──→ BATCH-38 (Daemon Health)
    │
    ├──→ BATCH-39 (Wait Predicates) ──→ BATCH-43 (Integration Tests)
    │                                         │
    └──→ BATCH-40 (SoM Enhancement)           │
         │                                    │
         └──→ BATCH-41 (VLM Integration) ────→┘
              │
              └──→ BATCH-42 (Benchmarks)
                    │
                    └──→ BATCH-44 (v1.1.0 Release)
```

BATCH-39, BATCH-40, and BATCH-38 can run in parallel after BATCH-37.
BATCH-41 depends on BATCH-40 (annotated screenshots feed VLM).
BATCH-43 depends on BATCH-37, BATCH-39, and BATCH-40 (all three features).
BATCH-42 depends on all feature batches (needs them to exist to benchmark).
BATCH-44 is the release gate — depends on everything.

---

## TOTAL EFFORT ESTIMATE

| Batch | Tasks | Estimated Tests | Risk |
|-------|-------|----------------|------|
| BATCH-37 | 3 | +80 | HIGH (COM threading) |
| BATCH-38 | 2 | +35 | MEDIUM (memory leaks) |
| BATCH-39 | 3 | +55 | LOW |
| BATCH-40 | 2 | +30 | LOW-MEDIUM (perf) |
| BATCH-41 | 2 | +25 | MEDIUM (cost/latency) |
| BATCH-42 | 1 | +15 | LOW |
| BATCH-43 | 2 | +40 | MEDIUM (env variance) |
| BATCH-44 | 1 | +5 | LOW |
| **Total** | **16** | **+285** | |

**Target:** 3,703 → ~3,988 tests. Version v1.0.0 → v1.1.0.
