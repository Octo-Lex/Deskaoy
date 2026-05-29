"""Enhanced VisionProviderFactory with cascade routing and env configuration."""

from __future__ import annotations

import logging
import os
from typing import Any

from deskaoy.vision.types import CascadeConfig, VisionProviderName

logger = logging.getLogger(__name__)


class VisionProviderFactory:
    """Factory for vision providers with cascade support."""

    def __init__(
        self,
        providers: dict[str, Any] | None = None,
        cascade: CascadeConfig | None = None,
    ) -> None:
        self._providers: dict[str, Any] = providers or {}
        self._cascade = cascade or CascadeConfig()
        self._default_key: str | None = (
            next(iter(self._providers)) if self._providers else None
        )

    def get_provider(
        self,
        name: str | None = None,
        model: str | None = None,
    ) -> Any | None:
        if not self._providers:
            return None
        if model is not None:
            for p in self._providers.values():
                if getattr(p, "model_id", None) == model:
                    return p
            return None
        if name is not None:
            return self._providers.get(name)
        if self._default_key is not None:
            return self._providers[self._default_key]
        return None

    def get_provider_for_complexity(self, complexity: str) -> Any | None:
        mapping = {
            "simple": (self._cascade.simple_provider, self._cascade.simple_model),
            "complex": (self._cascade.complex_provider, self._cascade.complex_model),
            "ambiguous": (self._cascade.ambiguous_provider, self._cascade.ambiguous_model),
        }
        entry = mapping.get(str(complexity))
        if entry is None:
            return self.get_provider()
        provider_name, _model = entry
        provider = self._providers.get(str(provider_name))
        if provider is None:
            return self.get_provider()
        return provider

    @classmethod
    def from_env(cls) -> VisionProviderFactory:
        providers: dict[str, Any] = {}
        cascade = CascadeConfig()

        provider_name = os.environ.get("SB_VISION_DEFAULT_PROVIDER", "").strip()
        model_id = os.environ.get("SB_VISION_DEFAULT_MODEL", "").strip() or None

        anthropic_key = os.environ.get("SB_ANTHROPIC_API_KEY", "").strip()
        if anthropic_key:
            from deskaoy.vision.providers import AnthropicCUAProvider
            providers["anthropic"] = AnthropicCUAProvider(
                api_key=anthropic_key, model=model_id or "claude-sonnet-4-20250514",
            )

        openai_key = os.environ.get("SB_OPENAI_API_KEY", "").strip()
        if openai_key:
            from deskaoy.vision.providers import OpenAIResponseProvider
            providers["openai"] = OpenAIResponseProvider(
                api_key=openai_key, model=model_id or "gpt-4o-mini",
            )

        uitars_path = os.environ.get("SB_UITARS_MODEL_PATH", "").strip()
        if uitars_path:
            from deskaoy.vision.providers import UITARSProvider
            providers["uitars"] = UITARSProvider(model_path=uitars_path)

        # Local grounding pipeline (OmniParser v2 + Florence-2 + PaddleOCR)
        # Enabled via SB_VISION_DEFAULT_PROVIDER=grounding or always available
        grounding_enabled = os.environ.get("SB_GROUNDING_ENABLED", "").strip().lower()
        if grounding_enabled in ("1", "true", "yes") or provider_name == "grounding":
            try:
                from deskaoy.grounding.pipeline import GroundingPipeline
                providers["grounding"] = GroundingPipeline()
                logger.info("GroundingPipeline registered as vision provider")
            except Exception as exc:
                logger.warning("Failed to initialize GroundingPipeline: %s", exc)

        env_simple = os.environ.get("SB_VISION_CASCADE_SIMPLE_PROVIDER", "").strip()
        env_complex = os.environ.get("SB_VISION_CASCADE_COMPLEX_PROVIDER", "").strip()
        env_ambiguous = os.environ.get("SB_VISION_CASCADE_AMBIGUOUS_PROVIDER", "").strip()

        if env_simple:
            cascade.simple_provider = VisionProviderName(env_simple)
        if env_complex:
            cascade.complex_provider = VisionProviderName(env_complex)
        if env_ambiguous:
            cascade.ambiguous_provider = VisionProviderName(env_ambiguous)

        factory = cls(providers=providers, cascade=cascade)
        if provider_name:
            factory._default_key = provider_name

        return factory

    @property
    def provider_priority(self) -> list[str]:
        order = ["anthropic", "openai", "uitars", "grounding"]
        return [n for n in order if n in self._providers]

    @property
    def provider_names(self) -> set[str]:
        return set(self._providers.keys())

    @property
    def cascade(self) -> CascadeConfig:
        return self._cascade
