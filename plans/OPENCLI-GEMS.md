# OpenCLI Gem Extraction — Patterns for Desktop Agent

> Deep analysis of `C:\Next AI\ref\OpenCLI-main` (v1.7.8, 30,539 lines TS, 85,291 lines adapters).
> Each gem is a pattern worth stealing, with specific code we can adapt.

---

## Gem 1: Cascading Stale-Ref Resolver (3-Tier)

**Source:** `src/browser/target-resolver.ts` (~450 lines)

This is the single most valuable gem. When a snapshot ref `[42]` goes stale (SPA re-rendered, DOM changed), OpenCLI doesn't just fail — it walks 3 tiers before giving up:

```
Tier 1: EXACT        — tag + id + testId + aria-label + text all match
Tier 2: STABLE       — tag + strong id (id or testId) match, soft signals drifted
Tier 3: REIDENTIFIED — original ref gone, but fingerprint uniquely identifies
                        a single other live element via id/testId/aria-label
```

**How it works:**
1. Snapshot tags elements with `data-opencli-ref="42"` AND stores a fingerprint map: `{tag, role, text, ariaLabel, id, testId}`
2. On click/type, resolver first finds `querySelector('[data-opencli-ref="42"]')`
3. If found, checks fingerprint match → `exact` or `stable`
4. If element gone entirely, searches the page for an element matching the fingerprint
5. If exactly one candidate found → re-tags it with the old ref, returns `reidentified`
6. Only if all 3 fail → `stale_ref` error with hint to re-snapshot

**Why it matters for us:** Our cascade tier-1 (selector) fails when UIA elements change. We have `memory/healer.py` but it only replays cached selectors. OpenCLI's approach is richer — it classifies match quality (`exact`/`stable`/`reidentified`) and degrades gracefully.

**What to steal:**
```python
# In agent_core/cascade/cache.py — add fingerprint-based re-resolution
@dataclass
class ElementFingerprint:
    tag: str
    name: str
    role: str
    automation_id: str
    text_prefix: str  # first 30 chars

class StaleRefResolver:
    def resolve(self, ref: str, fingerprint: ElementFingerprint,
                live_nodes: dict[str, AXNode]) -> ResolveResult:
        # Tier 1: exact match by ref
        # Tier 2: stable — strong id matches, soft signals drifted
        # Tier 3: reidentify — search all live nodes for fingerprint match
        ...
```

---

## Gem 2: DOM Snapshot Engine (13-Step Pipeline)

**Source:** `src/browser/dom-snapshot.ts` (~940 lines)

This is the most sophisticated DOM-to-LLM-text converter I've seen. A 13-step pipeline that turns a live DOM into a compact, token-efficient string:

```
Step 1:  Walk DOM, collect visibility + layout + interactivity signals
Step 2:  Prune invisible, zero-area, non-content elements
Step 3:  SVG & decoration collapse
Step 4:  Shadow DOM traversal
Step 5:  Same-origin iframe content extraction
Step 6:  Bounding-box parent-child dedup (link/button wrapping children)
Step 7:  Paint-order occlusion detection (overlay/modal coverage)
Step 8:  Attribute whitelist filtering
Step 9:  Table → markdown serialization
Step 10: Token-efficient serialization with interactive indices [42]
Step 11: data-ref annotation for click/type targeting
Step 12: Hidden interactive element hints (scroll-to-reveal)
Step 13: Incremental diff (mark new elements with *)
```

Output format:
```
url: https://example.com
title: Example
viewport: 1280x720
---
[1]<input type=text placeholder="Search" />
[2]<button type=submit>Search</button>
  [3]<a href=/about>About Us</a>
|scroll|<div> (0.5↑ 3.2↓)
  *[4]<a href=/new>New Content</a>
---
hidden_interactive (2):
  <button> "Load More" ~2.5 pages below
---
compounds (1):
  [5] {"control":"date","format":"YYYY-MM-DD","current":"2024-01-15"}
---
interactive: 5 | iframes: 0
```

