"""Tests for visual fingerprint extraction and comparison."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

# Pillow is required for these tests
try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

from deskaoy.memory.fingerprint import (
    _dhash,
    compute_visual_fingerprint,
    crop_fingerprint,
    fingerprint_distance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(width: int = 100, height: int = 100, color: tuple = (128, 128, 128)) -> bytes:
    """Create a minimal PNG image for testing."""
    if Image is None:
        pytest.skip("Pillow not installed")

    import io

    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_gradient_png(width: int = 100, height: int = 100) -> bytes:
    """Create a gradient PNG image."""
    if Image is None:
        pytest.skip("Pillow not installed")

    import io

    img = Image.new("L", (width, height))
    for y in range(height):
        for x in range(width):
            img.putpixel((x, y), (x + y) % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# compute_visual_fingerprint
# ---------------------------------------------------------------------------


class TestComputeVisualFingerprint:
    def test_returns_hex_string(self):
        fp = compute_visual_fingerprint(_make_png())
        assert isinstance(fp, str)
        assert len(fp) > 0

    def test_deterministic(self):
        data = _make_png()
        fp1 = compute_visual_fingerprint(data)
        fp2 = compute_visual_fingerprint(data)
        assert fp1 == fp2

    def test_different_images_different_fingerprints(self):
        if Image is None:
            pytest.skip("Pillow not installed")

        import io

        # Create a clear gradient image
        img1 = Image.new("L", (100, 100))
        for y in range(100):
            for x in range(100):
                img1.putpixel((x, y), (x * 2 + y * 2) % 256)

        # Create a solid image
        img2 = Image.new("L", (100, 100), 128)

        buf1, buf2 = io.BytesIO(), io.BytesIO()
        img1.save(buf1, format="PNG")
        img2.save(buf2, format="PNG")

        fp1 = compute_visual_fingerprint(buf1.getvalue())
        fp2 = compute_visual_fingerprint(buf2.getvalue())
        distance = fingerprint_distance(fp1, fp2)
        assert distance > 0.05  # Clearly different images

    def test_similar_images_similar_fingerprints(self):
        fp1 = compute_visual_fingerprint(_make_png(color=(128, 128, 128)))
        fp2 = compute_visual_fingerprint(_make_png(color=(130, 130, 130)))
        # Very similar images should have low distance
        distance = fingerprint_distance(fp1, fp2)
        assert distance < 0.3

    def test_handles_empty_bytes(self):
        # Should not crash, should return a hash
        fp = compute_visual_fingerprint(b"not an image")
        assert isinstance(fp, str)
        assert len(fp) > 0


# ---------------------------------------------------------------------------
# fingerprint_distance
# ---------------------------------------------------------------------------


class TestFingerprintDistance:
    def test_identical(self):
        d = fingerprint_distance("abcd1234", "abcd1234")
        assert d == 0.0

    def test_different_length(self):
        d = fingerprint_distance("abc", "abcdef")
        assert 0.0 <= d <= 1.0

    def test_maximally_different(self):
        # All bits different
        d = fingerprint_distance("0000000000000000", "ffffffffffffffff")
        assert d > 0.5

    def test_symmetric(self):
        fp1 = "abcd1234567890ab"
        fp2 = "abcd1234567890ac"
        assert abs(fingerprint_distance(fp1, fp2) - fingerprint_distance(fp2, fp1)) < 0.001


# ---------------------------------------------------------------------------
# crop_fingerprint
# ---------------------------------------------------------------------------


class TestCropFingerprint:
    def test_crop_center(self):
        screenshot = _make_png(200, 200)
        fp = crop_fingerprint(
            screenshot,
            bbox=(50, 50, 150, 150),
            viewport_size=(200, 200),
        )
        assert fp is not None
        assert isinstance(fp, str)

    def test_crop_with_padding(self):
        screenshot = _make_png(200, 200)
        fp = crop_fingerprint(
            screenshot,
            bbox=(90, 90, 110, 110),
            viewport_size=(200, 200),
            padding=20,
        )
        assert fp is not None

    def test_crop_edge_bbox(self):
        screenshot = _make_png(200, 200)
        # bbox at edge with padding should clamp
        fp = crop_fingerprint(
            screenshot,
            bbox=(0, 0, 10, 10),
            viewport_size=(200, 200),
        )
        assert fp is not None

    def test_crop_invalid_bbox(self):
        screenshot = _make_png(200, 200)
        # x2 < x1 → invalid
        fp = crop_fingerprint(
            screenshot,
            bbox=(100, 100, 50, 50),
            viewport_size=(200, 200),
        )
        assert fp is None

    def test_no_pillow_returns_none(self):
        # If Pillow is available, this tests a real crop
        # If not, crop_fingerprint returns None
        if Image is None:
            fp = crop_fingerprint(b"fake", (10, 10, 50, 50), (100, 100))
            assert fp is None
        else:
            # Pillow available — test should work
            fp = crop_fingerprint(_make_png(100, 100), (10, 10, 50, 50), (100, 100))
            assert fp is not None


# ---------------------------------------------------------------------------
# _dhash
# ---------------------------------------------------------------------------


class TestDhash:
    def test_uniform_image(self):
        if Image is None:
            pytest.skip("Pillow not installed")
        img = Image.new("L", (50, 50), 128)
        h = _dhash(img)
        assert isinstance(h, str)
        assert len(h) > 0
        # Uniform image → all bits same → all 0s or all 1s depending on implementation

    def test_hash_size(self):
        if Image is None:
            pytest.skip("Pillow not installed")
        img = Image.new("L", (50, 50), 128)
        h8 = _dhash(img, hash_size=8)
        h16 = _dhash(img, hash_size=16)
        # Larger hash → longer hex string
        assert len(h16) >= len(h8)
