# Reference Tour — Inspiration Analysis (April 2026)

> Scanned 17 repos, deep-dived 6. Key patterns applicable to Desktop Agent.

---

## 1. det-acp (Deterministic Agent Control Protocol) ⭐⭐⭐

**Repo:** `deterministic-agent-control-protocol-main`
**What:** Governance gateway for AI agents — every action bounded, auditable, reversible.

### Patterns We Should Adopt

| Pattern | What It Does | Our Gap | Effort |
|---------|-------------|---------|--------|
| **Evidence Ledger** | Append-only JSONL with SHA-256 hash chaining. If it's not in the ledger, it didn't happen. | Our `TraceBridge` is in-memory only — no persistence, no tamper evidence | 3h |
| **Policy Self-Evolution** | When an action is denied, a suggestion engine proposes a policy change. User approves → policy YAML is updated automatically. | Our `PolicyBridge` is static — deny is final, no learning | 4h |
| **Session Budgets** | max_actions, max_denials, rate_limit (max_per_minute), escalation (after N actions → human check-in) | We have `ActionRateGovernor` but no session-level budgets or escalation | 2h |
| **Gate System** | Three verdicts: allow / deny / gate (human approval required). Our policy has DENY/ASK/ALLOW but no structured gate with timeout. | Our ASK policy effect works but has no approval workflow | 3h |
| **Compensation Plans** | Auto-generated rollback plans for every executed action | Our undo is best-effort, no structured compensation plan | 4h |

### Key Files
- `src/ledger/ledger.ts` — SHA-256 chained JSONL ledger (~200 lines)
- `src/evolution/policy-evolution.ts` — Self-evolving policy system
- `src/engine/gate.ts` — Three-verdict gate (allow/deny/gate)
- `src/policy/evaluator.ts` — Policy YAML evaluation
- `src/rollback/manager.ts` — Compensation plan manager

---

## 2. MIRIX (Multi-Agent Memory System) ⭐⭐

**Repo:** `MIRIX-main`
**What:** Personal AI with 6 specialized memory types + screen observation.

### Patterns We Should Adopt

| Pattern | What It Does | Our Gap | Effort |
|---------|-------------|---------|--------|
| **6-Layer Memory** | Core (identity), Episodic (events), Semantic (facts), Procedural (skills), Resource (files), Knowledge Vault (long-term) | Our `ActionMemory` is single-tier (intent→selector mapping) | 8h |
| **Screen Activity Tracking** | Continuous visual capture → consolidated into structured memories | No screen observation / proactive monitoring | 6h |
| **Dedicated Memory Agents** | Each memory type has its own agent managing consolidation, retrieval, and pruning | Single memory store, no consolidation agent | 4h |

### What We Have That's Better
- Our `ActionMemory` feedback loop (WRITE/READ/HEAL) is more targeted for desktop actions
- Our grounding verification is more evidence-based than MIRIX's screen observation

---

## 3. Pocket Agent ⭐⭐

**Repo:** `pocket-agent-main`
**What:** Menu-bar AI with persistent memory, routines, browser automation.

### Patterns We Should Adopt

| Pattern | What It Does | Our Gap | Effort |
|---------|-------------|---------|--------|
| **Scheduled Routines** | "Every morning at 8am, check calendar and give briefing" — full agent executions on cron | No scheduling/cron system | 3h |
| **Fact Extraction** | Actively extracts facts about user (projects, people, preferences) into structured knowledge | Our memory is action-focused, no user modeling | 4h |
| **Soul System** | Learns communication style, response preferences, boundaries | No user preference adaptation | 5h |
| **Session Isolation** | Up to 5 threads with isolated memory | Single session model | 2h |

### What We Have That's Better
- Our 3-tier cascade is far more robust than Pocket Agent's browser automation
- Our DAG orchestration is more sophisticated

---

## 4. Agent Orchestrator ⭐⭐

**Repo:** `agent-orchestrator-main`
**What:** Parallel AI coding agents in git worktrees, auto-fix CI, address reviews.

### Patterns We Should Adopt

| Pattern | What It Does | Our Gap | Effort |
|---------|-------------|---------|--------|
| **Git Worktree Isolation** | Each agent gets its own worktree — zero cross-contamination | Our AppAgents share one surface — no real isolation | 6h |
| **CI Auto-Heal** | Agent detects CI failure → fixes → pushes → re-tests | Our `RecoveryBridge` has circuit breaker but no auto-heal loop | 5h |
| **Dashboard Supervision** | Web dashboard showing all parallel agents, their status, and human gate points | No web UI / dashboard | 12h |
| **Tracker-Agnostic** | Works with GitHub, Linear, Jira via adapters | We're tracker-specific (AI-OS only) | 3h |

### What We Have That's Better
- Our DAG executor handles arbitrary dependencies, not just PR-based workflows

---

## 5. Goose ⭐

**Repo:** `goose-main`
**What:** Rust-based desktop AI agent — CLI, desktop app, API. 70+ MCP extensions.

### Patterns We Should Adopt

| Pattern | What It Does | Our Gap | Effort |
|---------|-------------|---------|--------|
| **Rust Core** | Native performance for desktop interactions | Python overhead for real-time input | Would need rewrite |
| **Custom Distros** | Preconfigured providers, extensions, branding — like Linux distros | Single monolithic package | 3h |
| **ACP (Agent Communication Protocol)** | Use existing Claude/ChatGPT/Gemini subscriptions directly | Requires separate API keys | 5h |

### What We Have That's Better
- Our visual grounding pipeline (YOLO + Florence-2 + OCR) is far more sophisticated
- Our AI-OS contract compliance is enterprise-grade vs. Goose's standalone model

---

## 6. browser-use Skills System ⭐

**Repo:** `browser-use-main`
**What:** Browser automation with a skill definition system.

### Patterns We Should Adopt

| Pattern | What It Does | Our Gap | Effort |
|---------|-------------|---------|--------|
| **SKILL.md Definitions** | Skills defined in markdown with YAML frontmatter (name, description, allowed-tools) | Our pipelines are Python-only, no declarative definition | 2h |
| **Skill CLI** | `browser-use skill install <url>` — install skills from URLs | No skill installation mechanism | 3h |

---

## Recommended Next Steps (Priority Order)

| # | Pattern | Source | Impact | Effort | Fits In |
|---|---------|--------|--------|--------|---------|
| **1** | Evidence Ledger | det-acp | Audit trail for every desktop action | 3h | v0.13 |
| **2** | Session Budgets + Escalation | det-acp | Prevent runaway agents at session level | 2h | v0.13 |
| **3** | Policy Self-Evolution | det-acp | Learn from denials, don't just block | 4h | v0.13 |
| **4** | Scheduled Routines | Pocket Agent | Cron-like automation ("every morning…") | 3h | v0.14 |
| **5** | Compensation Plans | det-acp | Structured undo with generated rollback steps | 4h | v0.14 |
| **6** | Fact Extraction | Pocket Agent | Build user model from interactions | 4h | v0.15 |
| **7** | SKILL.md Definitions | browser-use | Declarative skill definitions in markdown | 2h | v0.15 |

### Top Recommendation: det-acp Adoption (v0.13)

The **Evidence Ledger** + **Session Budgets** + **Policy Self-Evolution** from det-acp would give us:
- Tamper-evident audit trail (currently missing)
- Session-level action budgets with escalation (we only have per-action rate limiting)
- Policy that learns from denials instead of being static

This maps to ~9h of work and would bring the Desktop Agent to production-grade governance.
