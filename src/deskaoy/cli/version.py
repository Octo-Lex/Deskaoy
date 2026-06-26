"""CLI version constants.

Re-exported from :mod:`deskaoy._version` (the neutral source). The CLI may
depend on core; core must never depend on the CLI, so the canonical resolver
lives in ``deskaoy._version`` and is simply re-exported here for the CLI's
own use.
"""

from __future__ import annotations

from deskaoy._version import VERSION, resolve_version

__all__ = ["VERSION", "resolve_version"]
