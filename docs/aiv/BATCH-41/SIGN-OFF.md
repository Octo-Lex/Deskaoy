BATCH-41 SIGN-OFF CERTIFICATE
═══════════════════════════════════════════════════════════

Batch ID:                 BATCH-41
Blueprint Version:        1.0 (inline — infrastructure batch)
Cycle Mode:               STANDARD
Lead Programmer:          Lead (Session 260520-apt-topaz)
Date Closed:              2026-05-21

───────────────────────────────────────────────────────────
INFRASTRUCTURE PROVISIONED
───────────────────────────────────────────────────────────

  Platform:         Proxmox VE 8.4.10
  Container:        CT 250 — desktop-agent-test
  OS:               Ubuntu 24.04 LTS
  IP:               192.168.3.152
  Resources:        4 cores, 4GB RAM, 32GB disk
  Desktop:          XFCE4 + Xvfb virtual display (:99)
  Installed:        at-spi2-core, python3-pyatspi, xdotool, wmctrl, gnome-calculator

───────────────────────────────────────────────────────────
SOURCE CHANGES
───────────────────────────────────────────────────────────

  File: src/agent_core/adapters/linux.py
  Change: Fixed AT-SPI2 Registry import — `import pyatspi` + `pyatspi.Registry`
          instead of `Atspi.Registry` (deprecated in newer GI bindings).
  Reason: Ubuntu 24.04's python3-pyatspi uses pyatspi.Registry, not gi.repository.

  File: tests/test_adapters/test_linux.py
  Change: Added `pyatspi` mock to _linux_modules() fixture.
  Reason: Tests mock sys.modules — need to include pyatspi since _ensure_imports()
          now imports it.

───────────────────────────────────────────────────────────
TEST RESULTS
───────────────────────────────────────────────────────────

  Windows:  549/549 passing, 0 failures
  Linux:    23/23 unit tests passing, 0 failures
  Linux:    E2E test PASSED (snapshot, screenshot, click, key_press, type_text)
  Total:    549 + E2E = all green

───────────────────────────────────────────────────────────
LEAD SIGN-OFF
───────────────────────────────────────────────────────────

  Decision:     ✅ APPROVED
  Lead:         Lead (260520-apt-topaz)
  Date:         2026-05-21

═══════════════════════════════════════════════════════════
