"""Tests for weight manager — download, cache, SHA256 verification."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.grounding.weight_manager import WeightManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cache_dir(tmp_path):
    d = tmp_path / "weights"
    d.mkdir()
    return d


@pytest.fixture
def wm(cache_dir):
    return WeightManager(cache_dir=cache_dir)


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

class TestWeightManager:

    def test_cache_dir_created(self, wm, cache_dir):
        assert wm.cache_dir == cache_dir

    def test_is_cached_false(self, wm):
        assert not wm.is_cached("icon_detect/model.pt")

    def test_is_cached_true(self, wm, cache_dir):
        sub = cache_dir / "icon_detect"
        sub.mkdir()
        (sub / "model.pt").write_bytes(b"fake weights")
        assert wm.is_cached("icon_detect/model.pt")

    def test_weight_path_none(self, wm):
        assert wm.weight_path("nonexistent.pt") is None

    def test_weight_path_exists(self, wm, cache_dir):
        (cache_dir / "test.txt").write_text("hello")
        assert wm.weight_path("test.txt") == cache_dir / "test.txt"

    def test_ensure_weights_downloads(self, wm, cache_dir):
        """ensure_weights calls download for missing files."""
        with patch.object(wm, "_download") as mock_dl:
            def fake_download(url, dest):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"downloaded")
            mock_dl.side_effect = fake_download
            result = wm.ensure_weights("icon_detect")
            # Should have downloaded model.pt and model.yaml
            assert mock_dl.call_count >= 1

    def test_manifest_persistence(self, wm, cache_dir):
        """SHA256 manifest is saved and loaded."""
        test_file = cache_dir / "test_weights"
        test_file.write_bytes(b"x" * 100)

        # Compute SHA256
        sha = wm._sha256(test_file)
        assert len(sha) == 64  # SHA256 hex digest

        # Save manifest
        wm._manifest["test_weights"] = sha
        wm._save_manifest()

        # Load in a new manager
        wm2 = WeightManager(cache_dir=cache_dir)
        assert wm2._manifest.get("test_weights") == sha

    def test_is_valid_checks_sha(self, wm, cache_dir):
        test_file = cache_dir / "test.bin"
        test_file.write_bytes(b"hello")

        # Wrong SHA → invalid
        assert not wm._is_valid(test_file, "0000wrong")

        # Correct SHA → valid
        sha = wm._sha256(test_file)
        assert wm._is_valid(test_file, sha)

    def test_is_valid_no_sha_trusts_existing(self, wm, cache_dir):
        test_file = cache_dir / "test.bin"
        test_file.write_bytes(b"hello")
        # No expected SHA → trust if non-empty
        assert wm._is_valid(test_file, "")

    def test_is_valid_empty_file_rejected(self, wm, cache_dir):
        test_file = cache_dir / "empty.bin"
        test_file.write_bytes(b"")
        # Empty file → invalid even without expected SHA
        assert not wm._is_valid(test_file, "")

    def test_sha256_deterministic(self, wm, cache_dir):
        test_file = cache_dir / "test.bin"
        test_file.write_bytes(b"deterministic content")
        sha1 = wm._sha256(test_file)
        sha2 = wm._sha256(test_file)
        assert sha1 == sha2
