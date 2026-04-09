# AE-2744: Payload Validation Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make empty/null input validation consistent between the dev server (`flash run`) and deployed QB endpoints, so developers discover the "RunPod rejects empty input" behavior during local development rather than after deployment.

**Architecture:** Three independent validation points in the `flash` repo: (1) `call_with_body` in the dev server helpers rejects empty Pydantic models via `model_fields_set`, (2) deployed handler templates reject empty `job_input` dicts before function invocation, (3) `create_deployed_handler` replaces its silent empty-to-default fallback with an explicit rejection. All share the same error message.

**Tech Stack:** Python, FastAPI (HTTPException), Pydantic v2 (`model_fields_set`), pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/runpod_flash/cli/commands/_run_server_helpers.py` | Modify | Add empty-input validation to `call_with_body()` |
| `src/runpod_flash/cli/commands/build_utils/handler_generator.py` | Modify | Add validation to `DEPLOYED_HANDLER_TEMPLATE` and `DEPLOYED_CLASS_HANDLER_TEMPLATE` |
| `src/runpod_flash/runtime/generic_handler.py` | Modify | Replace silent default with rejection in `create_deployed_handler()` |
| `tests/unit/cli/commands/test_run_server_helpers.py` | Create | Tests for `call_with_body` validation |
| `tests/unit/cli/commands/build_utils/test_handler_generator.py` | Modify | Add tests for empty-input validation in generated handlers |
| `tests/unit/runtime/test_generic_handler_extended.py` | Modify | Update existing tests, add empty-input rejection tests |

---

### Task 1: Add empty-input validation to `call_with_body`

**Files:**
- Create: `tests/unit/cli/commands/test_run_server_helpers.py`
- Modify: `src/runpod_flash/cli/commands/_run_server_helpers.py:74-80`

- [ ] **Step 1: Write failing tests for `call_with_body` validation**

Create `tests/unit/cli/commands/__init__.py` if it does not exist, then create the test file:

```bash
touch tests/unit/cli/commands/__init__.py
```

```python
"""Tests for _run_server_helpers.py — empty-input validation in call_with_body."""

import pytest
from unittest.mock import AsyncMock

from fastapi import HTTPException
from pydantic import create_model

from runpod_flash.cli.commands._run_server_helpers import call_with_body


class TestCallWithBodyEmptyInputValidation:
    """Verify call_with_body rejects empty input (model_fields_set is empty)."""

    @pytest.mark.asyncio
    async def test_rejects_empty_pydantic_model(self):
        """Empty input dict -> model_fields_set is empty -> 422."""
        Inner = create_model("Inner", msg=(str, None))
        body = Inner()  # no fields explicitly set

        func = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await call_with_body(func, body)

        assert exc_info.value.status_code == 422
        assert "Empty input" in exc_info.value.detail
        func.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_explicit_null_value(self):
        """{"msg": null} -> model_fields_set is {"msg"} -> passes."""
        Inner = create_model("Inner", msg=(str, None))
        body = Inner(msg=None)

        func = AsyncMock(return_value={"ok": True})
        result = await call_with_body(func, body)

        assert result == {"ok": True}
        func.assert_called_once_with(msg=None)

    @pytest.mark.asyncio
    async def test_allows_populated_fields(self):
        """{"msg": "hello"} -> model_fields_set is {"msg"} -> passes."""
        Inner = create_model("Inner", msg=(str, None))
        body = Inner(msg="hello")

        func = AsyncMock(return_value={"echo": "hello"})
        result = await call_with_body(func, body)

        assert result == {"echo": "hello"}
        func.assert_called_once_with(msg="hello")

    @pytest.mark.asyncio
    async def test_allows_plain_dict_body(self):
        """Plain dict (no model_fields_set attr) passes through unchanged."""
        body = {"key": "value"}

        func = AsyncMock(return_value={"ok": True})
        result = await call_with_body(func, body)

        assert result == {"ok": True}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
uv run pytest tests/unit/cli/commands/test_run_server_helpers.py -v --no-header --tb=short -p no:cacheprovider 2>&1 | tail -20
```

Expected: `test_rejects_empty_pydantic_model` FAILS (no HTTPException raised). Other tests PASS.

- [ ] **Step 3: Implement empty-input validation in `call_with_body`**

In `src/runpod_flash/cli/commands/_run_server_helpers.py`, replace the existing `call_with_body` function (lines 74-80):

```python
async def call_with_body(func, body):
    """Call func with body kwargs, handling Pydantic models and dicts.

    Rejects empty input (no fields explicitly set) to match RunPod platform
    behavior, which does not dispatch jobs with empty/null input dicts.
    """
    if hasattr(body, "model_fields_set") and not body.model_fields_set:
        raise HTTPException(
            status_code=422,
            detail=(
                "Empty input: RunPod serverless requires at least one field "
                "in the input dict. Use explicit values or pass null for "
                'optional parameters, e.g. {"input": {"param_name": null}}.'
            ),
        )
    if hasattr(body, "model_dump"):
        return await func(**body.model_dump())
    raw = body.get("input", body) if isinstance(body, dict) else body
    kwargs = _map_body_to_params(func, raw)
    return await func(**kwargs)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
