# PRD: Deployment and Cross-Endpoint Communication

## Context

Flash has evolved to a peer-to-peer endpoint model. The architecture — manifest-driven routing, ServiceRegistry, State Manager as source of truth — is largely in place. This PRD defines the remaining gaps between the current implementation and full deployment functionality.

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

- All endpoints in a flash application are peers. No hub-and-spoke, no coordinator.
- QB endpoints: standard RunPod queue. POST to /run or /runsync creates a job.
- LB endpoints: web server with user-defined HTTP routes served directly.
- CloudPickle is used only for `flash run` local dev (LiveServerless). Deployed environments use JSON-only payloads.
- Manifest determines endpoint behavior: `is_load_balanced` and `makes_remote_calls` flags drive provisioning decisions.
- State Manager is the source of truth for service discovery in deployed environments.

---

## Gap 1: Remove CloudPickle from Deployed Cross-Endpoint Communication

### Current State

Flash-worker's `remote_executor.py` uses `serialization_utils.py` (cloudpickle + base64) to serialize function arguments and results for cross-endpoint calls in deployed environments. This couples endpoints to Python-specific binary serialization.

### Target State

Deployed cross-endpoint calls use plain JSON. CloudPickle remains only for `flash run` local dev (LiveServerless stubs).

### Changes

**flash-worker:**
- `remote_executor.py`: When routing to a remote endpoint, send JSON payloads instead of cloudpickle-serialized args.
- `serialization_utils.py`: Keep for backward compatibility with LiveServerless, but deployed code paths bypass it.
- QB handler path: Arguments arrive as JSON from RunPod queue, stay JSON when forwarded cross-endpoint.
- LB handler path: Arguments arrive as JSON from HTTP request, stay JSON when forwarded.

**flash (core library):**
- `stubs/load_balancer_sls.py`: Deployed mode already sends JSON to user-defined routes. Confirm no cloudpickle leakage in deployed path.
- `runtime/production_wrapper.py`: Ensure cross-endpoint routing uses JSON serialization in deployed context.

### Affected Examples

- `00_multi_resource` (LB calls 2 QB workers)
- `03_mixed_workers` (LB orchestrates CPU->GPU->CPU pipeline)

### Acceptance Criteria

- Cross-endpoint calls in deployed environments use JSON-only payloads.
- No cloudpickle imports executed in deployed code paths.
- `flash run` local dev still works with cloudpickle for LiveServerless.

---

## Gap 2: Flash-Worker LB Handler Terminology and Mode Cleanup

### Current State

Flash-worker's `lb_handler.py` has two modes controlled by `FLASH_IS_MOTHERSHIP=true`:

- **Mothership mode**: Dynamically imports user's FastAPI app, serves all routes directly, adds `/ping` health check.
- **Queue-based mode**: Creates a generic `/execute` endpoint for child endpoints using `RemoteExecutor` with cloudpickle.

