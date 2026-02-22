# Deployment and Cross-Endpoint Communication Implementation Plan

> **Status: Completed.** Mothership-to-peer terminology migration is done. `FLASH_IS_MOTHERSHIP` removed; `FLASH_ENDPOINT_TYPE=lb` is the sole mechanism. Content below is the original implementation plan preserved as historical record.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close four deployment gaps so every flash-example deploys and runs on RunPod without errors.

**Architecture:** Extend the existing peer-to-peer model. Rename mothership terminology, switch deployed cross-endpoint serialization from cloudpickle to JSON, verify endpoint URL population in deployment pipeline, and inject RUNPOD_API_KEY selectively based on `makes_remote_calls`.

**Tech Stack:** Python 3.11+, Pydantic, FastAPI, asyncio, aiohttp, RunPod GraphQL API

**Repositories:**
- `flash` — `/Users/deanquinanola/Github/python/flash-project/flash/main/`
- `flash-worker` — `/Users/deanquinanola/Github/python/flash-project/flash-worker/main/`

---

## Phase 1: Terminology Rename (Gap 2)

Rename `FLASH_IS_MOTHERSHIP` to `FLASH_ENDPOINT_TYPE` across both repos. Accept legacy env var with deprecation warning.

### Task 1: flash-worker — Rename env var in lb_handler.py

**Files:**
- Modify: `flash-worker: src/lb_handler.py`
- Test: `flash-worker: tests/unit/test_lb_handler.py`

**Step 1: Write failing test for new env var**

```python
# In test_lb_handler.py - add test for new env var
def test_lb_mode_uses_flash_endpoint_type(monkeypatch, tmp_path):
    """FLASH_ENDPOINT_TYPE=lb triggers LB mode."""
    monkeypatch.setenv("FLASH_ENDPOINT_TYPE", "lb")
    monkeypatch.delenv("FLASH_IS_MOTHERSHIP", raising=False)
    # Verify is_lb_endpoint resolves to True
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/deanquinanola/Github/python/flash-project/flash-worker/main && make quality-check`
Expected: FAIL — `FLASH_ENDPOINT_TYPE` not recognized

**Step 3: Update lb_handler.py**

Replace line 46:
```python
# Before
is_mothership = os.getenv("FLASH_IS_MOTHERSHIP") == "true"

# After
def _is_lb_endpoint() -> bool:
    """Determine if this endpoint runs in LB mode (serves user FastAPI routes)."""
    if os.getenv("FLASH_ENDPOINT_TYPE") == "lb":
        return True
    # Backward compatibility: accept legacy env var
    if os.getenv("FLASH_IS_MOTHERSHIP") == "true":
        logger.warning(
            "FLASH_IS_MOTHERSHIP is deprecated. Use FLASH_ENDPOINT_TYPE=lb instead."
        )
        return True
    return False

is_lb_endpoint = _is_lb_endpoint()
```

Replace all `is_mothership` references with `is_lb_endpoint` (lines 48, 54, 84, 88, 105).

Replace `ping_mothership` function name with `ping_lb` (line 84).

Replace `"endpoint": "mothership"` with `"endpoint": "lb"` (line 88).

Replace log messages:
- Line 54: `"Mothership mode:"` → `"LB endpoint mode:"`
- Line 95: `"Failed to initialize mothership mode:"` → `"Failed to initialize LB endpoint mode:"`
- Line 101: `"Queue-based mode:"` → `"QB endpoint mode:"`

Update module docstring (lines 1-20) to remove mothership terminology.

**Step 4: Run tests**

Run: `cd /Users/deanquinanola/Github/python/flash-project/flash-worker/main && make quality-check`
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash-worker/main
git add src/lb_handler.py tests/unit/test_lb_handler.py
git commit -m "refactor: rename FLASH_IS_MOTHERSHIP to FLASH_ENDPOINT_TYPE in lb_handler"
```

### Task 2: flash-worker — Rename env var in manifest_reconciliation.py

**Files:**
- Modify: `flash-worker: src/manifest_reconciliation.py:24-37`
- Modify: `flash-worker: src/constants.py:49-52`
- Test: `flash-worker: tests/unit/test_manifest_reconciliation.py`

**Step 1: Write failing test**

```python
def test_is_flash_deployment_with_endpoint_type(monkeypatch):
    """FLASH_ENDPOINT_TYPE is recognized as Flash deployment."""
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "test-123")
    monkeypatch.setenv("FLASH_ENDPOINT_TYPE", "lb")
    monkeypatch.delenv("FLASH_IS_MOTHERSHIP", raising=False)
    monkeypatch.delenv("FLASH_RESOURCE_NAME", raising=False)
    assert is_flash_deployment() is True
