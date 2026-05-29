"""Florence-2 captioner — functional descriptions for UI icons/elements.

Requires: transformers (optional). Generates labels like "Close button",
"Navigation menu", "Submit form" for cropped UI elements.
"""

from __future__ import annotations

import logging
from io import BytesIO

from deskaoy.grounding.types import FusedElement

logger = logging.getLogger(__name__)

_HAS_TRANSFORMERS = False
try:
    from transformers import AutoModelForCausalLM, AutoProcessor
    _HAS_TRANSFORMERS = True
except ImportError:
    pass

# Florence-2 prompt for functional captioning
_CAPTION_PROMPT = "<CAPTION>"


class FlorenceCaptioner:
    """Icon/element captioning using Florence-2 (OmniParser v2 weights)."""

    def __init__(
        self,
        weights_path: str | None = None,
        *,
        device: str = "cpu",
    ) -> None:
        self._weights_path = weights_path or "weights/icon_caption_florence"
        self._device = device
        self._model: object | None = None
        self._processor: object | None = None

    @property
    def available(self) -> bool:
        return _HAS_TRANSFORMERS

    def _ensure_model(self) -> None:
        """Lazy-load Florence-2 on first use."""
        if self._model is not None:
            return
        if not _HAS_TRANSFORMERS:
            raise RuntimeError(
                "transformers not installed. Install with: "
                "pip install deskaoy[grounding]"
            )
        from transformers import AutoModelForCausalLM, AutoProcessor
        logger.info("Loading Florence-2 captioner from %s", self._weights_path)
        self._processor = AutoProcessor.from_pretrained(
            self._weights_path, trust_remote_code=True,
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            self._weights_path, trust_remote_code=True,
        ).to(self._device)
        self._model.eval()

    async def caption(self, cropped_image: bytes) -> str:
        """Generate a functional description for a cropped UI element."""
        if not _HAS_TRANSFORMERS:
            return ""

        self._ensure_model()

        import torch
        from PIL import Image

        img = Image.open(BytesIO(cropped_image)).convert("RGB")
        inputs = self._processor(
            text=_CAPTION_PROMPT,
            images=img,
            return_tensors="pt",
        ).to(self._device)

        with torch.no_grad():
            generated_ids = self._model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=50,
                num_beams=1,
            )

        generated_text = self._processor.batch_decode(
            generated_ids, skip_special_tokens=True,
        )[0]

        # Clean up the prompt prefix
        text = generated_text.strip()
        if text.startswith(_CAPTION_PROMPT):
            text = text[len(_CAPTION_PROMPT):].strip()

        return text

    async def caption_elements(
        self,
        screenshot: bytes,
        elements: list[FusedElement],
    ) -> list[FusedElement]:
        """Caption non-text elements that lack labels.

        Returns new FusedElements with updated labels.
        """
        if not _HAS_TRANSFORMERS:
            return elements

        from PIL import Image

        img = Image.open(BytesIO(screenshot)).convert("RGB")
        result: list[FusedElement] = []

        for el in elements:
            # Skip elements that already have good labels
            if el.text and el.label:
                result.append(el)
                continue
            # Skip text elements — they have their own text
            if el.role.value == "text" and el.text:
                result.append(el)
                continue

            # Crop the element from the screenshot
            bbox = el.bbox.clamp(img.size[0], img.size[1])
            crop = img.crop((bbox.x1, bbox.y1, bbox.x2, bbox.y2))

            # Skip tiny crops
            if crop.size[0] < 8 or crop.size[1] < 8:
                result.append(el)
                continue

            # Save crop to bytes
            buf = BytesIO()
            crop.save(buf, format="PNG")
            crop_bytes = buf.getvalue()

            caption = await self.caption(crop_bytes)
            if caption:
                result.append(FusedElement(
                    bbox=el.bbox,
                    role=el.role,
                    label=caption,
                    confidence=el.confidence,
                    source=el.source,
                    sources=el.sources,
                    text=el.text,
                    anchor_id=el.anchor_id,
                    metadata=el.metadata,
                ))
            else:
                result.append(el)

        return result
