# AI-OS Compatibility Matrix

| Desktop-Agent object | AI-OS contract object | Status | Mapping | Gap | Decision |
|---|---|---|---|---|---|
| DesktopAgent | First-party capability agent | Partial | Wrap as `aios.first_party.desktop_agent` | Must not act as kernel | Align as capability package |
| os_types.py | AI-OS SDK contract types | **Shim** | Temporary compatibility shim | Parallel contract authority | Replace against AI-OS SDK when available |
| SurfaceAdapter | Surface adapter contract | Strong | Keep abstraction | Needs policy/trace context | Add bridge methods |
| ActionResult | GUI action result contract | Strong | Map via result_mapper.py | Needs trace/policy IDs | Add mapper |
| ActionError | AI-OS error/evidence types | Strong | Map code/hint to AI-OS error shape | Partial coverage | Extend error catalog |
| FlowLogger | AI-OS TraceService | Partial | Diagnostic sink | Not authoritative | Add trace_bridge.py |
| ActionMemory | Capability learning evidence | Partial | Use as evidence | Must not bypass memory policy | Add policy/review path |
| CheckpointManager | AI-OS snapshot/rollback evidence | Partial | Use as local evidence | Not authoritative rollback | Delegate to AI-OS control plane |
| RecoveryCoordinator | AI-OS recovery event / step retry | Partial | Keep strategy | Invisible recovery loop risk | Add recovery_bridge.py |
| WindowsAdapter | Desktop surface adapter | Strong | Keep | Needs AI-OS storage/policy/trace bridge | Wrap with bridges |
| BrowserAdapter | Browser automation capability | Partial | Keep basic browser automation | Stealth risk | Split stealth capability |
| Visual grounding | Visual grounding provider | Strong | Keep optional provider | Artifact tracking required | Add model metadata |
| HookRegistry | AI-OS lifecycle hooks | Partial | Diagnostic hooks | Not authoritative lifecycle | Map to AI-OS events |
| PipelineExecutor | Deterministic action paths | Strong | Keep | Needs policy preflight | Add policy check before dispatch |
| StaleRefResolver | Element recovery strategy | Strong | Keep as internal strategy | No gap | N/A |
| SnapshotFormatter | Page state serializer | Strong | Keep as internal utility | No gap | N/A |
| ShapeInference | Data summarization | Strong | Keep as internal utility | No gap | N/A |
| ElectronAppRegistry | CDP app launcher | Strong | Keep | Needs policy for CDP launch | Add policy preflight |