```

**Step 2: Run test — expect FAIL**

**Step 3: Update is_flash_deployment()**

```python
def is_flash_deployment() -> bool:
    """Check if running in Flash deployment mode."""
    endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID")
    is_flash = any(
        [
            os.getenv("FLASH_ENDPOINT_TYPE") in ("lb", "qb"),
            os.getenv("FLASH_IS_MOTHERSHIP") == "true",  # backward compat
            os.getenv("FLASH_RESOURCE_NAME"),
        ]
    )
    return bool(endpoint_id and is_flash)
```

Update `constants.py` lines 49-52: replace "mothership" in comments with "LB endpoint".

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
git add src/manifest_reconciliation.py src/constants.py tests/unit/test_manifest_reconciliation.py
git commit -m "refactor: recognize FLASH_ENDPOINT_TYPE in flash deployment detection"
```

### Task 3: flash — Rename env vars in mothership_provisioner.py

**Files:**
- Modify: `flash: src/runpod_flash/runtime/mothership_provisioner.py:276-295`
- Test: `flash: tests/` (relevant provisioner tests)

**Step 1: Write failing test**

```python
def test_create_resource_sets_endpoint_type_for_lb():
    """LB resources get FLASH_ENDPOINT_TYPE=lb instead of FLASH_IS_MOTHERSHIP."""
    resource_data = {"is_mothership": True, "resource_type": "LiveLoadBalancer", ...}
    resource = create_resource_from_manifest("test_lb", resource_data)
    assert resource.env.get("FLASH_ENDPOINT_TYPE") == "lb"
    # Backward compat: also sets legacy var
    assert resource.env.get("FLASH_IS_MOTHERSHIP") == "true"
```

**Step 2: Run test — expect FAIL**

**Step 3: Update create_resource_from_manifest() at lines 289-295**

```python
# Before
if resource_data.get("is_mothership"):
    env["FLASH_IS_MOTHERSHIP"] = "true"

# After
if resource_data.get("is_mothership") or resource_data.get("is_load_balanced"):
    env["FLASH_ENDPOINT_TYPE"] = "lb"
    env["FLASH_IS_MOTHERSHIP"] = "true"  # backward compat during transition
    if "main_file" in resource_data:
        env["FLASH_MAIN_FILE"] = resource_data["main_file"]
    if "app_variable" in resource_data:
        env["FLASH_APP_VARIABLE"] = resource_data["app_variable"]
```

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add src/runpod_flash/runtime/mothership_provisioner.py tests/
git commit -m "refactor: set FLASH_ENDPOINT_TYPE=lb alongside legacy FLASH_IS_MOTHERSHIP"
```

### Task 4: flash-worker — Update remaining mothership references and tests

**Files:**
- Modify: `flash-worker: src/unpack_volume.py` (comments only, logic uses is_flash_deployment())
- Modify: `flash-worker: tests/unit/test_unpack_volume.py` (update FLASH_IS_MOTHERSHIP tests)
- Modify: `flash-worker: tests/unit/test_manifest_reconciliation.py` (update mothership tests)
- Modify: `flash-worker: tests/integration/test_manifest_state_manager.py` (update mothership tests)

**Step 1: Update test_unpack_volume.py**

For each test that sets `FLASH_IS_MOTHERSHIP=true`, add a parallel test using `FLASH_ENDPOINT_TYPE=lb`. Keep legacy tests as regression.

**Step 2: Update test_manifest_reconciliation.py**

Same approach: add parallel tests with new env var, keep legacy tests.

**Step 3: Run `make quality-check` — expect PASS**

**Step 4: Commit**

```bash
git add src/ tests/
git commit -m "refactor: add FLASH_ENDPOINT_TYPE tests alongside legacy mothership tests"
```

---

## Phase 2: Selective API Key Injection (Gap 4)

### Task 5: flash — Inject RUNPOD_API_KEY based on makes_remote_calls

**Files:**
- Modify: `flash: src/runpod_flash/runtime/mothership_provisioner.py:276-295`
- Test: `flash: tests/` (provisioner tests)

**Step 1: Write failing test**

```python
def test_create_resource_injects_api_key_when_makes_remote_calls(monkeypatch):
    """Resources with makes_remote_calls=true get RUNPOD_API_KEY."""
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key-123")
    resource_data = {"makes_remote_calls": True, "resource_type": "ServerlessResource", ...}
    resource = create_resource_from_manifest("test_worker", resource_data)
    assert resource.env.get("RUNPOD_API_KEY") == "test-key-123"

