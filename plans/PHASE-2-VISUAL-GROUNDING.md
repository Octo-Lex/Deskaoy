# Phase 2: Visual Grounding Pipeline — Implementation Plan

> Build the local ML pipeline that detects, captions, and annotates UI elements
> without cloud VLM calls. Based on **OmniParser v2** (Microsoft Research).

## Why OmniParser v2

OmniParser v2 is the proven visual grounding pipeline from Microsoft Research:
- **39.5% on ScreenSpot Pro** (SOTA for GUI grounding as of 2025)
- **Top-ranked on Windows Agent Arena**
- Weights: ~300MB total (YOLO ~100MB + Florence-2 ~200MB)
- License: YOLO detector = AGPL, Florence-2 = MIT
- Runs on GPU (~50ms) or CPU (~300ms) — zero cost per call

This is what Agent-S uses to achieve 72.6% on OSWorld (first above human performance).

## What We're NOT Building

The plan originally specified "YOLO26n" — **this model does not exist**. It was a fabricated name.
The correct detection model is the YOLO-based detector from OmniParser v2 weights.

## Architecture

```
Screenshot (bytes)
    │
    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  AX/UIA Tree  │     │  YOLO Detect  │     │  PaddleOCR   │
│  (from Tier 1)│     │  (OmniParser) │     │  (text)      │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                     │
       │     ┌──────────────┴─────────────────────┘
       │     ▼
       │  ┌──────────────┐
       │  │  Fusion Engine │  IoU dedup, structural-as-truth priority
       │  └──────┬───────┘
       │         │
       │    ┌────┴────┐
       │    ▼         ▼
       │  Text      Non-text elements
       │  elements    │
       │    │         ▼
       │    │    ┌──────────────┐
       │    │    │ Florence-2    │  Caption icons/buttons
       │    │    │ Captioning    │  "Close button", "Submit"
       │    │    └──────┬───────┘
       │    │           │
       ▼    ▼           ▼
    ┌──────────────────────────┐
    │     FusedElement[]       │
    │  role, label, bounds,    │
    │  source, confidence      │
    └──────────┬───────────────┘
               ▼
    ┌──────────────────────────┐
    │   Set-of-Mark Renderer   │  Color-coded role-based boxes
    └──────────────────────────┘
```

## Implementation

### Week 1 — Detection + Fusion

#### 1.1 YOLO Detector (`agent_core/grounding/detector.py`)

```python
from agent_core.grounding.types import BBox, Detection
from ultralytics import YOLO

class OmniParserDetector:
    """YOLO-based UI element detection using OmniParser v2 weights."""

    def __init__(self, weights_path: str = "weights/icon_detect/model.pt"):
        self._model = YOLO(weights_path, task="detect")

    async def detect(self, screenshot: bytes, *, confidence: float = 0.3) -> list[Detection]:
        """Detect interactive elements in a screenshot.

        Uses tiled inference for high-res screens:
          - Split into 4 tiles (640x640, 50% overlap)
          - Run YOLO on each tile
          - Merge results with IoU-based dedup
        """
        ...
```

Weight files (downloaded from HuggingFace `microsoft/OmniParser-v2.0`):
- `weights/icon_detect/model.pt` — YOLO detector (~100MB)
- `weights/icon_detect/model.yaml` — architecture config
- `weights/icon_detect/train_args.yaml` — training config

#### 1.2 OCR Engine (`agent_core/grounding/ocr.py`)

```python
from paddleocr import PaddleOCR
from agent_core.grounding.types import BBox, Detection

class PaddleOCREngine:
    """Text extraction via PaddleOCR."""

    def __init__(self, lang: str = "en"):
        self._ocr = PaddleOCR(lang=lang, show_log=False)

    async def detect_text(self, screenshot: bytes) -> list[Detection]:
        """Extract text bounding boxes from screenshot."""
        ...
```

#### 1.3 Fusion Engine (`agent_core/grounding/fusion.py`)

```python
from agent_core.grounding.types import FusedElement, BBox

class FusionEngine:
    """Merge structural (AX) + visual (YOLO) + text (OCR) detections.

    Priority: structural-as-truth
      - AX elements are authoritative (they come from the OS)
      - YOLO boxes that overlap AX elements are deduped (AX wins)
      - OCR text boxes deduped against both AX and YOLO
      - Remaining YOLO-only boxes = elements the AX tree missed
    """

    def fuse(
        self,
        structural: list[FusedElement],  # from AX/UIA tree
        visual: list[Detection],          # from YOLO
        text: list[Detection],            # from OCR
        *,
        iou_threshold: float = 0.5,
    ) -> list[FusedElement]:
        ...
```

### Week 2 — Captioning + Anchoring

#### 2.1 Florence-2 Captioner (`agent_core/grounding/captioner.py`)

```python
from transformers import AutoModelForCausalLM, AutoProcessor

class FlorenceCaptioner:
    """Icon/element captioning using Florence-2 (OmniParser v2 weights).

    MIT license. Generates functional descriptions:
      - "Close window button"
      - "Submit form"
      - "Navigation menu hamburger icon"
    """

    def __init__(self, weights_path: str = "weights/icon_caption_florence"):
        self._processor = AutoProcessor.from_pretrained(weights_path, trust_remote_code=True)
        self._model = AutoModelForCausalLM.from_pretrained(weights_path, trust_remote_code=True)

    async def caption(self, cropped_image: bytes) -> str:
        """Generate a functional description for a cropped UI element."""
        ...
```