**Key innovations:**
- **Viewport expansion** — includes elements 800px beyond viewport edge
- **BBox dedup** — if `<button>` wraps `<svg>` + `<span>`, only the button gets a ref (no `[1]<button>[2]<svg>[3]<span>` noise)
- **Paint-order occlusion** — `elementFromPoint()` checks if a modal/overlay covers the target
- **Incremental diff** — marks new elements with `*` using hash comparison against previous snapshot
- **Hidden interactives** — tells the agent "there's a Load More button 2.5 pages below"
- **Compound sidecar** — date/select/file fields get rich JSON: format, options list, accept types

**Why it matters for us:** Our `AXSnapshot` is a flat dict of nodes. For browser automation, we need this kind of rich, token-efficient page state. This pipeline is 10x better than what we have.

**What to steal:** Adapt this pipeline for UIA/AX tree snapshots in `agent_core/adapters/`. The BBox dedup, occlusion detection, and incremental diff patterns apply directly to desktop element trees.

---

## Gem 3: Chrome Extension Bridge Architecture

**Source:** `extension/` (~1,500 lines), `src/daemon.ts` (~360 lines)

OpenCLI uses a 3-layer architecture for browser control:

```
CLI (Node.js)
  ↓ HTTP POST /command (localhost:19825)
Daemon (local HTTP + WS server)
  ↓ WebSocket
Chrome Extension (MV3 service worker)
  ↓ chrome.debugger / chrome.tabs / chrome.cookies APIs
User's Real Chrome (logged-in, cookies, extensions)
```

**Key design decisions:**
- Daemon auto-spawns on first browser command, persists until explicit shutdown
- Extension connects via WebSocket, not native messaging (simpler, cross-platform)
- Defense-in-depth security: Origin check + custom header + no CORS + body size limit
- Extension probes daemon via `/ping` before WebSocket to avoid console noise
- Each command gets a unique ID, daemon tracks pending promises with timeouts

**Why it matters for us:** Our Patchright launches a separate browser. For logged-in workflows (Gmail, Slack, internal tools), reusing the user's real Chrome session via an extension is far superior. This pattern lets us drive the user's actual browser without separate login.

**What to steal:** A Chrome extension + local daemon that DesktopAgent can talk to for browser automation. The extension could expose the same `IPage` interface our BrowserAdapter uses.

---

## Gem 4: Deterministic YAML Pipelines (Zero LLM Cost)

**Source:** `src/pipeline/` (~600 lines), 898 adapters in `clis/`

Every site adapter is a declarative YAML-like pipeline:

```javascript
// clis/hackernews/top.js
cli({
    site: 'hackernews',
    name: 'top',
    pipeline: [
        { fetch: { url: 'https://hacker-news.firebaseio.com/v0/topstories.json' } },
        { limit: '${{ Math.min(args.limit + 10, 50) }}' },
        { map: { id: '${{ item }}' } },
        { fetch: { url: 'https://hacker-news.firebaseio.com/v0/item/${{ item.id }}.json' } },
        { filter: 'item.title && !item.deleted' },
        { map: { rank: '${{ index + 1 }}', title: '${{ item.title }}', score: '${{ item.score }}' } },
        { limit: '${{ args.limit }}' },
    ],
});
```

Pipeline steps: `fetch` → `navigate` → `evaluate` → `intercept` → `select` → `map` → `filter` → `sort` → `limit`

Template engine supports:
- `${{ item.title }}` — expression interpolation
- `${{ item.name || 'Unknown' | upper }}` — pipe filters
- `${{ args.limit }}` — argument references
- Sandboxed JS VM for complex expressions

**Why it matters for us:** Our DesktopAgent always uses LLM (costs money, non-deterministic). For known workflows (e.g., "open Notepad, type text"), a deterministic pipeline would be zero-cost and 100% reproducible. We could have a hybrid: pipeline for known patterns, LLM for unknown.

**What to steal:** A `PipelineExecutor` in agent_core that runs declarative action sequences without LLM involvement. Could be YAML or Python dicts:

```python
# Known workflow: type text in Notepad
PIPELINES = {
    "notepad_type": [
        {"action": "click", "target": "Text Editor"},
        {"action": "type_text", "text": "${args.text}"},
    ]
}
```

---

