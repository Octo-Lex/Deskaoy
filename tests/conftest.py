import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires a real browser")


def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False,
                     help="Run integration tests that launch a real browser")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip = pytest.mark.skip(reason="Need --run-integration flag to run")
        for item in items:
            if "integration" in item.keywords:
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
