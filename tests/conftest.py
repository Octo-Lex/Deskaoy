import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires a real browser")
    # Disable pyautogui's fail-safe on CI / headless environments.
    # On GitHub Actions Windows runners (no interactive desktop), pyautogui's
    # FailSafeThread can raise KeyboardInterrupt when the mouse hits a corner,
    # killing the entire test process. Disabling it is safe in tests since no
    # real mouse input is ever injected.
    import os
    if os.getenv("GITHUB_ACTIONS") == "true":
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
        except ImportError:
            pass


def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False,
                     help="Run integration tests that launch a real browser")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip = pytest.mark.skip(reason="Need --run-integration flag to run")
        for item in items:
            # Use get_closest_marker to match the explicit @pytest.mark.integration
            # marker only, not the "integration" keyword from the directory path.
            if item.get_closest_marker("integration"):
                item.add_marker(skip)


@pytest.fixture
def mock_page():
    """A mock page object with configurable evaluate() return value."""
    class MockPage:
        def __init__(self, return_value=1, raise_exc=None):
            self._return_value = return_value
            self._raise_exc = raise_exc

        def evaluate(self, expr):
            if self._raise_exc:
                raise self._raise_exc
            return self._return_value

    return MockPage
