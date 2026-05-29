# Desktop-Agent AI-OS Realignment Plan

## Goal

Convert Desktop-Agent into the first-party AI-OS desktop automation capability package.

## Non-goals

- Do not replace AI-OS kernel
- Do not own canonical AI-OS contracts
- Do not write production durable state outside AIOS_HOME
- Do not bypass AI-OS policy
- Do not make local logs authoritative over AI-OS tracing
- Do not silently enable stealth browser behavior
- Do not claim desktop automation is sandboxed

## Phase 1 — Identity and Manifest ✅

- [x] Capability manifest (`agent_core.manifest`)
- [x] AI-OS alignment docs (`docs/AIOS_ALIGNMENT.md`)
- [x] Compatibility matrix (`docs/AIOS_COMPATIBILITY_MATRIX.md`)
- [x] Capability manifest doc (`docs/AIOS_CAPABILITY_MANIFEST.md`)

## Phase 2 — Contract Alignment ✅

- [x] Mark local AI-OS-like types as compatibility shim (noted in compatibility matrix)
- [x] Add AI-OS SDK / contract mapping (compatibility matrix)
- [x] Manifest validation tests

## Phase 3 — AIOS_HOME Storage ✅

- [x] Storage resolver (`agent_core.storage`)
- [x] Production root under AIOS_HOME
- [x] Dev mode fallback with explicit flag
- [x] Tests for both modes

## Phase 4 — Policy Bridge ✅

- [x] Policy preflight hook (`agent_core.policy`)
- [x] Support allow / deny / ask / dry-run-only / degraded
- [x] Stealth disabled by default
- [x] Permission mapping per action
- [x] Tests for all effects

## Phase 5 — Trace Bridge ✅

- [x] AI-OS trace bridge (`agent_core.trace_bridge`)
- [x] Action span with full metadata
- [x] Diagnostic fallback when standalone
- [x] Tests for connected and diagnostic modes

## Phase 6 — Result Mapping ✅

- [x] Result mapper (`agent_core.result_mapper`)
- [x] Map ActionResult → AI-OS result/evidence shape
- [x] Structured error codes preserved
- [x] Sensitive data redaction
- [x] Dry-run never claims completion
- [x] Tests for success, failure, dry-run, redaction

## Phase 7 — Recovery Bridge ✅

- [x] Recovery bridge (`agent_core.recovery_bridge`)
- [x] Recovery events visible as events
- [x] Bounded by configurable max_attempts
- [x] Failure evidence emission
- [x] Policy can set attempt limits
- [x] Tests for all event types

## Remaining Phases

### Phase 8 — Action Memory Alignment ✅
- [x] Treat ActionMemory as capability learning evidence (`memory/learning.py`)
- [x] Add policy/review path (`apply_policy_to_evidence`)
- [x] Keep selector healing policy-bound
- [x] Wire AIOS_HOME into MemoryConfig default store_dir
- [x] Emit learning evidence on heal success

### Phase 9 — Package Separation ✅
- [x] Keep desktop automation core
- [x] Separate browser-basic and browser-stealth (`stealth_gate.py`)
- [x] Gate stealth with explicit policy
- [x] Add model artifact metadata for visual grounding (`grounding/artifacts.py`)

## Success Criteria

- [x] Desktop-Agent can register as `aios.first_party.desktop_agent`
- [x] Desktop-Agent exposes a valid capability manifest
- [x] Production state can be rooted under AIOS_HOME
- [x] Actions can be policy-preflighted
- [x] Actions can emit AI-OS trace/evidence metadata
- [x] Results map to AI-OS result/evidence structures
- [x] Recovery attempts are visible and bounded
- [x] Stealth is not enabled by default
- [x] Action memory is policy-bound (Phase 8)
- [x] Browser stealth is separated (Phase 9)
