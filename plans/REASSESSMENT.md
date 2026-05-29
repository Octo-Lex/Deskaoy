# Super Browser — Honest Re-Assessment

## What the Project Says It Is

From the Master Plan:

> **Build a cross-platform desktop agent that automates any application on any OS
> through natural language instructions.**

12-week roadmap, 6 phases:
0. Fix critical gaps (done)
1. Extract agent-core (surface-agnostic engine)
2. Visual grounding pipeline (YOLO, Florence-2, OCR)
3. Platform adapters (macOS/Windows/Linux)
4. Multi-app orchestration (HostAgent + AppAgent)
5. Memory & learning
6. Hardening

## What Actually Exists Right Now

A **browser automation library**. It can:
- Launch headless Chromium via Patchright
- Click, type, fill, scroll via 3-tier cascade (selector → coordinate → vision)
- Take screenshots and compute perceptual hashes
- Capture AX trees for element discovery
- Save/load checkpoints for recovery
- Truncate large outputs to protect context windows
- Track token budgets

It has 88 source files, 1147 tests, and works reliably on real websites.

## What's Missing for the Stated Vision

The Master Plan says "cross-platform desktop agent." The code is 100% browser-only:

| The Plan Says | What Exists |
|--------------|-------------|
| 4-tier cascade (API → AX → XY → VLM) | 3-tier cascade (selector → XY → VLM) |
| Works on any app (Calculator, TextEdit, Excel) | Only works on web pages |
| YOLO + Florence-2 + OCR visual grounding | Cloud VLM providers (Anthropic, OpenAI) with fallback |
| macOS AXUIElement, Windows UIA, Linux AT-SPI | Patchright CDP only |
| HostAgent/AppAgent multi-app orchestration | SubagentDelegator (parallel browser tasks only) |
| Trajectory mining, document RAG | Skill registry (basic save/search) |
| Desktop isolation, virtual desktop | Nothing |

**80% of the stated vision is unbuilt.** What exists is Phase 0 (bug fixes) complete plus a solid browser layer.

## Who Is the User?

This is the question that matters. The Master Plan never names one.

Three possible users, with very different needs:

### User A: Developer building a browser agent
- Wants: `pip install super-browser`, point it at a URL, give instructions
- Needs: Reliable browser control, LLM integration, cost management
- Doesn't need: Desktop automation, platform adapters, multi-app orchestration
- **This user is served today** (minus the LLM integration — `act()` requires wiring your own client)

### User B: Developer building a desktop automation agent
- Wants: Same cascade engine, but for native apps on macOS/Windows/Linux
- Needs: Platform adapters, accessibility APIs, window management, desktop isolation
- Doesn't need: Stealth stack, anti-bot, CDP
- **This user is not served today** — agent-core extraction + platform adapters are prerequisite

### User C: End user who wants to say "book me a flight"
- Wants: Natural language → autonomous task completion
- Needs: Full stack, plus UI, plus error recovery, plus trust/safety
- **This user is 6+ months away**

## The Honest Question

The project is at an inflection point. The bug fixes are done. The browser automation works. The next step in the Master Plan is **Phase 1: Extract agent-core** — 2 weeks of refactoring to separate the surface-agnostic 80% from the browser-specific 20%.

**But who asked for that?**

The extraction only matters if:
1. Someone is going to build a macOS/Windows/Linux adapter (Phase 3)
2. Someone is going to build the visual grounding pipeline with local models (Phase 2)
3. Someone needs to use the cascade/recovery/verification without a browser

If the answer is "we're building a browser automation library," then the extraction is premature optimization and the right next step is making the browser experience better (real LLM wiring, better error messages, more robust selectors).

If the answer is "we're building a desktop agent," then extraction is the right next step and the browser work becomes just one adapter among many.

## My Read

The codebase tells a different story than the plan. The code is:
- **Thorough** — 12 subsystems, 88 source files, carefully typed
- **Well-analyzed** — 15 reference projects studied, 12 GAP specs written
- **Browser-specific** — every line assumes Patchright/CDP
- **Not integrated** — subsystems exist but don't talk to each other without manual wiring
- **Missing the main loop** — `act()` requires an LLM client that nobody has wired

The Master Plan's architecture is sound. The phased approach is correct. But we've spent all our time on Phase 0 (fixing bugs in existing code) and haven't started Phase 1 (the actual architectural transformation).

**The most valuable thing to build next is not more fixes — it's making the system do something useful autonomously.** That means wiring an LLM and running `act()` on a real task. That's the proof point that determines whether the architecture works.
