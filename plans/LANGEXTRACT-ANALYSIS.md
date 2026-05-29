# LangExtract Reference Analysis

> **Repo:** `C:\Next AI\ref\langextract-main`
> **What:** Google's library for extracting structured data from text using LLMs
> **By:** Akshay Goel (Google) — Apache-2.0
> **Version:** v1.2.1, requires Python 3.10+
> **Size:** ~15 modules in `langextract/` + `langextract/core/` + `langextract/providers/`

---

## Architecture Overview

```
lx.extract(text, prompt, examples, model_id)
    │
    ├── Prompt Validation (pv.validate_prompt_alignment)
    │   └── Checks example extraction_text aligns to example text
    │
    ├── Model Factory (factory.create_model)
    │   ├── Router resolves model_id → provider class
    │   ├── Schema generated from examples (BaseSchema.from_examples)
    │   └── Provider instantiated (Gemini, OpenAI, Ollama, custom)
    │
    ├── Annotator (annotation.Annotator)
    │   ├── Chunking: Document → TextChunks (max_char_buffer)
    │   ├── Prompting: QAPromptGenerator builds few-shot prompts
    │   ├── Inference: BaseLanguageModel.infer(batch_prompts)
    │   ├── Resolver: Parse JSON/YAML → Extraction objects
    │   ├── Alignment: Map extractions back to source text (exact → fuzzy)
    │   └── Multi-pass: extraction_passes > 1 → merge non-overlapping
    │
    └── AnnotatedDocument(text, extractions, char_intervals)
```

---

## Key Patterns

### 1. Source Grounding (Character-Level Alignment)

Every extraction maps back to its **exact position** in the source text:

```python
extraction.char_interval  # CharInterval(start_pos=42, end_pos=56)
```

**Alignment algorithm** (4-tier fallback):
1. **MATCH_EXACT** — Token-level exact match via `difflib`
2. **MATCH_LESSER** — Partial exact match (extraction longer than matched text)
3. **MATCH_FUZZY** — LCS (Longest Common Subsequence) window matching, threshold ≥ 0.75
4. **`None`** — Unverifiable (hallucinated or from few-shot example, not source)

This is the core value prop: **trust but verify** — every LLM output is checked against the source.

### 2. Schema-Driven Structured Output

`BaseSchema.from_examples(examples)` generates a schema from few-shot examples:
- **GeminiSchema**: Full JSON Schema constraint for controlled generation
- **FormatModeSchema**: Generic JSON/YAML format enforcement (for Ollama/OpenAI)
- Schema validates against `FormatHandler` to ensure compatibility
- `requires_raw_output` property determines fence behavior

### 3. Provider Plugin System

```python
@router.register(r"gpt-4", r"gpt-5", priority=0)
class OpenAILanguageModel(BaseLanguageModel):
    @classmethod
    def get_schema_class(cls):
        return FormatModeSchema
    def infer(self, batch_prompts, **kwargs):
        ...
```

- **Lazy loading**: Providers register patterns + loader functions; class imported only on first use
- **Priority**: Higher priority wins on model_id collision
- **Entry points**: `pyproject.toml` declares `langextract.providers` entry points for pip-installable plugins
- **Resolution**: `router.resolve("gpt-4o")` → pattern match → lazy import → class

### 4. Multi-Pass Extraction for Recall

```python
result = lx.extract(..., extraction_passes=3)
```

- Pass 1: Standard extraction
- Pass 2+: Re-process same chunks, merge **non-overlapping** new extractions
- Overlap detection uses `CharInterval` intersection
- First-pass wins on conflicts
- Cost: N passes = N× token processing

### 5. Context Window for Cross-Chunk Coreference

```python
result = lx.extract(..., context_window_chars=200)
```

- `ContextAwarePromptBuilder` prepends N chars from previous chunk
- Resolves pronouns ("She", "it") across chunk boundaries
- Critical for medical/long-document extraction

### 6. Streaming Pipeline Architecture

`Annotator.annotate_documents()` is a **generator**:
- Documents → chunks → batches → prompts → inference → resolve → align → yield
- Peak memory bounded: completed documents emitted immediately
- Progress bar via `tqdm`

### 7. Prompt Validation (Pre-Flight)

`validate_prompt_alignment(examples, aligner, policy)` runs before extraction:
- Checks each example's `extraction_text` can be found in its `text`
- Reports `MATCH_FUZZY`, `MATCH_LESSER`, `FAILED` alignments
- Three modes: `OFF`, `WARNING` (default), `ERROR` (fail-fast)
- Prevents garbage-in-garbage-out at dev time

### 8. Error Hierarchy

```
LangExtractError (base)
├── InferenceError
│   ├── InferenceConfigError    (missing API key, bad model_id)
│   └── InferenceRuntimeError   (API failure, network)
│       └── .original, .provider fields
├── InferenceOutputError        (no scored outputs)
├── InvalidDocumentError        (duplicate IDs)
├── ProviderError               (backend-specific)
├── SchemaError                 (schema validation)
└── FormatError
    └── FormatParseError        (JSON/YAML parse failure)
```

