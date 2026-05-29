# BATCH-27 BLUEPRINT — Desktop Observation Pipeline

**Batch:**                BATCH-27
**Version:**              v0.34.0 → v0.35.0
**Cycle Type:**           STANDARD
**AIV Framework:**        v5.2
**Date:**                 2026-05-10
**Lead:**                 Craft Agent (Lead Override per §5.3)
**Blueprint Version:**    1.0

---

## 1. Batch Identity

**Batch Name:**           Desktop Observation Pipeline
**Strategic Bet:**        Unified capture+detect+OCR+annotate pipeline shared across CLI/MCP/REST — Peekaboo's single observation pipeline pattern adapted for Desktop-Agent's modular architecture.
**Priority:**             HIGH

**Context:**              Peekaboo has a unified observation pipeline where capture → analysis → OCR → annotation happens in a single composable chain. Desktop-Agent currently has fragmented observation: `DesktopObservation` dataclass, `GroundingPipeline` for visual analysis, `UIAWalker` for AX trees, but no unified orchestrator that chains them together. This batch creates `ObservationPipeline` — a single entry point that produces rich `DesktopObservation` objects with all layers populated.

---

## 2. Scope

### In Scope
- `ObservationPipeline` class: unified capture → AX walk → OCR → detect → fuse → annotate chain
- Composable steps: each step optional, configurable, pluggable
- Pipeline presets: `quick` (screenshot+AX only), `standard` (screenshot+AX+OCR), `full` (all steps)
- Integration with existing `DesktopObservation`, `GroundingPipeline`, `UIAWalker`, `SnapshotStore`
- CLI `observe` command that outputs rich observations
- MCP tool exposure: `observe` tool
- REST endpoint: `POST /observe`

### Out of Scope
- New ML models or OCR engines
- macOS/Linux adapter changes
- Changes to existing `GroundingPipeline` internals

---

## 3. Hard Boundaries

| ID  | Constraint |
|-----|-----------|
| HB-01 | Must degrade gracefully — every step optional, pipeline works with zero ML deps |
| HB-02 | All 3,109 baseline tests must pass |
| HB-03 | No new required dependencies |
| HB-04 | Pipeline must complete in <5s for `quick` preset on any machine |

---

## 4. Data Models

```python
@dataclass
class ObservationConfig:
    """Configuration for an observation pipeline run."""
    preset: str = "standard"              # quick, standard, full
    include_screenshot: bool = True
    include_ax_tree: bool = True
    include_ocr: bool = True
    include_detection: bool = False       # ML-heavy, off by default
    include_annotation: bool = False      # SoM rendering, off by default
    save_snapshot: bool = False           # Persist to SnapshotStore
    target_window: Optional[str] = None   # Window title filter
    ocr_engine: str = "builtin"           # builtin, paddleocr, tesseract
    max_elements: int = 500               # Limit AX tree size

@dataclass
class ObservationResult:
    """Rich result from an observation pipeline run."""
    observation: DesktopObservation
    elements: list[dict]                  # Detected/OCR'd elements
    element_count: int
    elapsed_ms: float
    steps_completed: list[str]            # Which steps ran
    steps_skipped: list[str]             # Which steps were skipped
    snapshot_id: Optional[str] = None     # If saved to SnapshotStore
    annotated_screenshot: Optional[bytes] = None  # SoM-rendered PNG
```

---

## 5. Task Sequence

**Sequencing:** SEQUENTIAL (T01 → T02 → T03 → T04)

### TASK-01: ObservationPipeline Core

**Description:** Create the pipeline class with composable steps.

**New Module:** `src/agent_core/observation_pipeline.py`

**Pipeline Steps (in order):**
| Step | Description | Preset Availability |
|------|-------------|-------------------|
| `capture` | Screenshot via SurfaceAdapter | quick/standard/full |
| `ax_walk` | Accessibility tree via UIAWalker | quick/standard/full |
| `ocr` | Text extraction via builtin/PaddleOCR | standard/full |
| `detect` | Element detection via GroundingPipeline | full |
| `fuse` | Combine AX + detection + OCR results | standard/full |
| `annotate` | SoM rendering on screenshot | full |
| `snapshot` | Persist to SnapshotStore | optional |

**Methods:**
| Method | Description |
|--------|-------------|
| `observe(config)` | Run full pipeline with config, return ObservationResult |
| `observe_quick()` | Shortcut: screenshot + AX only |
| `observe_standard()` | Shortcut: screenshot + AX + OCR |
| `observe_full()` | Shortcut: all steps |
| `list_presets()` | Return available presets and their configs |

