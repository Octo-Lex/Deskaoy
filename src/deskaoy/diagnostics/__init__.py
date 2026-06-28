"""Platform diagnostics for deskaoy.

Side-effect-free environment checks that expose the adapter truthfulness
work from Batches 5, 10, and 11 as user-facing diagnostics.
"""

from __future__ import annotations

from deskaoy.diagnostics.doctor import CheckResult, run_doctor

__all__ = ["CheckResult", "run_doctor"]