def test_create_resource_skips_api_key_when_no_remote_calls(monkeypatch):
    """Resources with makes_remote_calls=false do not get RUNPOD_API_KEY."""
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key-123")
    resource_data = {"makes_remote_calls": False, "resource_type": "ServerlessResource", ...}
    resource = create_resource_from_manifest("test_worker", resource_data)
    assert "RUNPOD_API_KEY" not in resource.env
```

**Step 2: Run test — expect FAIL**

**Step 3: Add API key injection in create_resource_from_manifest()**

After the existing env var block (around line 295), add:

```python
# Inject RUNPOD_API_KEY for endpoints that make remote calls
if resource_data.get("makes_remote_calls", False):
    api_key = os.getenv("RUNPOD_API_KEY")
    if api_key:
        env["RUNPOD_API_KEY"] = api_key
```

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add src/runpod_flash/runtime/mothership_provisioner.py tests/
git commit -m "feat: inject RUNPOD_API_KEY selectively based on makes_remote_calls flag"
```

### Task 6: flash — Validate API key presence during deployment

**Files:**
- Modify: `flash: src/runpod_flash/cli/utils/deployment.py` (in reconcile_and_provision_resources)
- Test: `flash: tests/` (deployment tests)

**Step 1: Write failing test**

```python
async def test_deploy_fails_when_api_key_missing_for_remote_calls():
    """Deployment fails early if RUNPOD_API_KEY missing but resources make remote calls."""
    manifest = {
        "resources": {
            "orchestrator": {"makes_remote_calls": True, ...},
        },
        ...
    }
    with pytest.raises(ValueError, match="RUNPOD_API_KEY"):
        await reconcile_and_provision_resources(app, "build-1", "prod", manifest)
```

**Step 2: Run test — expect FAIL**

**Step 3: Add validation in reconcile_and_provision_resources()**

Early in the function, before provisioning begins:

```python
# Validate RUNPOD_API_KEY is available if any resource makes remote calls
has_remote_callers = any(
    config.get("makes_remote_calls", False)
    for config in local_manifest.get("resources", {}).values()
)
if has_remote_callers and not os.getenv("RUNPOD_API_KEY"):
    raise ValueError(
        "RUNPOD_API_KEY environment variable is required when deploying "
        "resources that make remote calls. Set it in your environment "
        "before running flash deploy."
    )
```

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add src/runpod_flash/cli/utils/deployment.py tests/
git commit -m "feat: validate RUNPOD_API_KEY presence when resources make remote calls"
```

---

## Phase 3: Endpoint URL Population Verification (Gap 3)

The deployment pipeline in `cli/utils/deployment.py:280-346` already:
1. Extracts `endpoint_url` from deployed resources (line 305)
2. Populates `resources_endpoints` dict (line 310)
3. Writes manifest to local file (line 339)
4. Pushes manifest to State Manager (line 344)

This phase verifies correctness and adds type safety.

### Task 7: flash — Add resources_endpoints to Manifest dataclass

**Files:**
- Modify: `flash: src/runpod_flash/runtime/models.py:40-74`
- Test: `flash: tests/` (model tests)

**Step 1: Write failing test**

```python
def test_manifest_from_dict_includes_resources_endpoints():
    """Manifest.from_dict() parses resources_endpoints field."""
    data = {
        "version": "1.0",
        "generated_at": "2026-01-01",
        "project_name": "test",
        "function_registry": {"func_a": "resource_1"},
        "resources": {"resource_1": {"resource_type": "ServerlessResource", "functions": []}},
        "resources_endpoints": {"resource_1": "https://abc123.runpod.io"},
    }
    manifest = Manifest.from_dict(data)
    assert manifest.resources_endpoints == {"resource_1": "https://abc123.runpod.io"}

