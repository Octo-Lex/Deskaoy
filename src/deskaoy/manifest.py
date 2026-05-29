"""AI-OS Capability Manifest — deskaoy package identity.

This manifest declares the capability to the AI-OS local registry
and marketplace packaging system.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Capability Manifest
# ---------------------------------------------------------------------------

CAPABILITY_MANIFEST: dict[str, Any] = {
    # ── Identity ──────────────────────────────────
    "capability_id": "aios.first_party.deskaoy",
    "name": "Deskaoy",
    "version": "2.0.0",
    "publisher": "aios",
    "capability_type": "agent",

    # ── Domains ────────────────────────────────────
    "domains": [
        "desktop_automation",
        "browser_automation",
    ],

    # ── Entrypoint ─────────────────────────────────
    "entrypoint": "deskaoy.desktop_agent:DesktopAgent",

    # ── Supported actions ──────────────────────────
    "supported_actions": [
        "click",
        "fill",
        "type_text",
        "key_press",
        "scroll",
        "screenshot",
        "snapshot",
        "navigate",
        "automate",
        "orchestrate",
    ],

    # ── Action classes ─────────────────────────────
    "action_classes": [
        "read_only",
        "recoverable",
        "draftable",
        "sensitive",
        "external",
        "irreversible",
    ],

    # ── Permissions requested ──────────────────────
    "permissions": [
        "screen_capture",
        "accessibility_read",
        "keyboard_input",
        "mouse_input",
        "window_focus",
        "clipboard_read",
        "clipboard_write",
        "browser_navigation",
        "network_access",
    ],

    # ── Stealth (separate, policy-gated) ───────────
    "stealth_permissions": [
        "stealth_browser",
    ],

    # ── Runtime requirements ───────────────────────
    "runtime": {
        "process": "local_process",
        "sandbox": False,
        "requires_local_user_session": True,
        "requires_os_permissions": [
            "accessibility",
            "screen_capture",
            "input_injection",
        ],
        "optional_ml_runtime": [
            "ultralytics",
            "transformers",
            "paddleocr",
            "torch",
        ],
    },

    # ── Storage requirements ───────────────────────
    "storage": {
        "production_root": "AIOS_HOME/capabilities/aios.first_party.deskaoy/",
        "subareas": [
            "action-memory/",
            "checkpoints/",
            "artifacts/",
            "logs/",
            "temp/",
        ],
    },

    # ── Feature support ────────────────────────────
    "dry_run_support": True,
    "estimate_support": True,
    "undo_support": "best_effort",
    "compensation_support": True,
    "trace_support": "bridge",
    "receipt_support": "bridge",
    "policy_simulation_support": True,

    # ── Update compatibility ───────────────────────
    "update_policy": "aios_managed",
    "min_aios_version": "0.1.0",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_MANIFEST_KEYS = frozenset({
    "capability_id", "name", "version", "publisher", "capability_type",
    "domains", "entrypoint", "supported_actions", "action_classes",
    "permissions", "runtime", "storage",
})


def validate_manifest(manifest: dict[str, Any] | None = None) -> list[str]:
    """Validate a capability manifest. Returns list of errors (empty = valid)."""
    m = manifest if manifest is not None else CAPABILITY_MANIFEST
    errors: list[str] = []

    missing = REQUIRED_MANIFEST_KEYS - set(m.keys())
    if missing:
        errors.append(f"Missing required keys: {sorted(missing)}")

    if "capability_id" in m and not m["capability_id"].startswith(("aios.", "deskaoy")):
        errors.append(f"capability_id must start with 'aios.' or 'deskaoy', got: {m['capability_id']}")

    if "capability_type" in m and m["capability_type"] not in ("agent", "tool", "skill"):
        errors.append(f"Invalid capability_type: {m['capability_type']}")

    if "version" in m and not isinstance(m["version"], str):
        errors.append("version must be a string")

    if "domains" in m and not isinstance(m["domains"], list):
        errors.append("domains must be a list")

    if "permissions" in m and not isinstance(m["permissions"], list):
        errors.append("permissions must be a list")

    if "runtime" in m:
        rt = m["runtime"]
        if rt.get("sandbox", False):
            errors.append("Desktop automation must not claim sandbox")
        if not rt.get("requires_local_user_session", False):
            errors.append("Desktop automation must declare requires_local_user_session=True")

    if "storage" in m:
        st = m["storage"]
        if not st.get("production_root", "").startswith("AIOS_HOME"):
            errors.append("Production storage root must start with AIOS_HOME")

    return errors
