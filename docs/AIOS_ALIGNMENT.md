# AI-OS Alignment

## Positioning

Desktop-Agent is the **first-party AI-OS desktop automation capability package**.

It provides surface adapters, GUI action execution, visual grounding, verification, recovery strategies, and action memory evidence **under AI-OS policy and control-plane authority**.

## What Desktop-Agent is NOT

- Not an AI-OS kernel
- Not the authority for AI-OS contracts, policy, tracing, storage, approvals, receipts, updates, or registry activation
- Not a sandboxed runtime — desktop automation requires local user session access

## Authority Boundaries

| Owned by Desktop-Agent | Owned by AI-OS |
|------------------------|----------------|
| Surface adapters | Canonical contracts |
| GUI action execution | Policy decisions |
| Visual grounding | Approval decisions |
| Action verification | Durable run state |
| Recovery strategies | Trace/span authority |
| Action memory evidence | Signed events |
| Deterministic GUI pipelines | Receipts |
| | AIOS_HOME durable storage |
| | Update policy |
| | Registry/marketplace activation |

## Bridge Points

Desktop-Agent exposes integration bridges for AI-OS authority:

| Bridge | Module | Purpose |
|--------|--------|---------|
| **Policy** | `agent_core.policy` | Preflight GUI actions against AI-OS policy |
| **Trace** | `agent_core.trace_bridge` | Emit action spans to AI-OS TraceService |
| **Result** | `agent_core.result_mapper` | Map ActionResult → AI-OS result/evidence |
| **Recovery** | `agent_core.recovery_bridge` | Make recovery attempts visible and bounded |
| **Storage** | `agent_core.storage` | Root durable state under AIOS_HOME |
| **Manifest** | `agent_core.manifest` | Declare capability to AI-OS registry |

## Hard Rules

1. No production durable state outside AIOS_HOME
2. No GUI action bypasses AI-OS policy when running under AI-OS
3. AI-OS TraceService is authoritative; Desktop-Agent logs are diagnostic
4. No invisible unbounded recovery loops
5. Action memory is evidence, not authoritative user memory
6. Visual models require artifact metadata
7. Stealth automation is separated and policy-gated
8. Desktop automation is not a sandbox
