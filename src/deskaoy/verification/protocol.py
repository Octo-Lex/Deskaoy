"""VerifierAdapter — decouples VisualVerifier from browser-specific classes.

Implementations:
  - BrowserVerifierAdapter (wraps CDPBridge + PageHandle)
  - MacOSVerifierAdapter (wraps AXUIElement screenshot)
  - WindowsVerifierAdapter (wraps DXGI Desktop Duplication)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VerifierAdapter(ABC):
    """Decouples VisualVerifier from CDPBridge/PageHandle.

    The verifier needs screenshots and structural trees for comparison.
    This adapter provides them without coupling to browser internals.
    """

    @abstractmethod
    async def capture_screenshot(self) -> tuple[bytes, str]:
        """Capture a screenshot.

        Returns:
            (image_bytes, sha256_hex) tuple.
        """
        ...

    @abstractmethod
    async def capture_structural(self, url: str, title: str) -> Any:
        """Capture a structural (AX) tree snapshot.

        Args:
            url: Current page/focus identifier.
            title: Current window/page title.

        Returns:
            AXSnapshot object.
        """
        ...

    @abstractmethod
    async def execute_js(self, expression: str) -> Any:
        """Execute JS or platform script for DOM/tree queries.

        Returns:
            Raw result of the expression.
        """
        ...