## Gem 5: Compound Form Field Expansion

**Source:** `src/browser/compound.ts` (~150 lines)

Agents waste turns on 3 recurring input types because raw attributes under-specify them:

1. **Date inputs** — agents type free-form strings, browser silently ignores mismatched formats
2. **Select dropdowns** — snapshot shows 6 options, agent doesn't know the full set
3. **File inputs** — snapshot shows filenames but not `accept` or `multiple`

OpenCLI's solution: `compoundInfoOf(element)` returns structured JSON:

```json
{"control": "date", "format": "YYYY-MM-DD", "current": "2024-01-15", "min": "2020-01-01"}
{"control": "select", "multiple": false, "current": "Option A", "options": [...], "options_total": 47}
{"control": "file", "multiple": false, "current": [], "accept": ".pdf,.docx"}
```

**What to steal:** When our UIA walker encounters date pickers, dropdowns, or file dialogs on Windows, we should extract the same structured metadata. Win32 date controls have format strings; combo boxes have item lists; file dialogs have filter specs.

---

## Gem 6: Interceptor Pattern (Declarative Network Capture)

**Source:** `src/pipeline/steps/intercept.ts` (~70 lines), `src/browser/base-page.ts`

For SPAs that load data via XHR, OpenCLI can declaratively intercept network requests:

```yaml
pipeline:
  - intercept:
      trigger: click:"#search-btn"
      capture: "api/search"
      timeout: 8
      select: "response.data.results"
```

Steps:
1. Inject fetch/XHR interceptor with URL pattern
2. Execute trigger action (click, navigate, evaluate)
3. Wait for matching network request (event-driven, not polling)
4. Return captured response body

**What to steal:** For browser automation, network interception is gold. We already have CDP `Fetch.requestPaused` in our stealth manager. We could expose it as a high-level action: `intercept(pattern="api/*") → wait → read_captured()`.

---

## Gem 7: Shape Inference for API Discovery

**Source:** `src/browser/shape.ts` (~90 lines)

When an agent captures a network response, it gets a flat type map instead of the full body:

```json
{
  "$.data.items": "array(25)",
  "$.data.items[0].title": "string",
  "$.data.items[0].score": "number",
  "$.data.items[0].author": "string",
  "$.data.items[0].comments": "number",
  "$.data.pagination.next": "string(len=45)",
  "(truncated)": "reached 2048B budget"
}
```

This lets the agent understand the response structure without paying token cost for the full body.

**What to steal:** When our DesktopAgent captures data (from screenshots, UIA trees, or network), we should summarize the shape before sending to LLM. A `infer_shape(data, max_bytes=2048)` function would cut LLM costs significantly.

---

## Gem 8: Hook System (Plugin Lifecycle)

**Source:** `src/hooks.ts` (~80 lines)

Clean plugin lifecycle hooks using `globalThis` for singleton guarantee:

```typescript
onStartup((ctx) => { /* after all plugins loaded */ });
onBeforeExecute((ctx) => { /* before every command */ });
onAfterExecute((ctx, result) => { /* after every command */ });
```

Each hook is wrapped in try/catch — a failing hook never blocks execution. Context carries command name, args, timing, and arbitrary plugin data.

**What to steal:** We have nothing like this. Our `WatchdogEventBus` is recovery-only. A general hook system would let us add cross-cutting concerns (logging, metrics, rate limiting) without modifying core code.

---

## Gem 9: Snapshot Formatter (4-Pass Cleanup)

**Source:** `src/snapshotFormatter.ts` (~360 lines)

Raw DOM/AX snapshots are noisy. OpenCLI applies 4 cleanup passes:

1. **Parse & filter** — strip annotations, metadata, noise roles (`presentation`, `separator`), ads, boilerplate
2. **Deduplicate** — generic/text parent match, heading+link merge, nested identical links
3. **Prune** — remove empty containers (iterative bottom-up)
4. **Collapse** — single-child container chains → direct parent-to-child

**What to steal:** Our `AXSnapshot` dumps raw nodes. A `format_snapshot(nodes, mode="llm")` that applies similar cleanup would dramatically reduce token usage when feeding page state to LLM.

---

