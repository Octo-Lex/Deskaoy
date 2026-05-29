"""Visual grounding model artifact metadata.

No untracked model weights in production.
Every model used by the visual grounding pipeline must declare:
  model_id, version, license, digest, source, storage_path, signature_status,
  runtime_requirements, update_policy
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelArtifact:
    """Metadata for a visual grounding model artifact."""
    model_id: str
    version: str
    license: str                   # e.g. "MIT", "Apache-2.0"
    digest: str = ""               # SHA256 of weights file
    source: str = ""               # HuggingFace repo URL
    storage_path: str = ""         # Local path under AIOS_HOME/artifacts/
    signature_status: str = "unsigned"  # "verified", "unsigned", "unknown"
    runtime_requirements: list[str] = field(default_factory=list)
    update_policy: str = "manual"  # "auto", "manual", "pinned"
    size_bytes: int = 0
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "license": self.license,
            "digest": self.digest,
            "source": self.source,
            "storage_path": self.storage_path,
            "signature_status": self.signature_status,
            "runtime_requirements": self.runtime_requirements,
            "update_policy": self.update_policy,
            "size_bytes": self.size_bytes,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Known model artifacts
# ---------------------------------------------------------------------------

KNOWN_ARTIFACTS: dict[str, ModelArtifact] = {
    "omniparser_v2_detector": ModelArtifact(
        model_id="omniparser_v2_detector",
        version="2.0",
        license="MIT",
        source="https://huggingface.co/microsoft/OmniParser-v2.0",
        runtime_requirements=["ultralytics", "torch"],
        update_policy="manual",
        description="YOLO-based UI element detector from OmniParser v2",
    ),
    "florence2_captioner": ModelArtifact(
        model_id="florence2_captioner",
        version="2.0",
        license="MIT",
        source="https://huggingface.co/microsoft/Florence-2-large",
        runtime_requirements=["transformers", "torch"],
        update_policy="manual",
        description="Florence-2 functional captioning model for UI icons",
    ),
    "paddleocr": ModelArtifact(
        model_id="paddleocr",
        version="4.0",
        license="Apache-2.0",
        source="https://github.com/PaddlePaddle/PaddleOCR",
        runtime_requirements=["paddleocr"],
        update_policy="manual",
        description="PaddleOCR text extraction engine",
    ),
}


def get_artifact(model_id: str) -> ModelArtifact | None:
    """Look up model artifact metadata by ID."""
    return KNOWN_ARTIFACTS.get(model_id)


def register_artifact(artifact: ModelArtifact) -> None:
    """Register a new model artifact."""
    KNOWN_ARTIFACTS[artifact.model_id] = artifact
