# Phase 2: Visual Grounding Pipeline — Revised Implementation Plan

> Build the local ML pipeline (OmniParser v2 + Florence-2 + PaddleOCR) that
> detects, captions, and annotates UI elements — feeding real confidence
> scores into DesktopAgent without cloud VLM calls.

## What Changed Since the Original Plan

The original Phase 2 plan was aspirational — 43 hours, no integration path.
Now we have:
- `DesktopAgent` with `AgentResult.confidence` (currently heuristic: 0.9 on success)
- `BrowserAdapter` proving DesktopAgent → SurfaceAdapter → real surface
- `VisionController` with cloud VLM cascade (Anthropic/OpenAI/UITARS)
- `OCRGrounding` using pytesseract (weak — no bounding boxes, word-level only)
- `SurfaceAdapter` protocol with `snapshot()` returning `AXSnapshot`

The grounding pipeline plugs into **Tier 3 of the cascade** and feeds
**Confidence.factors** with visual evidence scores.

## Architecture (Where Grounding Fits)

```
SurfaceAdapter.click("Submit button")
  │
  ▼
MultimodalController._cascade()
  │
  ├─ Tier 1: Selector "#submit"     → AX resolve     (85%)
  ├─ Tier 2: Coordinate (x, y)      → CDP click      (10%)
  └─ Tier 3: Vision cascade
       │
       ├─ 3a: GroundingPipeline     ← NEW (local, free, ~100ms)
       │     YOLO detect → OCR text → Fuse → Florence caption
       │     Returns: element coords + confidence
       │
       └─ 3b: Cloud VLM             ← EXISTING ($0.01-0.05, ~2s)
              Anthropic/OpenAI/UITARS
```

GroundingPipeline becomes a **VisionProvider** — drop-in for the existing
provider protocol. No changes to MultimodalController cascade logic.

## Revised Scope (Incremental, Testable Slices)

### Slice 1: Types + Contracts (no ML deps)
**New file:** `agent_core/grounding/types.py`

Grounding-specific types that are importable without torch/ultralytics:
- `BBox(x1, y1, x2, y2)` — axis-aligned bounding box with IoU
- `Detection(bbox, confidence, label, source)` — single detected element
- `FusedElement(bbox, role, label, text, source, confidence, anchor_id)`
- `ElementRole` enum: BUTTON, INPUT, LINK, ICON, TEXT, IMAGE, CONTAINER, OTHER
- `DetectionSource` enum: STRUCTURAL, VISUAL_YOLO, VISUAL_OCR, FUSED
- `FrameDelta(stable, appeared, disappeared)` — cross-frame tracking
- `GroundingResult(elements, screenshot_annotated, duration_ms, source_counts)`

Tests: Pure dataclass tests (BBox IoU, FusedElement equality, etc.)

### Slice 2: Fusion Engine (no ML deps)
**New file:** `agent_core/grounding/fusion.py`

IoU-based dedup and merge of detections from multiple sources:
- `fuse(structural, visual, text, iou_threshold=0.5) → list[FusedElement]`
- Structural-as-truth priority (AX > YOLO > OCR)
- Non-max suppression for overlapping same-source detections
- Text label assignment from OCR for YOLO-only boxes

Tests: 15+ unit tests with synthetic detections, edge cases (empty inputs,
perfect overlaps, multi-source overlaps, zero-size boxes)

### Slice 3: Anchor IDs + Cross-Frame Tracking (no ML deps)
**New files:** `agent_core/grounding/anchor.py`, `agent_core/grounding/tracker.py`

- `compute_anchor(element, viewport_size) → str` — stable hash from role+label+normalized-position
- `track_frames(prev_elements, curr_elements) → FrameDelta` — match by anchor

Tests: Deterministic anchors, stability across slight position shifts,
frame delta classification (appeared/disappeared/stable)

### Slice 4: YOLO Detector (ultralytics dep)
**New file:** `agent_core/grounding/detector.py`

- `OmniParserDetector.detect(screenshot_bytes) → list[Detection]`
- Tiled inference for >640px screenshots (2x2 grid, 50% overlap, merge)
- Confidence threshold filtering (default 0.25)
- Lazy model loading (load on first call, not import)
- Weight download from HuggingFace `microsoft/OmniParser-v2.0` on first use

Tests: Mocked (mock YOLO model, verify tiled split + merge logic),
skipped-integration (real weights if available)

### Slice 5: PaddleOCR Engine (paddleocr dep)
**New file:** `agent_core/grounding/paddle_ocr.py`