### 9. Visualization System

`lx.visualize(annotated_doc_or_jsonl)` generates self-contained HTML:
- Animated highlighting of extractions in source text
- Color-coded by `extraction_class`
- Interactive: click to inspect attributes
- Works in Jupyter (returns `HTML` object) or standalone (write to file)
- Handles thousands of entities from full novels

### 10. Testing Patterns

- `pyproject.toml` markers: `live_api`, `requires_pip`, `integration`
- `tox.ini` matrix: Python 3.10 + 3.11, pylint + pytest
- `import-linter` enforces dependency boundaries:
  - `providers` must not import `inference`
  - `core` must not import `providers` or high-level modules
- PEP 562 lazy loading for ergonomic public API

---

## What Desktop-Agent Should Adopt

### High Priority (Directly Applicable)

| Pattern | LangExtract | Desktop-Agent Equivalent |
|---------|-------------|-------------------------|
| **Source grounding with char intervals** | Every extraction has `CharInterval` | Desktop actions should record which UI element they targeted + verification the element still exists. Our `AXNode` + `Detection` types already carry bounding boxes — wire them into `ActionResult.data` as `target_bounds`, `target_text` |
| **Multi-pass extraction for recall** | `extraction_passes=3` | Multi-pass automate: if first automation pass misses elements, re-scan and retry. Maps to our `AgentLoop` max_steps but with **intent-level** retry, not just step-level |
| **Pre-flight validation** | `validate_prompt_alignment()` | Before executing an automate task, validate the instruction against available actions (our `ToolRegistry` already does this partially). Could add: verify target surface is reachable before first action |
| **Streaming generator pipeline** | `annotate_documents()` yields results | Our `AgentLoop.run()` already returns `LoopResult` — could yield intermediate results for long-running automations |
| **Provider plugin system** | `@router.register(pattern, target, priority)` | Our `SurfaceAdapter` is close but not plugin-discoverable. Add entry-point-based adapter discovery |
| **Error hierarchy with structured fields** | `InferenceRuntimeError(original=, provider=)` | Our `ActionError` has `code`, `hint`, `candidates` — add `original` exception chain and `provider`/`surface` field |

### Medium Priority (Good Patterns)

| Pattern | What to Take |
|---------|-------------|
| **Schema from examples** | Generate action schemas from recorded `ActionEvidence` — auto-suggest parameters for similar tasks |
| **Context window across chunks** | In multi-step automate, carry context from previous steps (screenshot + snapshot) into next step's prompt |
| **Prompt validation levels** | Add OFF/WARNING/ERROR validation levels for action instructions before execution |
| **Fence + format handling** | Abstract output format handling (JSON/YAML/structured) for LLM responses — our `SimpleLLMClient` does JSON extraction but could be more robust |
| **Visualization** | Generate HTML report of automate session: screenshots with bounding boxes, action timeline, confidence graph |

### Lower Priority (Nice to Have)

| Pattern | What to Take |
|---------|-------------|
| **Lazy module loading** | PEP 562 for `agent_core.__init__` — currently imports everything eagerly |
| **Benchmark framework** | `benchmarks/` with config, plotting, fuzzy matching metrics |
| **Entry point plugins** | `pyproject.toml` entry points for adapter discovery |
| **Import linting** | `import-linter` to enforce our `agent_core` / `super_browser` boundary |

---

## Architecture Comparison

| Aspect | LangExtract | Desktop-Agent |
|--------|-------------|---------------|
| **Core loop** | chunk → prompt → infer → resolve → align | snapshot → plan → act → verify → learn |
| **Input** | Unstructured text | Desktop surface (UI tree + screenshot) |
| **Output** | Structured extractions with source positions | Actions executed with verification |
| **Grounding** | CharInterval in source text | Bounding box + AXNode in UI tree |
| **LLM usage** | Central — does the extraction | Planning only (action selection) |
| **Multi-pass** | Recall improvement | Error recovery |
| **Chunking** | Fixed char buffer + sentence boundaries | N/A (single surface at a time) |
| **Parallelism** | batch_length × max_workers | Sequential actions (desktop is single-threaded) |
| **Provider model** | Plugin registry with lazy loading | Adapter protocol with explicit init |

---

## Key Insight

LangExtract's most transferable pattern is **grounding with structured fallback**:

1. **Exact match** (highest confidence)
2. **Partial match** (acceptable with flag)
3. **Fuzzy match** (LCS-based, threshold-gated)
4. **No match → filtered out** (unverifiable = untrusted)

Desktop-Agent should apply this same 4-tier pattern to **action result verification**:
1. **Structural match** — AXNode still exists with same properties (0.95+ confidence)
2. **Visual match** — Same bounding box, similar appearance (0.80+ confidence)
3. **Text match** — Same text content found somewhere (0.60+ confidence)
4. **No verification** — Action executed blindly (untrusted, flag for review)

This directly maps to our existing `GroundingPipeline` tiers (structural → visual → text) but applied to **post-action verification**, not just pre-action targeting.
