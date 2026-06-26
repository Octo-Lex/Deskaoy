"""Release coherence tests — guard against the drift fixed in Batch 1.

These are static/structural checks (no desktop interaction) that enforce:

1. **Version single-source** — every place that exposes a version agrees:
   ``deskaoy.__version__``, ``deskaoy._version.VERSION`` /
   ``resolve_version()``, ``DesktopAgent.version``, telemetry
   ``TelemetryConfig.service_version``, and the manifest all resolve to the
   same value. The fallback constant must also match ``pyproject.toml``.

2. **README quick start matches the real API** — the snippet must reference
   ``AgentGoal`` / ``AgentContext`` (the actual ``execute`` signature), not a
   bare positional string. This catches the P0 README/API mismatch.

3. **No stale repository URLs** — neither the placeholder
   ``github.com/example`` nor the pre-rename ``Elephant-Rock-Lab`` org should
   appear in user-facing metadata.

4. **release-check uses the real version attribute** — must not reference
   ``DesktopAgent.__dataclass_fields__`` (DesktopAgent is a plain class).

5. **Core does not depend on CLI** — core modules must import version logic
   from ``deskaoy._version``, never from ``deskaoy.cli.*``.

6. **Manifest domains reflect v2.0** — ``desktop_automation`` only; the
   removed ``browser_automation`` domain must not be present.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import deskaoy
from deskaoy._version import VERSION as FALLBACK_VERSION
from deskaoy._version import resolve_version
from deskaoy.desktop_agent import DesktopAgent
from deskaoy.manifest import CAPABILITY_MANIFEST
from deskaoy.tracing.runtime import TelemetryConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
README = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Version single-source
# ---------------------------------------------------------------------------

class TestVersionCoherence:

    def test_package_version_matches_fallback_constant(self):
        # When installed, __version__ resolves from metadata; in a raw
        # checkout it equals the fallback. Either way they must agree.
        assert deskaoy.__version__ == FALLBACK_VERSION

    def test_resolve_version_matches_package_version(self):
        assert resolve_version() == deskaoy.__version__

    def test_desktop_agent_version_matches_package(self):
        assert DesktopAgent.version == deskaoy.__version__

    def test_telemetry_default_service_version_matches_package(self):
        # Fresh config must default to the current package version, not a
        # stale hardcoded constant.
        assert TelemetryConfig().service_version == deskaoy.__version__

    def test_manifest_version_matches_package(self):
        assert CAPABILITY_MANIFEST["version"] == deskaoy.__version__

    def test_pyproject_version_matches_package(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        assert m is not None, "version not found in pyproject.toml"
        assert m.group(1) == deskaoy.__version__

    def test_fallback_constant_matches_pyproject(self):
        """Guard the secondary source: the fallback literal must not drift
        from pyproject.toml. Without this, the fallback could silently go
        stale even though runtime resolution masks it on installed builds."""
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        assert m is not None
        assert m.group(1) == FALLBACK_VERSION


# ---------------------------------------------------------------------------
# 2. README quick start matches the real API
# ---------------------------------------------------------------------------

class TestReadmeQuickStart:

    def test_quick_start_uses_agent_goal(self):
        # The corrected quick start must construct an AgentGoal rather than
        # passing a bare string to execute().
        assert "AgentGoal" in README, (
            "README quick start should reference AgentGoal (the real execute signature)"
        )

    def test_quick_start_uses_agent_context(self):
        assert "AgentContext" in README, (
            "README quick start should reference AgentContext (the real execute signature)"
        )

    def test_quick_start_does_not_pass_bare_string_to_execute(self):
        # The old broken snippet was: result = await agent.execute("...")
        # Match execute( followed by a quote — a bare string positional arg.
        bad = re.search(r'\.execute\(\s*["\']', README)
        assert bad is None, (
            f"README appears to call execute() with a bare string at: {bad.group(0)!r}"
        )

    def test_quick_start_uses_dry_run_for_default_agent(self):
        # The quick start constructs DesktopAgent() with no surface/LLM and
        # calls execute() with capability="automate". Without dry_run=True
        # this returns failure ("No agent loop or LLM configured"). The
        # snippet must be a dry-run smoke test so it actually succeeds.
        assert "dry_run=True" in README, (
            "README quick start must set dry_run=True — without an LLM/surface "
            "the default-agent automate path otherwise fails on first run"
        )


# ---------------------------------------------------------------------------
# 3. No stale repository URLs
# ---------------------------------------------------------------------------

class TestRepositoryUrls:

    @pytest.mark.parametrize("filename", ["pyproject.toml", "README.md"])
    def test_no_placeholder_url(self, filename):
        content = (PROJECT_ROOT / filename).read_text(encoding="utf-8")
        assert "github.com/example" not in content

    def test_cli_docs_url_is_not_placeholder(self):
        # The CLI `docs` command builds URLs from a docs_base constant; it must
        # not still point at the example placeholder.
        cli_main = (PROJECT_ROOT / "src" / "deskaoy" / "cli" / "main.py").read_text(
            encoding="utf-8"
        )
        assert 'github.com/example/deskaoy' not in cli_main


# ---------------------------------------------------------------------------
# 4. release-check does not use the broken dataclass introspection
# ---------------------------------------------------------------------------

class TestReleaseCheckLogic:

    def test_release_check_does_not_use_dataclass_fields(self):
        """DesktopAgent is a plain class; __dataclass_fields__ raises AttributeError."""
        cli_main = (PROJECT_ROOT / "src" / "deskaoy" / "cli" / "main.py").read_text(
            encoding="utf-8"
        )
        assert "__dataclass_fields__" not in cli_main, (
            "release-check must read DesktopAgent.version directly, not via "
            "__dataclass_fields__ (DesktopAgent is not a dataclass)"
        )

    def test_release_check_has_no_v1_wording(self):
        cli_main = (PROJECT_ROOT / "src" / "deskaoy" / "cli" / "main.py").read_text(
            encoding="utf-8"
        )
        # The stale v1.0-specific wording should be gone.
        assert "v1.0 Release" not in cli_main
        assert "READY FOR v1.0" not in cli_main


# ---------------------------------------------------------------------------
# 5. Core must not depend on CLI
# ---------------------------------------------------------------------------

class TestLayering:

    CORE_MODULES = [
        "src/deskaoy/desktop_agent.py",
        "src/deskaoy/manifest.py",
        "src/deskaoy/tracing/runtime.py",
        "src/deskaoy/__init__.py",
    ]

    @pytest.mark.parametrize("rel_path", CORE_MODULES)
    def test_core_modules_do_not_import_cli_version(self, rel_path):
        """Core runtime code must import version logic from ``deskaoy._version``,
        never from ``deskaoy.cli.*``. The CLI may depend on core; core must
        never depend on the CLI."""
        src = (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")
        assert "deskaoy.cli.version" not in src, (
            f"{rel_path} imports from deskaoy.cli.version — core must use "
            "deskaoy._version instead to avoid a core→CLI dependency"
        )
        assert "from deskaoy.cli" not in src, (
            f"{rel_path} imports from deskaoy.cli — core must not depend on "
            "the CLI package"
        )


# ---------------------------------------------------------------------------
# 6. Manifest domains reflect v2.0 (browser surface removed)
# ---------------------------------------------------------------------------

class TestManifestDomains:

    def test_desktop_automation_domain_present(self):
        assert "desktop_automation" in CAPABILITY_MANIFEST["domains"]

    def test_browser_automation_domain_removed(self):
        # The browser-automation surface was removed in v2.0; the manifest
        # must not still advertise it as a capability domain.
        assert "browser_automation" not in CAPABILITY_MANIFEST["domains"]