The mothership mode mechanism is correct for LB endpoints (imports user's FastAPI app and serves routes), but the naming contradicts the peer model.

### Target State

Same two modes, reframed for the peer architecture:

- **LB endpoint mode** (was mothership): Imports user's FastAPI app and serves routes. Triggered by manifest metadata (`is_load_balanced: true`), not a "mothership" flag.
- **QB endpoint mode**: Standard RunPod queue handler. Processes jobs from /run and /runsync. The `/execute` endpoint stays only for `flash run` local dev (LiveServerless).

### Changes

**flash-worker:**
- `lb_handler.py`: Rename `FLASH_IS_MOTHERSHIP` references to a peer-appropriate env var (e.g., `FLASH_ENDPOINT_TYPE=lb` or derive from manifest's `is_load_balanced`).
- `constants.py`: Update mothership references.
- `unpack_volume.py`: Update detection logic for the renamed env var.
- Tests: Update all mothership references in test files.

**flash (core library):**
- `runtime/mothership_provisioner.py`: Rename or refactor. This file does reconciliation logic, not mothership-specific work. The env vars it sets during deployment need updating.
- Deployment pipeline: Set the renamed env var instead of `FLASH_IS_MOTHERSHIP`.

### Affected Examples

- `05_load_balancer` (pure LB endpoints)
- `00_multi_resource` (mixed QB + LB)
- `03_mixed_workers` (LB orchestration)
- `01_network_volumes` (QB + LB with shared volume)

### Acceptance Criteria

- No "mothership" terminology in new code paths (legacy compat shim acceptable during transition).
- LB endpoints correctly import and serve user FastAPI routes using the renamed mechanism.
- QB endpoints process jobs from RunPod queue without the `/execute` cloudpickle path.
- All LB examples deploy and respond to their defined HTTP routes.

---

## Gap 3: Deployment Pipeline: Populate Endpoint URLs Post-Provisioning

### Current State

`DeploymentOrchestrator` provisions endpoints via RunPod API and `ResourceManager` tracks deployed resources in `.runpod/resources.pkl` with endpoint IDs and config hashes. However, after provisioning, endpoint URLs are not written back into the manifest for peer discovery. `StateManagerClient` can persist manifest data to State Manager, but the deployment pipeline does not populate `resources_endpoints` (the resource-name-to-URL mapping) after all endpoints are provisioned.

### Target State

After all endpoints in a flash application are provisioned, the deployment pipeline:

1. Collects endpoint URLs for every provisioned resource.
2. Populates the `resources_endpoints` mapping in the manifest.
3. Pushes the completed manifest to State Manager so any endpoint making remote calls can discover its peers.

### Changes

**flash (core library):**
- `core/deployment.py` (`DeploymentOrchestrator`): After provisioning all resources, collect endpoint URLs from RunPod API responses and build the `resources_endpoints` map.
- `cli/commands/build_utils/manifest.py`: Ensure the manifest schema supports `resources_endpoints` at the top level (may already exist in runtime models).
- `runtime/state_manager_client.py`: Verify the `update_resource_state` method can persist the completed manifest with endpoint URLs.
- Deploy CLI command: After orchestration completes, push the finalized manifest (with URLs) to State Manager.

### Sequencing

All endpoints must be provisioned before the manifest is finalized, because URLs are not known until provisioning completes:

1. Provision all endpoints (parallel, as today).
2. Collect all endpoint URLs.
3. Build `resources_endpoints` mapping.
4. Push completed manifest to State Manager.

### Affected Examples

- `00_multi_resource` (LB needs to know QB endpoint URLs)
- `03_mixed_workers` (LB needs CPU and GPU endpoint URLs)
- Any future example with cross-endpoint calls

### Acceptance Criteria

- After `flash deploy`, State Manager contains a manifest with all endpoint URLs populated.
- Endpoints making remote calls can query State Manager and resolve peer endpoint URLs.
- Endpoints not making remote calls still deploy correctly (they do not need the URL mapping).

---

## Gap 4: Selective RUNPOD_API_KEY Injection

### Current State

`RUNPOD_API_KEY` is required for State Manager queries and for making RunPod API calls to peer endpoints. The deployment pipeline does not selectively inject this key based on the `makes_remote_calls` manifest flag. Endpoints that do not make remote calls should not need the key (reduces attack surface, follows least privilege).

### Target State

During deployment, the pipeline inspects each resource's `makes_remote_calls` flag. Endpoints that make remote calls get `RUNPOD_API_KEY` injected. Endpoints that do not make remote calls skip it.

### Changes

**flash (core library):**
- Deployment pipeline: When provisioning each endpoint, check `makes_remote_calls` in the resource's manifest entry.
  - If `true`: inject `RUNPOD_API_KEY` as an env var on the RunPod endpoint.
  - If `false`: skip injection.
- The key value comes from the user's local environment (already required for `flash deploy` to work).

**flash-worker:**
- No changes needed. `ServiceRegistry` already uses `RUNPOD_API_KEY` when present and skips State Manager queries when absent.

### Affected Examples

- `00_multi_resource`: LB endpoint makes remote calls (gets key), QB endpoints do not (skip key).
- `03_mixed_workers`: LB orchestrator makes remote calls (gets key), CPU/GPU workers do not (skip key).
- All other examples: No remote calls, no key needed.

### Acceptance Criteria

- Endpoints with `makes_remote_calls: true` have `RUNPOD_API_KEY` available at runtime.
- Endpoints with `makes_remote_calls: false` do not have `RUNPOD_API_KEY` injected.
- Cross-endpoint calls from LB orchestrators to QB workers succeed using the injected key.
- Deployment fails with a clear error if `RUNPOD_API_KEY` is not set locally but the manifest contains endpoints that make remote calls.

---

## Cross-Cutting Concerns

### Backward Compatibility

- `FLASH_IS_MOTHERSHIP` env var: Accept during transition period, log deprecation warning.
- CloudPickle in `flash run`: No changes. Local dev continues to use cloudpickle for LiveServerless.

### Error Handling

- Missing `RUNPOD_API_KEY` during deployment when remote calls are needed: Fail early with actionable message.
- State Manager unreachable during manifest push: Retry with backoff, fail deployment if persistent.
- Endpoint URL unavailable at cold start for remote-calling endpoint: ServiceRegistry already handles this with 300s cache TTL and State Manager query.

### Testing Strategy

- Unit tests: Each gap has isolated tests for the changed code paths.
- Integration tests: Deploy each flash-example and run its workflow end-to-end.
- Regression: `flash run` local dev must continue working unchanged.
