"""Visual fingerprint extraction for action memory.

Computes a perceptual hash of a cropped screenshot region so we can
recognize the same visual element even after minor layout changes.
Uses the existing verification hasher when available, with a lightweight
fallback using Pillow directly.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_visual_fingerprint(
    image_bytes: bytes,
    *,
    hash_size: int = 8,
) -> str:
    """Compute a perceptual hash fingerprint from image bytes.

    Returns a hex string representing the dHash of the image.
    Falls back to a raw SHA-256 if Pillow is unavailable.
    """
    try:
        from PIL import Image
    except ImportError:
        # No Pillow — raw hash as fallback
        return hashlib.sha256(image_bytes).hexdigest()[:16]

    try:
        img = Image.open(_BytesIO(image_bytes))
        return _dhash(img, hash_size)
    except Exception:
        logger.debug("Failed to compute visual fingerprint, using raw hash")
        return hashlib.sha256(image_bytes).hexdigest()[:16]


def fingerprint_distance(a: str, b: str) -> float:
    """Normalized Hamming distance between two hex fingerprints.

    Returns 0.0 for identical, 1.0 for completely different.
    Handles hex strings of different lengths gracefully.
    """
    if a == b:
        return 0.0
    if len(a) != len(b):
        # Different hash types — use string similarity
        min_len = min(len(a), len(b))
        matches = sum(1 for i in range(min_len) if a[i] == b[i])
        return 1.0 - (matches / max(len(a), len(b)))

    # Convert hex to integer and compute Hamming distance
    try:
        a_int = int(a, 16)
        b_int = int(b, 16)
        hamming = bin(a_int ^ b_int).count("1")
        return hamming / (len(a) * 4)  # Each hex char = 4 bits
    except ValueError:
        # Fallback for non-hex strings
        matches = sum(1 for x, y in zip(a, b, strict=False) if x == y)
        return 1.0 - (matches / len(a))


def crop_fingerprint(
    screenshot: bytes,
    bbox: tuple[float, float, float, float],
    viewport_size: tuple[int, int],
    *,
    padding: int = 8,
) -> str | None:
    """Crop a region from a screenshot and compute its fingerprint.

    Args:
        screenshot: Full screenshot PNG bytes.
        bbox: (x1, y1, x2, y2) pixel coordinates.
        viewport_size: (width, height) of the viewport.
        padding: Extra pixels around the bbox for context.

    Returns:
        Hex fingerprint string, or None if cropping fails.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        img = Image.open(_BytesIO(screenshot))
        x1, y1, x2, y2 = bbox

        # Apply padding, clamped to image bounds
        x1 = max(0, int(x1) - padding)
        y1 = max(0, int(y1) - padding)
        x2 = min(img.width, int(x2) + padding)
        y2 = min(img.height, int(y2) + padding)

        if x2 <= x1 or y2 <= y1:
            return None

        crop = img.crop((x1, y1, x2, y2))
        return _dhash(crop, hash_size=8)
    except Exception:
        logger.debug("Failed to crop fingerprint")
        return None


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _dhash(img: Image.Image, hash_size: int = 8) -> str:
    """Compute difference hash (dHash) — direction-aware perceptual hash.

    1. Resize to (hash_size+1, hash_size)
    2. Compare adjacent pixels horizontally
    3. Build bit vector
    4. Return as hex string
    """
    try:
        # Convert to grayscale and resize
        gray = img.convert("L")
        resized = gray.resize((hash_size + 1, hash_size))

        # Compute difference hash
        pixels = list(resized.getdata())
        bits = 0
        for row in range(hash_size):
            for col in range(hash_size):
                left = pixels[row * (hash_size + 1) + col]
                right = pixels[row * (hash_size + 1) + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)

        return f"{bits:0{hash_size * hash_size // 4}x}"
    except Exception:
        # Fallback: raw hash of resized image data
        gray = img.convert("L").resize((hash_size, hash_size))
        data = list(gray.getdata())
        raw = ",".join(str(p) for p in data)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# Lazy import helper
class _BytesIO:
    """Standalone BytesIO to avoid top-level io import overhead."""

    _BytesIO: type | None = None

    def __init__(self, data: bytes):
        if self._BytesIO is None:
            from io import BytesIO
            _BytesIO._BytesIO = BytesIO
        self._buf = self._BytesIO(data)

    def __getattr__(self, name: str):
        return getattr(self._buf, name)
