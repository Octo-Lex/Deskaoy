"""Version resolution for deskaoy.

This is the **neutral, dependency-free** home for version logic. Core runtime
modules (``desktop_agent``, ``manifest``, ``tracing``, ``__init__``) import
``resolve_version`` from here — never from ``deskaoy.cli.*``, so that core
code does not depend on the CLI package.

Resolution strategy:
- Prefer installed package metadata via ``importlib.metadata`` — this is the
  release source of truth after ``pip install``.
- Fall back to the :data:`VERSION` constant below when the package is not
  installed (e.g. running from a raw source checkout without
  ``pip install -e .``).

The :data:`VERSION` fallback must stay in sync with ``[project].version`` in
``pyproject.toml``; this invariant is guarded by the release-coherence tests.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

PACKAGE_NAME = "deskaoy"

# Hardcoded fallback used when the package is not installed (raw source
# checkout). Must stay in sync with [project].version in pyproject.toml.
VERSION = "2.1.0"


def resolve_version() -> str:
    """Resolve the deskaoy version at runtime.

    Prefers installed package metadata (the source of truth after
    ``pip install``). Falls back to the hardcoded :data:`VERSION` constant
    when the package is not installed.
    """
    try:
        return _pkg_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return VERSION