uv run pytest tests/unit/cli/commands/test_run_server_helpers.py -v --no-header --tb=short -p no:cacheprovider 2>&1 | tail -20
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
make quality-check 2>&1 | tail -30
```

Expected: All tests pass, quality checks green.

- [ ] **Step 6: Commit**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
git add tests/unit/cli/commands/__init__.py tests/unit/cli/commands/test_run_server_helpers.py src/runpod_flash/cli/commands/_run_server_helpers.py
git commit -m "fix(run): reject empty input in dev server QB routes (AE-2744)

call_with_body now checks model_fields_set and returns 422 when the
user sends {\"input\": {}}. This matches RunPod platform behavior,
which silently times out on empty input instead of dispatching the job."
```

---

### Task 2: Add empty-input validation to deployed handler templates

**Files:**
- Modify: `src/runpod_flash/cli/commands/build_utils/handler_generator.py:12-155`
- Modify: `tests/unit/cli/commands/build_utils/test_handler_generator.py`

- [ ] **Step 1: Write failing tests for handler template validation**

Append these tests to `tests/unit/cli/commands/build_utils/test_handler_generator.py`:

```python
def test_function_handler_validates_empty_input():
    """Generated function handler rejects empty input dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": False,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "if not job_input:" in content
        assert "Empty or null input" in content


def test_class_handler_validates_empty_input():
    """Generated class handler rejects empty input dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "Worker",
                            "module": "w",
                            "is_async": False,
                            "is_class": True,
                            "class_methods": ["run"],
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "if not job_input:" in content
        assert "Empty or null input" in content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
uv run pytest tests/unit/cli/commands/build_utils/test_handler_generator.py::test_function_handler_validates_empty_input tests/unit/cli/commands/build_utils/test_handler_generator.py::test_class_handler_validates_empty_input -v --no-header --tb=short -p no:cacheprovider 2>&1 | tail -15
```

Expected: Both FAIL — "if not job_input:" not found in content.

- [ ] **Step 3: Add validation to DEPLOYED_HANDLER_TEMPLATE**

In `src/runpod_flash/cli/commands/build_utils/handler_generator.py`, replace lines 34-38 of `DEPLOYED_HANDLER_TEMPLATE`:

```python
def handler(job):
    """Handler for deployed QB endpoint. Accepts plain JSON kwargs."""
    job_input = job.get("input", {{}})
    try:
        result = {function_name}(**job_input)
```

With:

```python
def handler(job):
    """Handler for deployed QB endpoint. Accepts plain JSON kwargs."""
    job_input = job.get("input") or {{}}
    if not job_input:
        return {{
            "error": (
                "Empty or null input. RunPod serverless requires at least one "
                "field in the input dict. Use explicit values or pass null for "
                'optional parameters, e.g. {{\\"input\\": {{\\"param_name\\": null}}}}.'
            )
        }}
    try:
        result = {function_name}(**job_input)
```

- [ ] **Step 4: Add validation to DEPLOYED_CLASS_HANDLER_TEMPLATE**

In the same file, replace lines 117-118 of `DEPLOYED_CLASS_HANDLER_TEMPLATE`:

```python
    job_input = job.get("input", {{}})
    try:
```

With:

```python
    job_input = job.get("input") or {{}}
    if not job_input:
        return {{
            "error": (
                "Empty or null input. RunPod serverless requires at least one "
                "field in the input dict. Use explicit values or pass null for "
                'optional parameters, e.g. {{\\"input\\": {{\\"param_name\\": null}}}}.'
            )
        }}
    try:
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
uv run pytest tests/unit/cli/commands/build_utils/test_handler_generator.py -v --no-header --tb=short -p no:cacheprovider 2>&1 | tail -20
```

Expected: All tests PASS (including the two new ones).

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
make quality-check 2>&1 | tail -30
```

Expected: All tests pass, quality checks green.

- [ ] **Step 7: Commit**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
git add src/runpod_flash/cli/commands/build_utils/handler_generator.py tests/unit/cli/commands/build_utils/test_handler_generator.py
git commit -m "fix(build): reject empty input in deployed handler templates (AE-2744)

Both function and class handler templates now return an error dict
when job input is empty or null. Defense-in-depth: the RunPod platform
typically blocks empty-input jobs, but this protects against platform
behavior changes and direct handler testing."
```

---

### Task 3: Replace silent default with rejection in `create_deployed_handler`