def test_manifest_to_dict_includes_resources_endpoints():
    """Manifest.to_dict() includes resources_endpoints when present."""
    manifest = Manifest(
        version="1.0",
        generated_at="2026-01-01",
        project_name="test",
        function_registry={},
        resources={},
        resources_endpoints={"r1": "https://example.com"},
    )
    result = manifest.to_dict()
    assert result["resources_endpoints"] == {"r1": "https://example.com"}
```

**Step 2: Run test — expect FAIL**

**Step 3: Add field to Manifest dataclass**

```python
@dataclass
class Manifest:
    """Type-safe manifest structure."""

    version: str
    generated_at: str
    project_name: str
    function_registry: Dict[str, str]
    resources: Dict[str, ResourceConfig]
    routes: Optional[Dict[str, Dict[str, str]]] = None
    resources_endpoints: Optional[Dict[str, str]] = None  # NEW

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Manifest":
        """Load Manifest from JSON dict."""
        resources = {}
        for resource_name, resource_data in data.get("resources", {}).items():
            resources[resource_name] = ResourceConfig.from_dict(resource_data)

        return cls(
            version=data.get("version", "1.0"),
            generated_at=data.get("generated_at", ""),
            project_name=data.get("project_name", ""),
            function_registry=data.get("function_registry", {}),
            resources=resources,
            routes=data.get("routes"),
            resources_endpoints=data.get("resources_endpoints"),  # NEW
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = asdict(self)
        if result.get("routes") is None:
            result.pop("routes", None)
        if result.get("resources_endpoints") is None:
            result.pop("resources_endpoints", None)  # NEW
        return result
```

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add src/runpod_flash/runtime/models.py tests/
git commit -m "feat: add resources_endpoints field to Manifest dataclass"
```

### Task 8: flash — Write integration test for URL population

**Files:**
- Test: `flash: tests/integration/test_deployment_url_population.py` (new)

**Step 1: Write test verifying the deployment pipeline populates URLs**

```python
"""Test that reconcile_and_provision_resources populates resources_endpoints."""

async def test_resources_endpoints_populated_after_provisioning(mock_app, mock_resource_manager):
    """After provisioning, resources_endpoints contains all endpoint URLs."""
    manifest = {
        "resources": {
            "gpu_worker": {"resource_type": "ServerlessResource", ...},
            "api": {"resource_type": "LiveLoadBalancer", ...},
        },
        "function_registry": {...},
    }

    # Mock resource_manager to return resources with endpoint_url
    mock_resource_manager.get_or_deploy_resource.side_effect = [
        MockResource(endpoint_url="https://gpu.runpod.io"),
        MockResource(endpoint_url="https://api.runpod.io"),
    ]

    result = await reconcile_and_provision_resources(mock_app, "build-1", "prod", manifest)

    assert result == {
        "gpu_worker": "https://gpu.runpod.io",
        "api": "https://api.runpod.io",
    }

async def test_state_manager_receives_manifest_with_urls(mock_app, mock_resource_manager):
    """State Manager receives the manifest with resources_endpoints populated."""
    # ... assert app.update_build_manifest was called with manifest containing resources_endpoints
```

**Step 2: Run test — verify behavior**

**Step 3: Fix any issues found**

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add tests/
git commit -m "test: add integration tests for endpoint URL population in deployment"
```

---

## Phase 4: Remove CloudPickle from Deployed Paths (Gap 1)

### Task 9: flash — Add serialization_format to FunctionRequest/Response

**Files:**
- Modify: `flash: src/runpod_flash/protos/remote_execution.py:13-147`
- Test: `flash: tests/` (proto tests)

**Step 1: Write failing test**

```python
def test_function_request_supports_json_serialization_format():
    """FunctionRequest accepts serialization_format='json'."""
    req = FunctionRequest(
        function_name="test_func",
        serialization_format="json",
        args=[{"key": "value"}, 42],
        kwargs={"param": "hello"},
    )
    assert req.serialization_format == "json"
    assert req.args == [{"key": "value"}, 42]

def test_function_request_defaults_to_cloudpickle():
    """FunctionRequest defaults to cloudpickle for backward compat."""
    req = FunctionRequest(function_name="test_func")
    assert req.serialization_format == "cloudpickle"
```

**Step 2: Run test — expect FAIL**

**Step 3: Update FunctionRequest and FunctionResponse**

In `protos/remote_execution.py`:

1. Change `args: List[str]` → `args: List[Any]`
2. Change `kwargs: Dict[str, str]` → `kwargs: Dict[str, Any]`
3. Add `serialization_format` field:

```python
serialization_format: str = Field(
    default="cloudpickle",
    description="Serialization format: 'json' for plain JSON, 'cloudpickle' for base64-encoded cloudpickle",
)
```

4. Same changes for `constructor_args` and `constructor_kwargs` if needed.

5. Add `json_result` to FunctionResponse:

```python
json_result: Optional[Any] = Field(
    default=None,
    description="Plain JSON result (used when serialization_format='json')",
)
```

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add src/runpod_flash/protos/remote_execution.py tests/
git commit -m "feat: add JSON serialization format support to FunctionRequest/Response"
```

### Task 10: flash — Update ProductionWrapper to use JSON serialization

**Files:**
- Modify: `flash: src/runpod_flash/runtime/production_wrapper.py:155-201`
- Test: `flash: tests/` (production_wrapper tests)

**Step 1: Write failing test**

```python
async def test_execute_remote_uses_json_serialization():
    """_execute_remote sends args as plain JSON, not cloudpickle."""
    wrapper = ProductionWrapper(mock_registry)
    mock_resource = MockServerlessResource()

    await wrapper._execute_remote(
        mock_resource, "my_func", ({"data": "value"},), {"key": 42}
    )

    # Verify payload uses JSON format
    call_args = mock_resource.run_sync.call_args
    payload = call_args[0][0]
    assert payload["input"]["serialization_format"] == "json"
    assert payload["input"]["args"] == [{"data": "value"}]
    assert payload["input"]["kwargs"] == {"key": 42}
```

**Step 2: Run test — expect FAIL**

**Step 3: Update _execute_remote()**

```python
async def _execute_remote(
    self,
    resource: ServerlessResource,
    function_name: str,
    args: tuple,
    kwargs: dict,
    execution_type: str = "function",
) -> Any:
    """Execute function on remote endpoint using JSON serialization."""
    # Build payload with plain JSON args (no cloudpickle in deployed paths)
    payload = {
        "input": {
            "function_name": function_name,
            "execution_type": execution_type,
            "serialization_format": "json",
            "args": list(args),
            "kwargs": kwargs,
        }
    }

    result = await resource.run_sync(payload)

    if result.error:
        raise RemoteExecutionError(
            f"Remote execution of {function_name} failed: {result.error}"
        )

    return result.output
```

Remove imports of `serialize_args` and `serialize_kwargs` from `runtime.serialization` (line 9) if no longer used elsewhere in this file.

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add src/runpod_flash/runtime/production_wrapper.py tests/
git commit -m "feat: use JSON serialization for deployed cross-endpoint calls"
```

### Task 11: flash-worker — Update RemoteExecutor to handle JSON args

**Files:**
- Modify: `flash-worker: src/remote_executor.py:338-408`
- Test: `flash-worker: tests/unit/test_remote_executor.py`

**Step 1: Write failing test**

```python
async def test_execute_flash_function_with_json_args():
    """Flash functions receive JSON args when serialization_format='json'."""
    request = FunctionRequest(
        function_name="my_func",
        serialization_format="json",
        args=[{"data": "value"}],
        kwargs={"key": 42},
    )
    executor = RemoteExecutor()
    result = await executor._execute_flash_function(request)
    # Verify the function received the raw Python values, not cloudpickle-decoded
    assert result.success is True

async def test_execute_flash_function_json_result():
    """Flash functions return JSON result when serialization_format='json'."""
    request = FunctionRequest(
        function_name="my_func",
        serialization_format="json",
        args=[],
        kwargs={},
    )
    executor = RemoteExecutor()
    result = await executor._execute_flash_function(request)
    # Result should be in json_result, not cloudpickle-encoded result
    assert result.json_result is not None
```

**Step 2: Run test — expect FAIL**

**Step 3: Update _execute_flash_function()**

Replace lines 383-400:

```python
# Deserialize args/kwargs based on serialization format
serialization_format = getattr(request, "serialization_format", "cloudpickle")

if serialization_format == "json":
    # JSON mode: args and kwargs are plain Python values
    args = request.args
    kwargs = request.kwargs
else:
    # CloudPickle mode: args are base64-encoded cloudpickle strings
    args = SerializationUtils.deserialize_args(request.args)
    kwargs = SerializationUtils.deserialize_kwargs(request.kwargs)

# Execute function
if func_details["is_async"]:
    if asyncio.iscoroutinefunction(func):
        result = await func(*args, **kwargs)
    else:
        result = await asyncio.to_thread(func, *args, **kwargs)
else:
    result = await asyncio.to_thread(func, *args, **kwargs)

# Serialize result based on format
if serialization_format == "json":
    return FunctionResponse(
        success=True,
        json_result=result,
    )
else:
    return FunctionResponse(
        success=True,
        result=SerializationUtils.serialize_result(result),
    )
```

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add src/remote_executor.py tests/
git commit -m "feat: support JSON serialization format in flash function execution"
```

### Task 12: flash-worker — Update _route_to_endpoint to preserve serialization format

**Files:**
- Modify: `flash-worker: src/remote_executor.py:432-495`
- Test: `flash-worker: tests/unit/test_remote_executor.py`

**Step 1: Write test**

```python
async def test_route_to_endpoint_preserves_serialization_format():
    """Cross-endpoint routing preserves serialization_format in forwarded request."""
    request = FunctionRequest(
        function_name="remote_func",
        serialization_format="json",
        args=[{"data": "value"}],
        kwargs={},
    )
    # Verify the forwarded payload includes serialization_format
```

**Step 2-3:** `_route_to_endpoint` already forwards `request.model_dump()`, which includes `serialization_format`. Verify this works — may only need tests.

**Step 4: Run `make quality-check` — expect PASS**

**Step 5: Commit**

```bash
git add src/remote_executor.py tests/
git commit -m "test: verify cross-endpoint routing preserves serialization format"
```

---

## Phase 5: Validation and Cross-Cutting

### Task 13: flash — Verify flash run still uses cloudpickle

**Files:**
- Test: `flash: tests/` (existing LiveServerless tests)

**Step 1: Run existing LiveServerless tests**

Run: `cd /Users/deanquinanola/Github/python/flash-project/flash/main && pytest tests/ -k "live_serverless" -v`

Verify all pass — `flash run` local dev path should be unaffected since it uses LiveServerlessStub which has its own serialization.

**Step 2: Commit if any fixes needed**

### Task 14: flash + flash-worker — Run full quality checks

**Step 1: Run flash quality check**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main && make quality-check
```

Expected: All 1109+ tests pass.

**Step 2: Run flash-worker quality check**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash-worker/main && make quality-check
```

Expected: All tests pass.

**Step 3: Final commit if any fixes needed**

---

## Dependency Graph

```
Task 1 (lb_handler rename)
Task 2 (manifest_reconciliation rename) → depends on Task 1
Task 3 (mothership_provisioner rename) → depends on Task 1
Task 4 (update tests) → depends on Tasks 1, 2

Task 5 (API key injection) → depends on Task 3
Task 6 (API key validation) → depends on Task 5

Task 7 (Manifest dataclass) → independent
Task 8 (URL population test) → depends on Task 7

Task 9 (FunctionRequest proto) → independent
Task 10 (ProductionWrapper JSON) → depends on Task 9
Task 11 (RemoteExecutor JSON) → depends on Task 9
Task 12 (route_to_endpoint) → depends on Task 11

Task 13 (regression) → depends on Tasks 10, 11
Task 14 (full validation) → depends on all
```

## Risk Mitigation

- **Backward compat:** Legacy `FLASH_IS_MOTHERSHIP` accepted with deprecation warning. No hard break.
- **Serialization compat:** `serialization_format` field defaults to `"cloudpickle"`. Existing callers (LiveServerless) work unchanged.
- **FunctionRequest type widening:** `List[str]` → `List[Any]` is backward compatible. Existing cloudpickle-encoded strings are valid `Any` values.
- **Two-repo coordination:** Tasks 9 changes the proto in flash (source of truth). Flash-worker imports the bundled proto from the deployed archive. Both repos must be updated before cross-endpoint calls work in deployed environments.