Weight files (from HuggingFace `microsoft/OmniParser-v2.0`):
- `weights/icon_caption_florence/model.safetensors` (~200MB)
- `weights/icon_caption_florence/config.json`
- `weights/icon_caption_florence/generation_config.json`

#### 2.2 Anchor IDs (`agent_core/grounding/anchor.py`)

Stable element identifiers that persist across frames:
```python
def compute_anchor(element: FusedElement) -> str:
    """Hash(role + label + relative_position) → stable ID.

    Same element at same position with same role gets same anchor.
    Survives scrolling (position normalized to viewport).
    """
    ...
```

#### 2.3 Set-of-Mark Renderer (`agent_core/grounding/som_renderer.py`)

Annotates screenshots with color-coded bounding boxes:
- **Green** = structural (AX/UIA) match
- **Blue** = text (OCR) match
- **Orange** = visual-only (YOLO, no structural match)
- Labels show element role + anchor ID

#### 2.4 Cross-Frame Tracking (`agent_core/grounding/tracker.py`)

Track elements across consecutive screenshots:
```python
@dataclass
class FrameDelta:
    stable: list[FusedElement]      # same anchor in both frames
    appeared: list[FusedElement]    # new anchors
    disappeared: list[FusedElement] # missing anchors
```

## New Files

```
agent_core/grounding/
├── __init__.py
├── types.py              BBox, Detection, FusedElement, ElementRole, AnchorMap
├── detector.py           OmniParserDetector (YOLO)
├── captioner.py          FlorenceCaptioner (Florence-2)
├── ocr.py                PaddleOCREngine
├── fusion.py             FusionEngine (merge + dedup)
├── anchor.py             Stable anchor computation
├── tracker.py            Cross-frame element tracking
├── som_renderer.py       Set-of-Mark annotation
└── pipeline.py           GroundingPipeline orchestrator

agent_core/grounding/adapters/
├── omniparser.py         Download + cache OmniParser v2 weights
└── weight_manager.py     HuggingFace weight management

weights/                  (gitignored, ~300MB total)
├── icon_detect/
│   ├── model.pt          YOLO detector weights (~100MB)
│   ├── model.yaml        Architecture config
│   └── train_args.yaml   Training config
└── icon_caption_florence/
    ├── model.safetensors  Florence-2 weights (~200MB)
    ├── config.json
    └── generation_config.json

tests/test_grounding/
├── test_detector.py      YOLO detection on test screenshots
├── test_captioner.py     Florence-2 captioning
├── test_ocr.py           PaddleOCR text extraction
├── test_fusion.py        Merge + dedup logic
├── test_anchor.py        Anchor stability
├── test_tracker.py       Cross-frame tracking
├── test_som_renderer.py  Annotation rendering
└── test_pipeline.py      Full pipeline integration
```

## New Dependencies

```
# pyproject.toml [project.optional-dependencies]
grounding = [
    "ultralytics>=8.0",      # YOLO inference
    "transformers>=4.40",    # Florence-2 inference
    "paddleocr>=2.7",        # OCR
    "paddlepaddle>=2.5",     # PaddleOCR backend
    "torch>=2.0",            # PyTorch (CPU or CUDA)
]
```

## Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Detection recall (interactive elements) | >80% | Test screenshots across native, Electron, browser |
| Detection latency (GPU) | <50ms | Single 1080p screenshot |
| Detection latency (CPU) | <300ms | Single 1080p screenshot |
| Captioning latency (GPU) | <30ms per element | Single icon crop |
| Full pipeline (GPU) | <100ms | Detect + OCR + fuse + caption |
| Full pipeline (CPU) | <500ms | Detect + OCR + fuse + caption |
| Cost | $0 | All local inference |

## Gate Criteria

1. Grounding pipeline detects **80%+ interactive elements** on test screenshots across 3 app types (native macOS, Electron, browser)
2. Fusion correctly deduplicates AX + YOLO + OCR overlaps
3. Anchors are stable across consecutive frames (same element → same anchor)
4. Pipeline works without network access (all weights local)
5. All new tests pass
6. Existing 1141 tests still pass

## Effort Estimate

| Task | Time | Notes |
|------|------|-------|
| YOLO detector integration | 8 hrs | Tiled inference, weight management |
| PaddleOCR integration | 4 hrs | Text extraction, bounding box normalization |
| Fusion engine | 6 hrs | IoU dedup, structural priority |
| Florence-2 captioner | 6 hrs | Cropping, caption generation |
| Anchors + tracking | 4 hrs | Stable IDs, frame deltas |
| SoM renderer | 3 hrs | PIL annotation drawing |
| Pipeline orchestrator | 4 hrs | Wire everything together |
| Tests | 8 hrs | 8 test files, mocked + real |
| **Total** | **~43 hrs** | |

## How This Fits the Cascade

```
Before Phase 2:
  Tier 1: AX tree → resolve target → done (85% of cases)
  Tier 2: Coordinate → click at (x,y) → done (10% of cases)
  Tier 3: Cloud VLM → $0.01-0.05/call (5% of cases)

After Phase 2:
  Tier 1: AX tree → resolve target → done (85% of cases)
  Tier 2: Coordinate → click at (x,y) → done (10% of cases)
  Tier 3a: Local grounding (OmniParser) → free, 100ms (4% of cases)
  Tier 3b: Cloud VLM → $0.01-0.05/call (1% of cases, last resort)
```

Cloud VLM usage drops from 5% to ~1%. Cost per action drops by 5x.