**Files:**
- NEW: `src/agent_core/observation_pipeline.py`
- MOD: `src/agent_core/observation.py` — Add `ObservationConfig`, `ObservationResult`

**Expected Tests:** 15

---

### TASK-02: OCR Step Enhancement

**Description:** Enhance the OCR step to use multiple backends and fuse results into the observation.

**New Module:** `src/agent_core/observation_ocr.py`

**Methods:**
| Method | Description |
|--------|-------------|
| `extract_text(image_bytes)` | Run OCR, return list of text regions |
| `merge_with_ax(ax_elements, ocr_results)` | Merge OCR text into AX elements |
| `get_available_engines()` | List available OCR backends |

**Backends:**
1. `builtin` — Always available, extracts text from AX tree `name`/`value` properties
2. `paddleocr` — Optional, uses PaddleOCR for image-based text extraction
3. `tesseract` — Optional, uses pytesseract for image-based text extraction

**Files:**
- NEW: `src/agent_core/observation_ocr.py`
- MOD: `src/agent_core/observation_pipeline.py` — Wire OCR step

**Expected Tests:** 10

---

### TASK-03: Transport Integration (CLI + MCP + REST)

**Description:** Expose the observation pipeline across all 3 transport layers.

**CLI Command:**
```
desktop-agent observe [--preset quick|standard|full] [--json] [--save] [--annotate]
desktop-agent observe --list-presets
```

**MCP Tool:**
```json
{"name": "observe", "description": "Capture desktop observation", "parameters": {"preset": "standard", "save": false}}
```

**REST Endpoint:**
```
POST /observe
Body: {"preset": "standard", "save": false, "annotate": false}
Response: ObservationResult as JSON
```

**Files:**
- MOD: `src/agent_core/cli/main.py` — `observe` command
- MOD: `src/agent_core/transport/mcp_server.py` — `observe` tool
- MOD: `src/agent_core/transport/rest_server.py` — `POST /observe`

**Expected Tests:** 10

---

### TASK-04: Version Bump + Integration Tests

**Description:** Version bump, full suite validation, integration test.

**Files:**
- MOD: `src/agent_core/cli/version.py` — 0.34.0 → 0.35.0
- MOD: `pyproject.toml` — version bump
- NEW: `tests/test_observation/test_pipeline.py` — All tests in one file

**Expected Tests:** 5 (version + preset validation + full pipeline + CLI + transport)

**Total:** 15 + 10 + 10 + 5 = **40 new tests**

---

## 6. Acceptance Criteria

| AC ID | Criterion | Task |
|-------|-----------|------|
| AC-01-01 | ObservationPipeline runs all 7 steps in order | TASK-01 |
| AC-01-02 | Each step optional — pipeline works with zero deps | TASK-01 |
| AC-01-03 | 3 presets produce correct configs | TASK-01 |
| AC-02-01 | OCR builtin backend extracts text from AX tree | TASK-02 |
| AC-02-02 | OCR merges text results with AX elements | TASK-02 |
| AC-03-01 | CLI `observe` command functional | TASK-03 |
| AC-03-02 | MCP `observe` tool exposed | TASK-03 |
| AC-03-03 | REST `POST /observe` endpoint functional | TASK-03 |
| AC-04-01 | Version is 0.35.0 | TASK-04 |
| AC-04-02 | Full suite passes: 3,149 (3,109 + 40) | TASK-04 |

---

## 7. Baseline Metrics

| Metric | Value |
|--------|-------|
| Version at Batch start:       | v0.34.0 |
| Test count at Batch start:    | 3,109 passing |
| Expected delta (all Tasks):   | +40 new tests |
| Expected total at Batch close:| 3,149 |

---

## 8. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| OCR backends unavailable | LOW | builtin always works (AX tree text) |
| Pipeline too slow for real-time | MEDIUM | `quick` preset skips OCR/detection |
| GroundingPipeline import fails | LOW | Lazy import with try/except |

---

## 9. Reviewer Notes

Reviewer Report ID:
Review Cycle:
Lead Decision:            [ ] ACCEPT   [ ] ACCEPT WITH MODIFICATIONS   [ ] REJECT

Blueprint Version after response:
Lead Sign:                Craft Agent — 2026-05-10
