# API Key Management in Flash

## Overview

Flash endpoints use `RUNPOD_API_KEY` from environment variables for all remote function calls. Both Load-Balancer (LB) and Queue-Based (QB) endpoints follow the same pattern.

## PRD Requirements

**All endpoints (LB and QB) use `RUNPOD_API_KEY` from environment variable only.**

No request-context API keys. This simplifies the architecture and improves performance by:
- Reducing State Manager queries for local-only endpoints
- Avoiding per-request API key resolution overhead
- Eliminating subtask/concurrency API key threading complexity

## Architecture

### Build Time
Scanner analyzes FastAPI routes and `@remote` function calls to determine which endpoints make remote calls:

```python
# scanner.py
def _analyze_fastapi_routes_for_remote_calls(tree, routes, main_file, remote_function_names):
    """Detect if FastAPI routes call @remote functions."""
    # Walks AST to find function calls matching remote_function_names
```

Manifest includes `makes_remote_calls` flag per resource:

```json
{
  "resources": {
    "mothership": {
      "makes_remote_calls": true,  // Calls GPU worker
      "functions": [...]
    },
    "gpu_worker": {
      "makes_remote_calls": false,  // Terminal node
      "functions": [...]
    }
  }
}
```

### Deployment Time
API keys injected based on `makes_remote_calls` flag:

```python
# serverless.py::_do_deploy()
makes_remote_calls = self._check_makes_remote_calls()
if makes_remote_calls:
    env_dict["RUNPOD_API_KEY"] = os.getenv("RUNPOD_API_KEY")
    env_dict["FLASH_ENVIRONMENT_ID"] = os.getenv("FLASH_ENVIRONMENT_ID")
```

Resource names normalized (strip `-fb` suffix, `live-` prefix) to match manifest.

### Runtime
ServiceRegistry uses environment variables only:

```python
# service_registry.py::_ensure_manifest_loaded()
if not self._makes_remote_calls:
    return  # Skip State Manager query

api_key = os.getenv("RUNPOD_API_KEY")  // NOT from request context
full_manifest = await self._manifest_client.get_persisted_manifest(
    environment_id, api_key=api_key
)
```

### Preview Mode
CLI injects environment variables for container-to-container communication:

```python
# preview.py::_start_resource_container()
if makes_remote_calls:
    docker_cmd.extend(["-e", f"RUNPOD_API_KEY={api_key}"])
    docker_cmd.extend(["-e", f"FLASH_RESOURCES_ENDPOINTS={json.dumps(resources_endpoints)}"])
```

## PRD Scenarios

### Scenario 1: Mothership + GPU Worker

**Setup:** Mothership calls GPU worker for inference.

**Behavior:**
- Mothership: `makes_remote_calls=True` → Gets `RUNPOD_API_KEY`
- GPU worker: `makes_remote_calls=False` → No API key (local-only)

### Scenario 2: Chained Workers

**Setup:** Mothership → CPU worker → GPU worker

**Behavior:**
- Mothership: `makes_remote_calls=True` → Gets API key
- CPU worker: `makes_remote_calls=True` → Gets API key (calls GPU)
- GPU worker: `makes_remote_calls=False` → No API key (terminal)

### Scenario 3: Local-Only Mothership

**Setup:** Mothership with no `@remote` calls

**Behavior:**
- Mothership: `makes_remote_calls=False` → No API key
- **State Manager not queried** (performance optimization)
- No endpoint discovery overhead

## Implementation Files

| Component | File | Purpose |
|-----------|------|---------|
| **Build** | `scanner.py` | Analyze routes for remote calls |
| | `manifest.py` | Set `makes_remote_calls` flag |
| **Deploy** | `serverless.py` | Inject API keys at deployment |
| **Runtime** | `service_registry.py` | Env var only, conditional queries |
| | `models.py` | Manifest schema with `resources_endpoints` |
| **Preview** | `preview.py` | Docker env var injection |

## Testing

Integration tests validate all 3 PRD scenarios:

```bash
pytest tests/integration/test_prd_api_key_scenarios.py -v
```

**Tests:**
- API key injection for remote-calling endpoints
- No injection for local-only endpoints
- State Manager not queried for local-only
- Resource name normalization (`-fb`, `live-` prefixes)

## Troubleshooting

### Remote calls fail with 404

**Cause:** Endpoint doesn't have `RUNPOD_API_KEY` injected.

**Fix:** Verify manifest has `makes_remote_calls=True` for the endpoint.

### State Manager queries on local-only endpoint

**Cause:** Manifest incorrectly has `makes_remote_calls=True`.

**Fix:** Rebuild project to regenerate manifest with correct flags.

### API key not available in preview mode

**Cause:** `RUNPOD_API_KEY` not set in local environment.

**Fix:** Set environment variable before running `flash deploy --preview`.

## Migration Notes

**Breaking Change:** Endpoints no longer use request-context API keys.

**Action Required:** None for most users. All API keys now come from environment variables, which is the standard deployment pattern.

**Impact:**
- Simplified architecture
- Better performance (fewer State Manager queries)
- Consistent behavior across LB and QB endpoints
