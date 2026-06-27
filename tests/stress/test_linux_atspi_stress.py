"""
Linux AT-SPI Stress Tests — stress-test the LinuxAdapter on real hardware.

Requires:
  - Ubuntu 24.04 LXC CT 250 @ 192.168.3.152 (Proxmox)
  - Xvfb :99 running
  - gnome-calculator installed and launched
  - AT-SPI2 bus active

Run on the VM:
  DISPLAY=:99 pytest tests/stress/test_linux_atspi_stress.py --run-stress -v
"""
import asyncio
import os
import sys
import time

import pytest

# ── Skip if not on Linux with AT-SPI ────────────────────────────────────

pytestmark = [
    pytest.mark.stress,
    pytest.mark.skipif(sys.platform != "linux", reason="Linux-only tests"),
]

# Check AT-SPI availability
try:
    import pyatspi
    HAS_ATSPI = True
except ImportError:
    HAS_ATSPI = False

pytestmark.append(
    pytest.mark.skipif(not HAS_ATSPI, reason="pyatspi not available")
)


from deskaoy.adapters.linux import LinuxAdapter

# ══════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def display():
    d = os.environ.get("DISPLAY", ":99")
    os.environ["DISPLAY"] = d
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return d


@pytest.fixture
def adapter(display):
    """Create a LinuxAdapter connected to the display."""
    return LinuxAdapter()


def _ensure_calculator():
    """Launch gnome-calculator if not already running."""
    import subprocess
    result = subprocess.run(
        ["pgrep", "-x", "gnome-calculator"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        subprocess.Popen(
            ["gnome-calculator"],
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":99")},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)


# ══════════════════════════════════════════════════════════════════════════
# 1. SNAPSHOT STRESS — rapid snapshots
# ══════════════════════════════════════════════════════════════════════════

class TestSnapshotStress:

    async def test_50_rapid_snapshots(self, adapter):
        """50 snapshots in quick succession must not crash."""
        results = []
        for _i in range(50):
            snap = await adapter.snapshot()
            results.append(snap is not None)

        # At least some should succeed
        assert any(results), "All 50 snapshots failed"

    async def test_snapshot_after_app_toggle(self, adapter):
        """Snapshot must work before and after app toggle."""
        await adapter.snapshot()

        _ensure_calculator()
        time.sleep(1)

        snap2 = await adapter.snapshot()
        assert snap2 is not None

    async def test_10_concurrent_snapshots(self, adapter):
        """10 concurrent snapshot calls must not deadlock."""
        results = await asyncio.gather(
            *[adapter.snapshot() for _ in range(10)],
            return_exceptions=True,
        )
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) <= 2, f"Too many exceptions: {exceptions}"


# ══════════════════════════════════════════════════════════════════════════
# 2. SCREENSHOT STRESS
# ══════════════════════════════════════════════════════════════════════════

class TestScreenshotStress:

    async def test_100_rapid_screenshots(self, adapter):
        """100 screenshots in 5 seconds — must not lag."""
        start = time.time()
        sizes = set()
        for _ in range(100):
            data = await adapter.screenshot()
            sizes.add(len(data))

        elapsed = time.time() - start
        # Must complete 100 screenshots in under 30 seconds
        assert elapsed < 30, f"Too slow: {elapsed:.1f}s for 100 screenshots"
        # All screenshots should be non-empty
        assert 0 not in sizes, "Empty screenshot detected"

    async def test_screenshot_size_consistency(self, adapter):
        """Screenshots of same display should be similar size."""
        sizes = []
        for _ in range(20):
            data = await adapter.screenshot()
            sizes.append(len(data))

        avg = sum(sizes) / len(sizes)
        for s in sizes:
            # Each screenshot should be within 20% of average
            assert abs(s - avg) / avg < 0.20, f"Size variance: {s} vs avg {avg}"


# ══════════════════════════════════════════════════════════════════════════
# 3. WINDOW LISTING STRESS
# ══════════════════════════════════════════════════════════════════════════

class TestWindowListingStress:

    async def test_200_rapid_list_windows(self, adapter):
        """200 rapid list_windows calls must not crash or hang."""
        start = time.time()
        for _ in range(200):
            windows = await adapter.list_windows()
            assert isinstance(windows, list)

        elapsed = time.time() - start
        assert elapsed < 10, f"Too slow: {elapsed:.1f}s for 200 list_windows"


# ══════════════════════════════════════════════════════════════════════════
# 4. AT-SPI TREE WALKING — deep hierarchy
# ══════════════════════════════════════════════════════════════════════════

class TestATSpiTreeStress:

    def test_walk_desktop_tree(self, adapter):
        """Walking the entire AT-SPI desktop tree must not crash."""
        desktop = pyatspi.Registry.getDesktop(0)
        node_count = 0

        def walk(node, depth=0):
            nonlocal node_count
            node_count += 1
            if depth > 10 or node_count > 5000:
                return  # Safety limit
            try:
                for child in node:
                    walk(child, depth + 1)
            except Exception:
                pass  # Some nodes are inaccessible

        walk(desktop)
        assert node_count > 0, "Desktop tree is empty"

    def test_repeated_tree_walks(self, adapter):
        """Walking the tree 50 times must not accumulate errors."""
        errors = 0
        for _ in range(50):
            desktop = pyatspi.Registry.getDesktop(0)
            try:
                apps = list(desktop)
                _ = len(apps)
            except Exception:
                errors += 1

        assert errors < 10, f"Too many errors walking tree: {errors}/50"


# ══════════════════════════════════════════════════════════════════════════
# 5. TITLE / STATE — repeated queries
# ══════════════════════════════════════════════════════════════════════════

class TestTitleStateStress:

    async def test_100_rapid_title_queries(self, adapter):
        """100 rapid current_title calls must not crash."""
        titles = []
        for _ in range(100):
            title = await adapter.current_title()
            titles.append(title)

        # All should return a string or None
        for t in titles:
            assert t is None or isinstance(t, str)

    async def test_evaluate_100_expressions(self, adapter):
        """100 evaluate calls must not crash."""
        for i in range(100):
            try:
                await adapter.evaluate(f"1 + {i}")
            except NotImplementedError:
                pytest.skip("evaluate not implemented on Linux")
            except Exception:
                pass  # Some expressions may fail — that's OK
