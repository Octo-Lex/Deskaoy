"""VisualVerifier — snapshot, verify, look_act_look cycle for visual verification.

Decoupled from browser-specific classes via VerifierAdapter protocol.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageDraw

from deskaoy.cascade.types import AXSnapshot
from deskaoy.verification.ax_diff import diff_ax_trees
from deskaoy.verification.hasher import HasherCache, compute_hash
from deskaoy.verification.protocol import VerifierAdapter
from deskaoy.verification.types import (
    ActionVerifiability,
    VerificationActionType,
    VerificationLevel,
    VerificationResult,
    VerificationSnapshot,
    VerifierConfig,
    VLMVerificationDetail,
)

logger = logging.getLogger(__name__)


class VisualVerifier:
    """Verify visual changes before/after actions.

    Takes a VerifierAdapter instead of browser-specific classes.
    The adapter provides screenshots and structural snapshots.
    """

    def __init__(
        self,
        adapter: VerifierAdapter,
        config: VerifierConfig | None = None,
        vlm_compare_fn: Callable | None = None,
    ) -> None:
        self._adapter = adapter
        self._config = config or VerifierConfig()
        self._hash_cache = HasherCache(max_size=self._config.hash_cache_size)
        self._vlm_compare_fn = vlm_compare_fn

    # =================================================================
    # Primary API
    # =================================================================

    async def snapshot(
        self,
        *,
        capture_ax: bool = True,
        capture_bytes: bool = True,
    ) -> VerificationSnapshot:
        """Capture a verification snapshot (screenshot + optional AX tree)."""
        image_bytes, sha256 = await self._adapter.capture_screenshot()

        cached = self._hash_cache.get(sha256)
        if cached is not None:
            phash = cached
        else:
            phash = compute_hash(image_bytes)
            self._hash_cache.put(sha256, phash)

        ax_snap: AXSnapshot | None = None
        ax_node_count = 0
        ax_interactive_count = 0
        if capture_ax:
            try:
                ax_snap = await self._adapter.capture_structural("", "")
                if ax_snap:
                    ax_node_count = len(ax_snap.nodes)
                    ax_interactive_count = sum(
                        1 for n in ax_snap.nodes.values() if n.is_interactive
                    )
            except Exception:
                logger.debug("AX snapshot capture failed during verification snapshot")

        dims = (0, 0)
        if image_bytes:
            try:
                with Image.open(io.BytesIO(image_bytes)) as img:
                    dims = img.size
            except Exception:
                pass

        return VerificationSnapshot(
            perceptual_hash=phash,
            ax_snapshot=ax_snap,
            screenshot_bytes=image_bytes if capture_bytes else None,
            screenshot_sha256=sha256,
            image_dimensions=dims,
            ax_node_count=ax_node_count,
            ax_interactive_count=ax_interactive_count,
        )

    async def verify(
        self,
        before: VerificationSnapshot,
        after: VerificationSnapshot,
        *,
        level: VerificationLevel | None = None,
        action_description: str | None = None,
        action_coordinates: tuple[float, float] | None = None,
    ) -> VerificationResult:
        start = time.monotonic()
        effective_level = level or self._config.default_level

        try:
            if effective_level == VerificationLevel.NONE:
                return VerificationResult(
                    changed=None, confidence=0.0, similarity=1.0,
                    level=VerificationLevel.NONE,
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            if effective_level == VerificationLevel.HASH:
                return self._verify_hash(before, after, start)

            if effective_level == VerificationLevel.STRUCTURAL_AX:
                return self._verify_structural(before, after, start)

            if effective_level == VerificationLevel.VLM_FULL:
                if self._vlm_compare_fn is not None:
                    return await self._verify_vlm(before, after, start, action_description)
                return VerificationResult(
                    changed=None, confidence=0.0, similarity=0.0,
                    level=VerificationLevel.VLM_FULL,
                    error="VLM provider not configured — pass vlm_compare_fn to enable VLM_FULL",
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            return VerificationResult(
                changed=None, confidence=0.0, similarity=0.0,
                level=effective_level, error="Unknown verification level",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return VerificationResult(
                changed=None, confidence=0.0, similarity=0.0,
                level=effective_level, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def look_act_look(
        self,
        action: Callable[[], Any],
        *,
        action_type: VerificationActionType = VerificationActionType.CLICK,
        level: VerificationLevel | None = None,
        action_description: str | None = None,
        action_coordinates: tuple[float, float] | None = None,
        settle_ms: int | None = None,
    ) -> tuple[Any, VerificationResult]:
        """Look-act-look verification cycle.

        1. Capture pre-action snapshot
        2. Execute action
        3. Wait for settle
        4. Capture post-action snapshot
        5. Compare and return verification result
        """
        verdict = self.classify_action(action_type)
        if not verdict.should_verify:
            result = await action()
            return result, VerificationResult(
                changed=None, confidence=0.0, similarity=1.0,
                level=VerificationLevel.NONE,
            )

        pre = await self.snapshot(capture_ax=True, capture_bytes=True)
        action_result = await action()

        wait_ms = settle_ms if settle_ms is not None else self._config.settle_ms
        if wait_ms > 0:
            await asyncio.sleep(wait_ms / 1000.0)

        post = await self.snapshot(capture_ax=True, capture_bytes=True)
        verification = await self.verify(
            pre, post,
            level=level, action_description=action_description,
            action_coordinates=action_coordinates,
        )
        return action_result, verification

    # =================================================================
    # Classification
    # =================================================================

    def classify_action(
        self,
        action_type: VerificationActionType,
        *,
        target: str | None = None,
    ) -> ActionVerifiability:
        if action_type in self._config.always_verify:
            return ActionVerifiability(
                action_type=action_type, should_verify=True,
                reason="In always_verify list",
            )
        if action_type in self._config.never_verify:
            return ActionVerifiability(
                action_type=action_type, should_verify=False,
                reason="In never_verify list",
            )

        _VERIFY_TYPES = {
            VerificationActionType.NAVIGATE,
            VerificationActionType.CLICK,
            VerificationActionType.DRAG,
            VerificationActionType.FILL,
            VerificationActionType.SELECT,
        }
        if action_type in _VERIFY_TYPES:
            return ActionVerifiability(
                action_type=action_type, should_verify=True,
                reason=f"{action_type.value} is a state-changing action",
            )
        return ActionVerifiability(
            action_type=action_type, should_verify=False,
            reason=f"{action_type.value} is not verifiable",
        )

    # =================================================================
    # Annotation helpers
    # =================================================================

    def _annotate_screenshot(
        self,
        image_bytes: bytes,
        coordinates: tuple[float, float],
        action_type: str = "click",
    ) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)
        x, y = int(coordinates[0]), int(coordinates[1])

        colors = {"click": "red", "fill": "blue", "drag": "green", "hover": "yellow"}
        color = colors.get(action_type, "red")
        radius = 15 if action_type == "click" else 8

        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            outline=color, width=2,
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _extract_zoomed_crop(
        self,
        image_bytes: bytes,
        center: tuple[float, float],
        crop_size: int = 300,
        upscale: int = 4,
    ) -> bytes:
        img = Image.open(io.BytesIO(image_bytes))
        half = crop_size // 2
        cx, cy = int(center[0]), int(center[1])
        left = max(0, cx - half)
        top = max(0, cy - half)
        right = min(img.width, cx + half)
        bottom = min(img.height, cy + half)
        crop = img.crop((left, top, right, bottom))
        new_size = (crop.width * upscale, crop.height * upscale)
        upscaled = crop.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        upscaled.save(buf, format="PNG")
        return buf.getvalue()

    # =================================================================
    # Internal
    # =================================================================

    def _verify_hash(
        self,
        before: VerificationSnapshot,
        after: VerificationSnapshot,
        start: float,
    ) -> VerificationResult:
        distance = before.perceptual_hash.hamming_distance(after.perceptual_hash)
        similarity = 1.0 - distance / 64.0
        threshold = self._config.hash_threshold

        if distance >= threshold:
            changed = True
            confidence = min(0.9, 0.6 + distance / 64.0)
        else:
            changed = False
            confidence = 0.95 if distance < 5 else 0.8

        return VerificationResult(
            changed=changed, confidence=confidence, similarity=similarity,
            level=VerificationLevel.HASH, hash_distance=distance,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    def _verify_structural(
        self,
        before: VerificationSnapshot,
        after: VerificationSnapshot,
        start: float,
    ) -> VerificationResult:
        if before.ax_snapshot is None or after.ax_snapshot is None:
            return VerificationResult(
                changed=None, confidence=0.0, similarity=0.0,
                level=VerificationLevel.STRUCTURAL_AX,
                error="Missing AX snapshot for structural comparison",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        diff = diff_ax_trees(before.ax_snapshot, after.ax_snapshot)
        total = diff.total_interactive_changes
        changed = total >= self._config.ax_change_threshold
        similarity = 1.0 - min(total / 64.0, 1.0)
        confidence = min(0.95, 0.7 + total * 0.05) if changed else 0.9

        return VerificationResult(
            changed=changed, confidence=confidence, similarity=similarity,
            level=VerificationLevel.STRUCTURAL_AX, ax_diff=diff,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _verify_vlm(
        self,
        before: VerificationSnapshot,
        after: VerificationSnapshot,
        start: float,
        action_description: str | None = None,
    ) -> VerificationResult:
        """M5: Verify using VLM comparison function."""
        if self._vlm_compare_fn is None:
            return VerificationResult(
                changed=None, confidence=0.0, similarity=0.0,
                level=VerificationLevel.VLM_FULL,
                error="VLM provider not configured",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        try:
            if before.screenshot_bytes and after.screenshot_bytes:
                vlm_result = await self._vlm_compare_fn(
                    before.screenshot_bytes, after.screenshot_bytes,
                    prompt=action_description,
                )
                # VLM should return dict with 'changed', 'confidence', 'description'
                if isinstance(vlm_result, dict):
                    detail = VLMVerificationDetail(
                        succeeded=True,
                        changes=tuple(vlm_result.get("changes", [])),
                        confidence=float(vlm_result.get("confidence", 0.5)),
                        raw_response=vlm_result.get("description"),
                    )
                    return VerificationResult(
                        changed=vlm_result.get("changed"),
                        confidence=float(vlm_result.get("confidence", 0.5)),
                        similarity=float(vlm_result.get("similarity", 0.5)),
                        level=VerificationLevel.VLM_FULL,
                        vlm_detail=detail,
                        duration_ms=(time.monotonic() - start) * 1000,
                    )
                # Fallback: treat as boolean changed/not changed
                return VerificationResult(
                    changed=bool(vlm_result),
                    confidence=0.7,
                    similarity=0.5,
                    level=VerificationLevel.VLM_FULL,
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            else:
                return VerificationResult(
                    changed=None, confidence=0.0, similarity=0.0,
                    level=VerificationLevel.VLM_FULL,
                    error="Missing screenshot for VLM comparison",
                    duration_ms=(time.monotonic() - start) * 1000,
                )
        except Exception as exc:
            return VerificationResult(
                changed=None, confidence=0.0, similarity=0.0,
                level=VerificationLevel.VLM_FULL,
                error=f"VLM comparison failed: {exc}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
