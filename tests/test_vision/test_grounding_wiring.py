"""Tests for GroundingPipeline wiring into VisionProviderFactory."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from deskaoy.vision.factory import VisionProviderFactory


class TestGroundingWiring:
    """GroundingPipeline is registered when env vars are set."""

    def test_not_registered_by_default(self):
        """Without env vars, grounding is NOT registered."""
        factory = VisionProviderFactory.from_env()
        assert "grounding" not in factory.provider_names

    def test_registered_when_provider_is_grounding(self):
        """SB_VISION_DEFAULT_PROVIDER=grounding registers the pipeline."""
        with patch.dict(os.environ, {"SB_VISION_DEFAULT_PROVIDER": "grounding"}):
            factory = VisionProviderFactory.from_env()
            assert "grounding" in factory.provider_names
            provider = factory.get_provider("grounding")
            assert provider is not None
            assert provider.name == "grounding"
            assert provider.model_id == "omniparser-v2"

    def test_registered_when_explicitly_enabled(self):
        """SB_GROUNDING_ENABLED=true registers the pipeline."""
        with patch.dict(os.environ, {"SB_GROUNDING_ENABLED": "true"}):
            factory = VisionProviderFactory.from_env()
            assert "grounding" in factory.provider_names

    def test_registered_when_enabled_1(self):
        """SB_GROUNDING_ENABLED=1 also works."""
        with patch.dict(os.environ, {"SB_GROUNDING_ENABLED": "1"}):
            factory = VisionProviderFactory.from_env()
            assert "grounding" in factory.provider_names

    def test_not_registered_when_disabled(self):
        """SB_GROUNDING_ENABLED=false does NOT register."""
        with patch.dict(os.environ, {"SB_GROUNDING_ENABLED": "false"}):
            factory = VisionProviderFactory.from_env()
            assert "grounding" not in factory.provider_names

    def test_default_key_set_to_grounding(self):
        """When SB_VISION_DEFAULT_PROVIDER=grounding, it becomes the default."""
        with patch.dict(os.environ, {"SB_VISION_DEFAULT_PROVIDER": "grounding"}):
            factory = VisionProviderFactory.from_env()
            assert factory._default_key == "grounding"
            default = factory.get_provider()
            assert default is not None
            assert default.name == "grounding"

    def test_grounding_in_priority_list(self):
        with patch.dict(os.environ, {"SB_VISION_DEFAULT_PROVIDER": "grounding"}):
            factory = VisionProviderFactory.from_env()
            assert "grounding" in factory.provider_priority

    def test_grounding_implements_locate(self):
        """The registered provider has a locate() method (VisionProvider protocol)."""
        with patch.dict(os.environ, {"SB_VISION_DEFAULT_PROVIDER": "grounding"}):
            factory = VisionProviderFactory.from_env()
            provider = factory.get_provider("grounding")
            assert hasattr(provider, "locate")
            assert callable(provider.locate)

    def test_pipeline_initialization_failure_handled(self):
        """If GroundingPipeline init fails, factory still works."""
        with patch.dict(os.environ, {"SB_VISION_DEFAULT_PROVIDER": "grounding"}), patch(
            "deskaoy.vision.factory.GroundingPipeline",
            side_effect=RuntimeError("no weights"),
            create=True,
        ):
            # The actual import happens inside from_env, so we need to
            # patch the module-level import. Since GroundingPipeline is
            # imported inside from_env, we patch the pipeline module.
            with patch(
                "deskaoy.grounding.pipeline.GroundingPipeline",
                side_effect=RuntimeError("no weights"),
            ):
                factory = VisionProviderFactory.from_env()
                # Should still create factory, just without grounding
                assert isinstance(factory, VisionProviderFactory)

    def test_coexists_with_cloud_providers(self):
        """Grounding can coexist with Anthropic/OpenAI providers."""
        env = {
            "SB_VISION_DEFAULT_PROVIDER": "grounding",
            "SB_ANTHROPIC_API_KEY": "sk-test-key-123",
        }
        with patch.dict(os.environ, env):
            # Mock AnthropicCUAProvider to avoid real API call
            with patch("deskaoy.vision.providers.AnthropicCUAProvider") as mock_anth:
                mock_anth.return_value = MagicMock(name="anthropic", model_id="claude-sonnet-4-20250514")
                factory = VisionProviderFactory.from_env()
                assert "grounding" in factory.provider_names
                assert "anthropic" in factory.provider_names
