# Design: Deployment and Cross-Endpoint Communication

> **Status: Completed.** Mothership-to-peer terminology migration is done. `FLASH_IS_MOTHERSHIP` removed; `FLASH_ENDPOINT_TYPE=lb` is the sole mechanism. Content below is the original design document preserved as historical record.

> Refined from PRD.md through brainstorming session on 2026-02-20.
> Canonical PRD: [PRD.md](../../PRD.md)

## Context

Flash has evolved to a peer-to-peer endpoint model. The architecture — manifest-driven routing, ServiceRegistry, State Manager as source of truth — is largely in place. Four concrete gaps remain between the current implementation and full deployment functionality.

## Success Criteria

Deploy every example in flash-examples to RunPod, execute their workflows in the deployed environment, and confirm they all complete without errors.

| Example | Type | Cross-Remote | Deployment Test |
|---------|------|--------------|-----------------|
| 00_standalone_worker | QB | No | Deploy QB, invoke /runsync, get result |
| 00_multi_resource | QB + LB | Yes | Deploy 2 QB + 1 LB, LB orchestrates both QB workers |
| 01_hello_world | QB | No | Deploy QB, invoke, get GPU info |
| 02_cpu_worker | QB | No | Deploy QB, invoke, get CPU info |
| 03_mixed_workers | QB + LB | Yes | Deploy 2 QB + 1 LB, pipeline runs CPU->GPU->CPU |
| 04_dependencies | QB | No | Deploy QB, invoke with deps installed |
| 01_text_to_speech | QB | No | Deploy QB, generate audio |
| 05_load_balancer | LB | No | Deploy 2 LB endpoints, test all HTTP methods |
| 01_network_volumes | QB + LB | No | Deploy QB + LB with shared volume, generate and list images |

## Architecture Principles

- All endpoints are peers. No hub-and-spoke, no coordinator.
- QB endpoints: standard RunPod queue (/run, /runsync).
- LB endpoints: web server with user-defined HTTP routes served directly.
- CloudPickle used only for `flash run` local dev (LiveServerless). Deployed environments use JSON-only.
- Manifest flags (`is_load_balanced`, `makes_remote_calls`) drive provisioning decisions.
- State Manager is source of truth for service discovery.

## Gap Analysis

### Gap 1: Remove CloudPickle from Deployed Cross-Endpoint Communication

**Problem:** flash-worker uses cloudpickle+base64 serialization for cross-endpoint calls in deployed environments.

**Solution:** Deployed cross-endpoint calls use plain JSON. CloudPickle stays for `flash run` only.

**Repositories affected:** flash-worker (`remote_executor.py`, `serialization_utils.py`), flash (`stubs/load_balancer_sls.py`, `runtime/production_wrapper.py`)

**Verification:** `00_multi_resource` and `03_mixed_workers` cross-endpoint calls succeed with JSON payloads.

### Gap 2: Flash-Worker LB Handler Terminology and Mode Cleanup

**Problem:** `lb_handler.py` uses `FLASH_IS_MOTHERSHIP` to toggle between LB mode (import user FastAPI app) and QB mode. Naming contradicts peer model.

**Solution:** Rename to peer-appropriate env var (e.g., `FLASH_ENDPOINT_TYPE=lb`). Same mechanism, new naming. Legacy `FLASH_IS_MOTHERSHIP` accepted with deprecation warning during transition.

**Repositories affected:** flash-worker (`lb_handler.py`, `constants.py`, `unpack_volume.py`, tests), flash (`runtime/mothership_provisioner.py`, deployment pipeline)

**Verification:** All LB examples deploy and serve user-defined routes under the new naming.

### Gap 3: Deployment Pipeline: Populate Endpoint URLs Post-Provisioning

**Problem:** After provisioning, endpoint URLs are not written back into the manifest. Peer endpoints cannot discover each other.

**Solution:** After all endpoints are provisioned, collect URLs, build `resources_endpoints` mapping, push completed manifest to State Manager.

**Repositories affected:** flash (`core/deployment.py`, `cli/commands/build_utils/manifest.py`, `runtime/state_manager_client.py`)

**Verification:** After `flash deploy`, State Manager contains manifest with all endpoint URLs. Cross-endpoint examples resolve peers.

### Gap 4: Selective RUNPOD_API_KEY Injection

**Problem:** `RUNPOD_API_KEY` is not selectively injected based on `makes_remote_calls` flag. Violates least privilege.

**Solution:** Deployment pipeline checks `makes_remote_calls` per resource. Inject key only where needed. Fail early if key is missing but required.

**Repositories affected:** flash (deployment pipeline only). flash-worker needs no changes.

**Verification:** Remote-calling endpoints have key, others do not. Cross-endpoint calls succeed.

## Cross-Cutting Concerns

- **Backward compatibility:** `FLASH_IS_MOTHERSHIP` accepted during transition with deprecation warning.
- **Error handling:** Missing API key fails deployment early. State Manager unavailability retries with backoff.
- **Testing:** Unit tests per gap, integration tests deploying each flash-example, regression for `flash run` local dev.

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Gap-driven PRD structure | Architecture is mostly implemented; gaps map directly to work items |
| Keep cloudpickle for flash run | Local dev convenience outweighs consistency; deployed env is the contract |
| Minimal manifest changes | Current schema already has the right fields; just need pipeline to populate them |
| Extend current DeploymentOrchestrator | Working provisioning pipeline; add URL collection as post-provisioning step |
| Selective API key injection | Least privilege; reduces attack surface on endpoints that don't need it |
