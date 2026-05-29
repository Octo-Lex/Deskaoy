"""Single source of truth for the deskaoy version.

Uses the hardcoded constant as the primary source, since the installed
package version may lag behind the source tree during development.
The constant is updated automatically during release builds.
"""

from __future__ import annotations

VERSION = "2.0.0"