**Files:**
- Modify: `src/runpod_flash/runtime/generic_handler.py:221-277`
- Modify: `tests/unit/runtime/test_generic_handler_extended.py:173-216`

- [ ] **Step 1: Write failing tests for empty-input rejection**

In `tests/unit/runtime/test_generic_handler_extended.py`, add these tests to the existing `TestCreateDeployedHandler` class (after the existing tests, around line 217):

```python
    def test_rejects_empty_input_dict(self):
        """Empty input dict -> error response, not silent execution."""
        def process(x: int):
            return {"result": x}

        handler = create_deployed_handler(process)
        result = handler({"input": {}})
        assert result["success"] is False
        assert "Empty or null input" in result["error"]

    def test_rejects_null_input(self):
        """Null input -> error response."""
        def process(x: int):
            return {"result": x}

        handler = create_deployed_handler(process)
        result = handler({"input": None})
        assert result["success"] is False
        assert "Empty or null input" in result["error"]

    def test_rejects_missing_input_key(self):
        """Missing input key -> error response."""
        def process(x: int):
            return {"result": x}

        handler = create_deployed_handler(process)
        result = handler({})
        assert result["success"] is False
        assert "Empty or null input" in result["error"]
```

- [ ] **Step 2: Update existing tests that expect empty input to succeed**

The existing tests `test_empty_input` (line 202) and `test_missing_input_key` (line 210) expect empty/missing input to succeed for zero-arg functions. These must be updated to expect rejection, because the validation applies regardless of function signature (matching RunPod platform behavior).

Replace the existing `test_empty_input` test (lines 202-208):

```python
    def test_empty_input_rejected(self):
        """Empty input is rejected even for zero-arg functions (platform behavior)."""
        def no_args():
            return {"status": "ok"}

        handler = create_deployed_handler(no_args)
        result = handler({"input": {}})
        assert result["success"] is False
        assert "Empty or null input" in result["error"]
```

Replace the existing `test_missing_input_key` test (lines 210-216):

```python
    def test_missing_input_key_rejected(self):
        """Missing input key is rejected even for zero-arg functions."""
        def no_args():
            return {"status": "ok"}

        handler = create_deployed_handler(no_args)
        result = handler({})
        assert result["success"] is False
        assert "Empty or null input" in result["error"]
```

- [ ] **Step 3: Run tests to verify the new tests fail and updated tests fail**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
uv run pytest tests/unit/runtime/test_generic_handler_extended.py::TestCreateDeployedHandler -v --no-header --tb=short -p no:cacheprovider 2>&1 | tail -20
```

Expected: `test_rejects_empty_input_dict`, `test_rejects_null_input`, `test_rejects_missing_input_key`, `test_empty_input_rejected`, and `test_missing_input_key_rejected` all FAIL.

- [ ] **Step 4: Implement validation in `create_deployed_handler`**

In `src/runpod_flash/runtime/generic_handler.py`, replace the input extraction logic in the inner `handler` function (lines 239-249):

```python
    def handler(job: Dict[str, Any]) -> Any:
        if "input" not in job or job.get("input") is None:
            job_input = {}
        else:
            job_input = job.get("input")
            if not isinstance(job_input, dict):
                return {
                    "success": False,
                    "error": f"Malformed input: expected dict, got {type(job_input).__name__}",
                }
        try:
            result = func(**job_input)
```

With:

```python
    def handler(job: Dict[str, Any]) -> Any:
        raw_input = job.get("input")
        if raw_input is None or (isinstance(raw_input, dict) and not raw_input):
            return {
                "success": False,
                "error": (
                    "Empty or null input. RunPod serverless requires at least "
                    "one field in the input dict. Use explicit values or pass "
                    'null for optional parameters, e.g. {"input": {"param_name": null}}.'
                ),
            }
        if not isinstance(raw_input, dict):
            return {
                "success": False,
                "error": f"Malformed input: expected dict, got {type(raw_input).__name__}",
            }
        job_input = raw_input
        try:
            result = func(**job_input)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
uv run pytest tests/unit/runtime/test_generic_handler_extended.py::TestCreateDeployedHandler -v --no-header --tb=short -p no:cacheprovider 2>&1 | tail -20
```

Expected: All tests PASS.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
make quality-check 2>&1 | tail -30
```

Expected: All tests pass, quality checks green.

- [ ] **Step 7: Commit**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
git add src/runpod_flash/runtime/generic_handler.py tests/unit/runtime/test_generic_handler_extended.py
git commit -m "fix(runtime): reject empty input in create_deployed_handler (AE-2744)

Replace silent None-to-empty-dict fallback with explicit rejection.
Returns {success: false, error: ...} for empty/null input, consistent
with the dev server and handler template validation."
```

---

## Verification

After all three tasks are committed, run the full quality check one final time:

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/main
make quality-check
```

All 2500+ tests must pass, formatting and linting must be clean, and coverage must remain above threshold.