Replaces the existing `vision/ocr.py` (pytesseract) with PaddleOCR:
- `PaddleOCREngine.detect_text(screenshot_bytes) → list[Detection]`
- Lazy initialization (PaddleOCR takes ~2s to init)
- Word-level + line-level bounding boxes
- Language auto-detect

Tests: Mocked (verify bounding box normalization),
skipped-integration (real PaddleOCR if installed)

### Slice 6: Florence-2 Captioner (transformers dep)
**New file:** `agent_core/grounding/captioner.py`

- `FlorenceCaptioner.caption(cropped_image_bytes) → str`
- Crops detected elements and generates functional descriptions
- Batch captioning (process multiple crops in one forward pass)
- Lazy model loading

Tests: Mocked (verify crop + prompt logic),
skipped-integration (real Florence-2 if installed)

### Slice 7: Set-of-Mark Renderer (PIL only, no ML deps)
**New file:** `agent_core/grounding/som_renderer.py`

- `render_som(screenshot_bytes, elements) → bytes` (annotated PNG)
- Color-coded boxes by source: green=structural, blue=OCR, orange=visual-only
- Labels: element index + role + truncated label
- Numbered overlays for click targeting

Tests: Render with synthetic elements, verify output is valid PNG,
verify colors/labels

### Slice 8: GroundingPipeline Orchestrator (wires everything)
**New file:** `agent_core/grounding/pipeline.py`

The main entry point:
```python
class GroundingPipeline(VisionProvider):
    """Drop-in VisionProvider that runs local grounding instead of cloud VLM."""
    
    async def locate(self, request: VisionRequest) -> VisionResponse:
        # 1. Run YOLO detection
        # 2. Run PaddleOCR
        # 3. Run AX snapshot pre-check (if provided)
        # 4. Fuse all detections
        # 5. Match description against fused elements
        # 6. Return VisionResponse with confidence
```

Also:
- `detect_all(screenshot_bytes) → GroundingResult` — full pipeline for debugging
- `confidence_for(elements, description) → float` — match scoring
- Registers as `"grounding"` provider in VisionProviderFactory

Tests: Full pipeline with mocked sub-components,
integration test if weights available

### Slice 9: Confidence Feed into DesktopAgent
**Modified file:** `agent_core/desktop_agent.py`

Update `_confidence_from_action()`:
```python
def _confidence_from_action(self, result: ActionResult) -> Confidence:
    if result.ok:
        # If grounding data is attached, use visual confidence
        visual_conf = result.data.get("visual_confidence") if result.data else None
        if visual_conf is not None:
            return Confidence(score=visual_conf, reason="Visual grounding verified",
                           factors={"source": "grounding_pipeline"})
        return Confidence(score=0.9, reason="Action completed successfully")
    ...
```

Tests: Verify confidence reflects grounding scores when available

### Slice 10: Weight Management
**New file:** `agent_core/grounding/weight_manager.py`

- `ensure_weights() → dict[str, Path]` — download from HuggingFace if missing
- Cache in `~/.cache/desktop-agent/weights/`
- Progress bar for downloads
- SHA256 verification
- `weights/` in `.gitignore`

Tests: Mock HuggingFace download, verify SHA256 check, verify cache hit

## File Summary

```
NEW (agent_core/grounding/):
  __init__.py               Package exports
  types.py                  BBox, Detection, FusedElement, ElementRole, etc.
  fusion.py                 IoU dedup + structural priority merge
  anchor.py                 Stable element anchor IDs
  tracker.py                Cross-frame element tracking
  detector.py               OmniParserDetector (YOLO, ultralytics)
  paddle_ocr.py             PaddleOCREngine (replaces pytesseract)
  captioner.py              FlorenceCaptioner (Florence-2, transformers)
  som_renderer.py           Set-of-Mark annotation renderer
  pipeline.py               GroundingPipeline orchestrator (VisionProvider)
  weight_manager.py         HuggingFace weight download + cache

NEW (tests/):
  test_grounding/
    __init__.py
    test_types.py           BBox IoU, dataclass validation
    test_fusion.py          Dedup, priority, edge cases
    test_anchor.py          Anchor stability
    test_tracker.py         Frame delta tracking
    test_detector.py        Tiled inference, mock YOLO
    test_paddle_ocr.py      OCR bounding boxes, mock PaddleOCR
    test_captioner.py       Crop + caption, mock Florence-2
    test_som_renderer.py    Annotation rendering
    test_pipeline.py        Full pipeline with mocked components
    test_weight_manager.py  Download, cache, SHA256

MODIFIED:
  agent_core/desktop_agent.py      Confidence from grounding (Slice 9)
  pyproject.toml                    New [grounding] optional dependency group
  .gitignore                        Add weights/ directory

UNCHANGED (grounding plugs in, doesn't modify):
  agent_core/vision/controller.py  GroundingPipeline becomes a provider option
  agent_core/vision/factory.py     GroundingProvider registered via env var
  super_browser/interaction/controller.py  Tier 3 cascade unchanged
```