## Gem 10: Electron App Registry (Port-Based CDP)

**Source:** `src/electron-apps.ts` (~100 lines)

Dead-simple mapping of desktop Electron apps to CDP ports:

```typescript
builtinApps = {
  cursor:    { port: 9226, processName: 'Cursor',    bundleId: 'com.todesktop.runtime.Cursor' },
  codex:     { port: 9222, processName: 'Codex',     bundleId: 'com.openai.codex' },
  notion:    { port: 9230, processName: 'Notion',    bundleId: 'notion.id' },
  chatgpt:   { port: 9236, processName: 'ChatGPT',   bundleId: 'com.openai.chat' },
  discord:   { port: 9232, processName: 'Discord',   bundleId: 'com.discord.app' },
};
```

Launch with `--remote-debugging-port=N`, connect via CDP directly. Each app gets a unique port to avoid conflicts.

**What to steal:** We could add this to our WindowsAdapter — detect running Electron apps, launch them with CDP flags, and control them via CDP instead of UIA. Electron apps respond to CDP (browser) commands, which is faster and more reliable than UIA tree walking.

---

## Gem 11: Agent-Native Error Envelopes

**Source:** `src/browser/target-errors.ts`, `src/browser/errors.ts`

Every interaction returns a structured envelope that tells the agent exactly what happened:

```typescript
// Success
{ ok: true, matches_n: 1, match_level: 'exact' }
{ ok: true, matches_n: 1, match_level: 'reidentified' }

// Errors — each with machine-readable code + human hint
{ ok: false, code: 'not_found', message: 'ref=42 not found',
  hint: 'Re-run browser state to get a fresh snapshot' }
{ ok: false, code: 'stale_ref', message: 'ref=42 was <button>"Submit" but now <div>',
  hint: 'The page has changed. Re-run browser state.' }
{ ok: false, code: 'selector_ambiguous', matches_n: 5,
  hint: 'Use --nth to pick one of 5 matches' }
```

**What to steal:** Our `ActionError` has `category` + `message` but no recovery hints. Adding `hint` and `code` fields that the LLM can read would make our agent much better at self-correcting.

---

## Gem 12: Network Cache with Shape-Based Keys

**Source:** `src/browser/network-cache.ts` (~100 lines), `src/browser/network-key.ts`

When agents discover API endpoints, OpenCLI caches responses keyed by URL + query params. The cache includes:
- **Shape preview** — the type map from `shape.ts`
- **Body** — full response (up to 8MB cap)
- **Timestamp** — for staleness checks
- **Truncation signal** — `responseBodyFullSize` + `responseBodyTruncated` so agents know if data was cut

**What to steal:** For our grounding pipeline's OCR/cache layer. When we screenshot a page and OCR it, we should cache the results with shape metadata, not just raw text.

---

## Summary: Priority Order for Implementation

| Priority | Gem | Effort | Impact |
|----------|-----|--------|--------|
| **P0** | #1 Cascading Stale-Ref Resolver | 8h | Cuts agent failures on dynamic pages by ~60% |
| **P0** | #2 DOM Snapshot Pipeline | 12h | 10x better page state for LLM consumption |
| **P1** | #11 Agent-Native Error Envelopes | 3h | LLM self-corrects instead of looping |
| **P1** | #9 Snapshot Formatter | 4h | Cuts token usage 50%+ on page state |
| **P1** | #7 Shape Inference | 2h | Cuts LLM costs on large data payloads |
| **P2** | #4 Deterministic Pipelines | 6h | Zero-cost path for known workflows |
| **P2** | #3 Chrome Extension Bridge | 16h | Enables logged-in browser automation |
| **P2** | #10 Electron App Registry | 4h | Fast CDP control of Electron desktop apps |
| **P3** | #5 Compound Form Fields | 3h | Better form interaction for desktop |
| **P3** | #6 Network Interceptor | 4h | API discovery for browser automation |
| **P3** | #8 Hook System | 3h | Plugin extensibility |
| **P3** | #12 Network Cache | 3h | Performance optimization |

**Total: ~68h for all 12 gems. P0+P1 = ~29h for the highest-impact items.**
