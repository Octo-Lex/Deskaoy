"""
Stress test conftest — markers, CLI flags, shared fixtures.

Markers:
  @pytest.mark.stress     — concurrency / rapid-fire tests
  @pytest.mark.chaos      — fault injection tests
  @pytest.mark.endurance  — long-running / memory leak tests
  @pytest.mark.property   — Hypothesis property-based tests

Usage:
  pytest tests/stress/ -m stress          — run only concurrency tests
  pytest tests/stress/ -m chaos           — run only chaos tests
  pytest tests/stress/ -m endurance       — run only endurance tests
  pytest tests/stress/ -m property        — run only property tests
  pytest tests/stress/ --run-all-stress   — run everything
"""
import asyncio
import os

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "stress: concurrency / rapid-fire stress tests (nightly)")
    config.addinivalue_line("markers", "chaos: fault injection tests (nightly)")
    config.addinivalue_line("markers", "endurance: long-running / memory leak tests (weekly)")
    config.addinivalue_line("markers", "property: Hypothesis property-based tests")


def pytest_addoption(parser):
    parser.addoption(
        "--run-all-stress", action="store_true", default=False,
        help="Run all stress tests (stress + chaos + endurance + property)"
    )
    parser.addoption(
        "--run-stress", action="store_true", default=False,
        help="Run concurrency stress tests"
    )
    parser.addoption(
        "--run-chaos", action="store_true", default=False,
        help="Run chaos / fault injection tests"
    )
    parser.addoption(
        "--run-endurance", action="store_true", default=False,
        help="Run endurance / memory leak tests"
    )
    parser.addoption(
        "--run-property", action="store_true", default=False,
        help="Run Hypothesis property-based tests"
    )


def pytest_collection_modifyitems(config, items):
    markers = {
        "stress": config.getoption("--run-stress"),
        "chaos": config.getoption("--run-chaos"),
        "endurance": config.getoption("--run-endurance"),
        "property": config.getoption("--run-property"),
    }
    all_stress = config.getoption("--run-all-stress")

    skip_map = {}
    for marker_name, enabled in markers.items():
        if not enabled and not all_stress:
            skip_map[marker_name] = pytest.mark.skip(
                reason=f"Need --run-{marker_name} or --run-all-stress flag"
            )

    for item in items:
        for marker_name, skip_mark in skip_map.items():
            # Use iter_markers() to check actual markers, NOT keywords
            # (keywords include file paths like "tests/stress/" which falsely match)
            if any(m.name == marker_name for m in item.iter_markers()):
                item.add_marker(skip_mark)


# ── Shared Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def event_loop():
    """Create a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def tmp_dir(tmp_path):
    """Temporary directory for file-based tests."""
    return tmp_path


@pytest.fixture
def display():
    """Ensure DISPLAY is set for AT-SPI / X11 tests."""
    d = os.environ.get("DISPLAY", ":99")
    os.environ["DISPLAY"] = d
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return d