## Dependency Strategy

```toml
[project.optional-dependencies]
grounding = [
    "ultralytics>=8.0",      # YOLO inference (~50MB)
    "transformers>=4.40",    # Florence-2 inference
    "paddleocr>=2.7",        # OCR (optional — fallback to pytesseract)
    "paddlepaddle>=2.5",     # PaddleOCR backend
    "torch>=2.0",            # PyTorch (CPU or CUDA)
    "accelerate>=0.20",      # Model loading optimization
]
grounding-gpu = [
    "torch>=2.0+cu121",      # CUDA-enabled PyTorch
]
```

**Grounding is optional.** The agent works perfectly with cloud VLMs.
Grounding eliminates the cost for the 4% of actions that reach Tier 3a.

`pip install super-browser[grounding]` enables local inference.

## Performance Targets

| Metric | CPU | GPU |
|--------|-----|-----|
| YOLO detection (1080p) | <300ms | <50ms |
| PaddleOCR (1080p) | <200ms | <100ms |
| Florence-2 caption (per element) | <100ms | <30ms |
| Full pipeline (detect+ocr+fuse) | <500ms | <100ms |
| Cost per call | $0 | $0 |

## Build Order & Test Gates

| Slice | Depends On | ML Deps? | Tests | Gate |
|-------|-----------|----------|-------|------|
| 1. Types | nothing | No | test_types.py | All dataclass operations correct |
| 2. Fusion | Types | No | test_fusion.py (15+ tests) | IoU dedup correct, structural priority |
| 3. Anchor+Tracker | Types | No | test_anchor.py, test_tracker.py | Anchors stable, deltas correct |
| 4. YOLO Detector | Types | Yes (ultralytics) | test_detector.py | Tiled split+merge correct |
| 5. PaddleOCR | Types | Yes (paddleocr) | test_paddle_ocr.py | BBox normalization correct |
| 6. Florence-2 | Types | Yes (transformers) | test_captioner.py | Crop+prompt correct |
| 7. SoM Renderer | Types | No (PIL only) | test_som_renderer.py | Valid PNG output |
| 8. Pipeline | 1-7 | Optional | test_pipeline.py | End-to-end with mocks |
| 9. Confidence | 8 | No | test in test_os_contract.py | DesktopAgent uses grounding confidence |
| 10. Weights | nothing | No | test_weight_manager.py | Download+cache+verify |

**Slices 1-3, 7, 10 have zero ML dependencies** — they can be built and tested
immediately without installing torch/ultralytics/paddleocr.

## Effort Estimate

| Slice | Time | Can Start Immediately? |
|-------|------|----------------------|
| 1. Types | 2 hrs | ✅ |
| 2. Fusion | 4 hrs | ✅ (after 1) |
| 3. Anchor + Tracker | 3 hrs | ✅ (after 1) |
| 4. YOLO Detector | 6 hrs | After ultralytics install |
| 5. PaddleOCR | 3 hrs | After paddleocr install |
| 6. Florence-2 | 4 hrs | After transformers install |
| 7. SoM Renderer | 2 hrs | ✅ (after 1) |
| 8. Pipeline | 4 hrs | After 1-7 |
| 9. Confidence feed | 1 hr | After 8 |
| 10. Weight manager | 2 hrs | ✅ |
| **Total** | **~31 hrs** | |

## Critical Design Decisions

1. **GroundingPipeline IS a VisionProvider** — implements the same `locate()` protocol.
   Zero changes to MultimodalController cascade. Selectable via env var
   `SB_VISION_DEFAULT_PROVIDER=grounding`.

2. **Slices 1-3, 7, 10 first** — pure Python, zero ML deps, immediate value.
   Fusion logic is the most complex piece and it needs no torch.

3. **PaddleOCR is optional** — if not installed, fall back to existing pytesseract.
   The pipeline degrades gracefully.

4. **Lazy loading everywhere** — models loaded on first `detect()` call, not at import.
   `import agent_core.grounding` should take <100ms even without torch.

5. **Weight caching in `~/.cache/`** — not in the repo. First run downloads ~300MB.
   Subsequent runs are instant.

6. **Confidence is evidence-based** — not a heuristic. Each element gets a confidence
   from its detection source (YOLO conf, OCR conf, structural=0.95). Fusion
   aggregates these into a single score.
