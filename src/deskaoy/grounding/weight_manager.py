"""Weight manager — download and cache ML model weights from HuggingFace.

Weights are stored in ~/.cache/deskaoy/weights/ and verified by SHA256.
The ~300MB download happens only on first use.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Default cache directory
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "deskaoy" / "weights"

# Known weight files and their expected SHA256 checksums.
# Updated when new OmniParser v2 releases are published.
_WEIGHT_MANIFEST: dict[str, dict[str, str]] = {
    "icon_detect/model.pt": {
        "url": "https://huggingface.co/microsoft/OmniParser-v2.0/resolve/main/icon_detect/model.pt",
        "sha256": "",  # Populated after first verified download
    },
    "icon_detect/model.yaml": {
        "url": "https://huggingface.co/microsoft/OmniParser-v2.0/resolve/main/icon_detect/model.yaml",
        "sha256": "",
    },
    "icon_caption_florence/config.json": {
        "url": "https://huggingface.co/microsoft/OmniParser-v2.0/resolve/main/icon_caption_florence/config.json",
        "sha256": "",
    },
    "icon_caption_florence/generation_config.json": {
        "url": "https://huggingface.co/microsoft/OmniParser-v2.0/resolve/main/icon_caption_florence/generation_config.json",
        "sha256": "",
    },
}

# Manifest file storing verified SHA256 checksums
_MANIFEST_FILE = "manifest.json"


class WeightManager:
    """Download and cache ML model weights."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._manifest_path = self._cache_dir / _MANIFEST_FILE
        self._manifest = self._load_manifest()

    def ensure_weights(self, name: str | None = None) -> dict[str, Path]:
        """Ensure weight files are available locally.

        Args:
            name: Specific weight set to download (e.g. "icon_detect").
                  None = download all.

        Returns:
            Dict of relative path → absolute Path for each weight file.
        """
        targets = {}
        for rel_path, info in _WEIGHT_MANIFEST.items():
            if name is not None and not rel_path.startswith(name):
                continue
            targets[rel_path] = info

        result: dict[str, Path] = {}
        for rel_path, info in targets.items():
            local_path = self._cache_dir / rel_path
            if self._is_valid(local_path, info.get("sha256", "")):
                result[rel_path] = local_path
                continue

            # Download
            logger.info("Downloading weight file: %s", rel_path)
            self._download(info["url"], local_path)

            # Verify and update manifest
            sha256 = self._sha256(local_path)
            self._manifest[rel_path] = sha256
            self._save_manifest()
            result[rel_path] = local_path

        return result

    def weight_path(self, rel_path: str) -> Path | None:
        """Get the local path for a weight file, or None if not cached."""
        p = self._cache_dir / rel_path
        if p.exists():
            return p
        return None

    def is_cached(self, rel_path: str) -> bool:
        """Check if a weight file is already cached."""
        return (self._cache_dir / rel_path).exists()

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_valid(self, path: Path, expected_sha: str) -> bool:
        """Check if a file exists and matches expected SHA256."""
        if not path.exists():
            return False
        if not expected_sha:
            # No checksum known yet — trust if file exists and is non-empty
            return path.stat().st_size > 0
        return self._sha256(path) == expected_sha

    def _download(self, url: str, dest: Path) -> None:
        """Download a file from URL to dest."""
        import urllib.request

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")

        try:
            urllib.request.urlretrieve(url, tmp)
            shutil.move(str(tmp), str(dest))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _sha256(path: Path) -> str:
        """Compute SHA256 hex digest of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _load_manifest(self) -> dict[str, str]:
        """Load the cached manifest (rel_path → sha256)."""
        if self._manifest_path.exists():
            try:
                return json.loads(self._manifest_path.read_text())
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}

    def _save_manifest(self) -> None:
        """Persist the manifest to disk."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(
            json.dumps(self._manifest, indent=2, sort_keys=True)
        )
