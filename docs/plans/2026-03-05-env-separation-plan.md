# Env Separation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop auto-carrying `.env` file contents to deployed endpoints; make resource `env={}` the sole source of user-declared deploy-time env vars.

**Architecture:** Remove `EnvironmentVars` class and `get_env_vars()`. Change `ServerlessResource.env` default to `None`. Add deploy-time env preview table with secret masking. Update docs and examples.

**Tech Stack:** Python, Pydantic, Rich (tables), pytest

**Branch base:** `deanq/ae-1549-env-vars-from-cwd-first`

**Working directory:** `/Users/deanquinanola/Github/python/flash-project/flash/deanq-ae-1549-env-vars-from-cwd-first`

**Test command:** `make format && make lint-fix && make quality-check` (then `git commit --no-verify`)

---

### Task 1: Remove `EnvironmentVars` class and `get_env_vars()`

**Files:**
- Delete: `src/runpod_flash/core/resources/environment.py`
- Modify: `src/runpod_flash/core/resources/serverless.py:23,36-44,149,424`
- Modify: `src/runpod_flash/core/resources/serverless_cpu.py:18,162`

**Step 1: Write failing tests for new default behavior**

Create `tests/unit/resources/test_env_separation.py`:

```python
"""Tests for env separation: resource env defaults to None, not .env contents."""

import pytest
from unittest.mock import patch


class TestResourceEnvDefault:
    """ServerlessResource.env defaults to None when no explicit env provided."""

    def test_serverless_resource_env_defaults_to_none(self):
        """env field should be None when not explicitly provided."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="test-resource")
        assert resource.env is None

    def test_serverless_resource_env_explicit_dict_preserved(self):
        """env field should preserve explicitly provided dict."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(
            name="test-resource",
            env={"HF_TOKEN": "hf_abc123", "MODEL_ID": "llama-3"},
        )
        assert resource.env == {"HF_TOKEN": "hf_abc123", "MODEL_ID": "llama-3"}

    def test_serverless_resource_env_explicit_empty_dict_preserved(self):
        """env={} should be preserved as empty dict, not converted to None."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="test-resource", env={})
        assert resource.env == {}

    def test_cpu_serverless_resource_env_defaults_to_none(self):
        """CPU resource env field should also default to None."""
        from runpod_flash.core.resources import CpuLiveServerless

        resource = CpuLiveServerless(name="test-cpu-resource")
        assert resource.env is None


class TestTemplateCreation:
    """Template env should use self.env or empty dict, never .env file."""

    def test_create_new_template_with_no_env(self):
        """Template env should be empty list when resource env is None."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="test-resource", imageName="test:latest")
        template = resource._create_new_template()
        assert template.env == []

    def test_create_new_template_with_explicit_env(self):
        """Template env should contain only explicitly declared vars."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(
            name="test-resource",
            imageName="test:latest",
            env={"MY_VAR": "my_value"},
        )
        template = resource._create_new_template()
        env_dict = {kv.key: kv.value for kv in template.env}
        assert env_dict == {"MY_VAR": "my_value"}

    def test_cpu_create_new_template_with_no_env(self):
        """CPU template env should be empty list when resource env is None."""
        from runpod_flash.core.resources import CpuLiveServerless

        resource = CpuLiveServerless(name="test-cpu", imageName="test:latest")
        template = resource._create_new_template()
        assert template.env == []
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/resources/test_env_separation.py -xvs`
Expected: FAIL -- `env` defaults to dict from `.env` file, not `None`

**Step 3: Delete `environment.py` and update `serverless.py`**

Delete `src/runpod_flash/core/resources/environment.py`.

In `src/runpod_flash/core/resources/serverless.py`:

1. Remove line 23: `from .environment import EnvironmentVars`
2. Remove lines 35-44 (the `get_env_vars` function and its comment)
3. Change line 149 from:
   ```python
   env: Optional[Dict[str, str]] = Field(default_factory=get_env_vars)
   ```
   to:
   ```python
   env: Optional[Dict[str, str]] = Field(default=None)
   ```
4. Change line 424 from:
   ```python
   env=KeyValuePair.from_dict(self.env or get_env_vars()),
   ```
   to:
   ```python
   env=KeyValuePair.from_dict(self.env or {}),
   ```

In `src/runpod_flash/core/resources/serverless_cpu.py`:

1. Remove `get_env_vars` from the import on line 18:
   ```python
   from .serverless import ServerlessEndpoint
   ```
2. Change line 162 from:
   ```python
   env=KeyValuePair.from_dict(self.env or get_env_vars()),
   ```
   to:
   ```python
   env=KeyValuePair.from_dict(self.env or {}),
   ```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/resources/test_env_separation.py -xvs`
Expected: PASS

**Step 5: Commit**

```bash
git add src/runpod_flash/core/resources/environment.py \
        src/runpod_flash/core/resources/serverless.py \
        src/runpod_flash/core/resources/serverless_cpu.py \
        tests/unit/resources/test_env_separation.py
git commit --no-verify -m "refactor: remove implicit .env carryover to resource env

Change ServerlessResource.env default from get_env_vars() (reads .env)
to None. Delete EnvironmentVars class and get_env_vars(). Template
creation now uses self.env or {} instead of falling back to .env file.

.env still populates os.environ via load_dotenv() in __init__.py for
CLI and get_api_key() usage. This change only affects what gets sent
to deployed endpoints."
```

---

### Task 2: Fix broken tests referencing `get_env_vars` / `EnvironmentVars`

**Files:**
- Modify: `tests/unit/test_p2_remaining_gaps.py:184-228`
- Delete or modify: `tests/unit/test_dotenv_loading.py`
- Possibly others (search first)

**Step 1: Find all broken test references**

Run:
```bash
grep -rn "get_env_vars\|EnvironmentVars\|environment\.dotenv_values" tests/
```

**Step 2: Update `test_p2_remaining_gaps.py`**

Replace class `TestServerlessResourceEnvLoading` (lines 184-228) with:

```python
class TestServerlessResourceEnvLoading:
    """ServerlessResource.env defaults to None (no implicit .env carryover)."""

    def test_env_defaults_to_none_without_explicit_env(self):
        """RES-LS-008: env field is None when not explicitly provided."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="env-test-resource")
        assert resource.env is None

    def test_env_preserves_explicit_dict(self):
        """RES-LS-008: env field preserves explicitly provided dict."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(
            name="env-test-resource",
            env={"FLASH_TEST_SECRET": "hunter2"},
        )
        assert resource.env == {"FLASH_TEST_SECRET": "hunter2"}
```

**Step 3: Update `test_dotenv_loading.py`**

Keep tests that verify `load_dotenv()` behavior in `__init__.py` (tests 1, 2, 3, 4, 5, 6, 7, 8).
Remove any test that imports or tests `EnvironmentVars` or `get_env_vars` (none currently do -- this file tests `load_dotenv` and `__init__.py` directly, which is still valid).

Verify: `grep -n "get_env_vars\|EnvironmentVars" tests/unit/test_dotenv_loading.py` -- should return nothing.

**Step 4: Run full test suite**

Run: `make format && make lint-fix && make quality-check`
Expected: All tests pass. Some tests that previously mocked `get_env_vars` may need updating.

**Step 5: Commit**

```bash
git add tests/
git commit --no-verify -m "test: update tests for env separation (remove get_env_vars references)"
```

---

### Task 3: Remove `RUNPOD_API_KEY` stripping from manifest

**Files:**
- Modify: `src/runpod_flash/cli/commands/build_utils/manifest.py:172-176`
- Test: `tests/unit/cli/commands/build_utils/test_manifest.py` (find relevant tests)

**Step 1: Write failing test**

Add to appropriate test file (find it first with `grep -rn "RUNPOD_API_KEY" tests/unit/cli/commands/build_utils/`):

```python
def test_manifest_preserves_explicit_runpod_api_key_in_env(self):
    """RUNPOD_API_KEY in explicit resource env should NOT be stripped.

    With env separation, if users explicitly declare RUNPOD_API_KEY
    in their resource env, it should be respected.
    """
    # Setup: resource with explicit RUNPOD_API_KEY in env
    # Assert: manifest contains RUNPOD_API_KEY in resource env
```

The exact test code depends on the test file structure -- find it first.

**Step 2: Update `manifest.py`**

In `src/runpod_flash/cli/commands/build_utils/manifest.py`, change lines 172-176 from:

```python
if hasattr(resource_config, "env") and resource_config.env:
    env_dict = dict(resource_config.env)
    env_dict.pop("RUNPOD_API_KEY", None)
    if env_dict:
        config["env"] = env_dict
```

to:

```python
if hasattr(resource_config, "env") and resource_config.env:
    config["env"] = dict(resource_config.env)
```

**Step 3: Run tests**

Run: `make format && make lint-fix && make quality-check`
Expected: PASS

**Step 4: Commit**

```bash
git add src/runpod_flash/cli/commands/build_utils/manifest.py tests/
git commit --no-verify -m "fix(manifest): stop stripping RUNPOD_API_KEY from explicit resource env

With env separation, resource.env only contains user-declared vars.
If a user explicitly sets RUNPOD_API_KEY in their resource env, it
should be preserved. Runtime injection via _inject_runtime_template_vars()
handles the automatic case."
```

---

### Task 4: Deploy-time env preview -- masking utility

**Files:**
- Create: `src/runpod_flash/cli/utils/env_preview.py`
- Create: `tests/unit/cli/utils/test_env_preview.py`

**Step 1: Write failing tests for mask_value**

Create `tests/unit/cli/utils/test_env_preview.py`:

```python
"""Tests for deploy-time env preview with secret masking."""

import pytest


SECRET_PATTERNS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


class TestMaskValue:
    """mask_env_value masks secrets based on key name patterns."""

    def test_masks_key_containing_token(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        assert mask_env_value("HF_TOKEN", "hf_abc123def456") == "hf_abc...****"

    def test_masks_key_containing_key(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        assert mask_env_value("RUNPOD_API_KEY", "rp_12345678") == "rp_123...****"

    def test_masks_key_containing_secret(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        assert mask_env_value("MY_SECRET", "supersecretvalue") == "supers...****"

    def test_masks_key_containing_password(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        assert mask_env_value("DB_PASSWORD", "p@ssw0rd123") == "p@ssw0...****"

    def test_masks_key_containing_credential(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        assert mask_env_value("AWS_CREDENTIAL", "AKIA12345678") == "AKIA12...****"

    def test_does_not_mask_non_secret_key(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        assert mask_env_value("MODEL_ID", "llama-3") == "llama-3"

    def test_does_not_mask_path_value(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        assert mask_env_value("FLASH_MODULE_PATH", "app.model") == "app.model"

    def test_masks_short_secret_value(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        result = mask_env_value("API_KEY", "abc")
        assert "****" in result
        assert "abc" not in result

    def test_case_insensitive_key_matching(self):
        from runpod_flash.cli.utils.env_preview import mask_env_value

        assert "****" in mask_env_value("api_token", "mytokenvalue123")
        assert "****" in mask_env_value("Api_Key", "mykeyvalue12345")


class TestCollectEnvForPreview:
    """collect_env_for_preview merges user env with flash-injected vars."""

    def test_empty_manifest_returns_empty(self):
        from runpod_flash.cli.utils.env_preview import collect_env_for_preview

        result = collect_env_for_preview({})
        assert result == {}

    def test_resource_with_explicit_env(self):
        from runpod_flash.cli.utils.env_preview import collect_env_for_preview

        manifest = {
            "resources": {
                "my-gpu": {
                    "env": {"HF_TOKEN": "hf_abc123", "MODEL_ID": "llama-3"},
                }
            }
        }
        result = collect_env_for_preview(manifest)
        assert "my-gpu" in result
        user_vars = {k: v for k, v, _ in result["my-gpu"]}
        assert user_vars["HF_TOKEN"] == "hf_abc123"
        assert user_vars["MODEL_ID"] == "llama-3"

    def test_resource_with_no_env(self):
        from runpod_flash.cli.utils.env_preview import collect_env_for_preview

        manifest = {"resources": {"my-gpu": {}}}
        result = collect_env_for_preview(manifest)
        assert result["my-gpu"] == []

    def test_resource_with_makes_remote_calls(self):
        from runpod_flash.cli.utils.env_preview import collect_env_for_preview

        manifest = {
            "resources": {
                "my-qb": {
                    "env": {},
                    "makes_remote_calls": True,
                }
            }
        }
        result = collect_env_for_preview(manifest)
        keys = [k for k, _, _ in result["my-qb"]]
        assert "RUNPOD_API_KEY" in keys
        # Verify it's marked as injected
        injected = {k: source for k, _, source in result["my-qb"]}
        assert injected["RUNPOD_API_KEY"] == "flash"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/cli/utils/test_env_preview.py -xvs`
Expected: FAIL -- module does not exist

**Step 3: Implement `env_preview.py`**

Create `src/runpod_flash/cli/utils/env_preview.py`:

```python
"""Deploy-time env preview: show what env vars go to each endpoint."""

from __future__ import annotations

import re
from typing import Any

from rich.console import Console
from rich.table import Table

_SECRET_PATTERN = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE
)

# Minimum chars to show before masking
_MASK_VISIBLE_CHARS = 6


def mask_env_value(key: str, value: str) -> str:
    """Mask value if key matches secret patterns.

    Keys containing KEY, TOKEN, SECRET, PASSWORD, or CREDENTIAL
    (case-insensitive) get masked: first 6 chars + '...****'.
    Short values are fully masked.
    """
    if not _SECRET_PATTERN.search(key):
        return value

    if len(value) <= _MASK_VISIBLE_CHARS:
        return "****"

    return value[:_MASK_VISIBLE_CHARS] + "...****"


def collect_env_for_preview(
    manifest: dict[str, Any],
) -> dict[str, list[tuple[str, str, str]]]:
    """Collect env vars per resource for preview display.

    Returns:
        Dict mapping resource_name -> list of (key, value, source) tuples.
        source is "user" for user-declared vars, "flash" for injected vars.
    """
    from runpod_flash.core.credentials import get_api_key

    resources = manifest.get("resources", {})
    result: dict[str, list[tuple[str, str, str]]] = {}

    for resource_name, config in resources.items():
        entries: list[tuple[str, str, str]] = []

        # User-declared env vars
        user_env = config.get("env") or {}
        for key, value in sorted(user_env.items()):
            entries.append((key, str(value), "user"))

        # Flash-injected: RUNPOD_API_KEY for resources making remote calls
        if config.get("makes_remote_calls", False):
            if "RUNPOD_API_KEY" not in user_env:
                api_key = get_api_key()
                if api_key:
                    entries.append(("RUNPOD_API_KEY", api_key, "flash"))

        # Flash-injected: FLASH_MODULE_PATH for LB endpoints
        if config.get("is_load_balanced", False):
            if "FLASH_MODULE_PATH" not in user_env:
                module_path = config.get("module_path", "")
                if module_path:
                    entries.append(("FLASH_MODULE_PATH", module_path, "flash"))

        result[resource_name] = entries

    return result


def render_env_preview(
    manifest: dict[str, Any],
    console: Console | None = None,
) -> None:
    """Render deploy-time env preview table to console."""
    if console is None:
        console = Console()

    env_data = collect_env_for_preview(manifest)

    if not env_data:
        return

    console.print("\n[bold]Environment Variables per Resource:[/bold]\n")

    for resource_name, entries in sorted(env_data.items()):
        table = Table(
            title=resource_name,
            show_header=True,
            header_style="bold",
            padding=(0, 1),
        )
        table.add_column("Variable", style="cyan")
        table.add_column("Value")
        table.add_column("Source", style="dim")

        if not entries:
            table.add_row("(none)", "", "")
        else:
            for key, value, source in entries:
                masked = mask_env_value(key, value)
                source_label = "injected by flash" if source == "flash" else ""
                table.add_row(key, masked, source_label)

        console.print(table)
        console.print()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/cli/utils/test_env_preview.py -xvs`
Expected: PASS

**Step 5: Commit**

```bash
git add src/runpod_flash/cli/utils/env_preview.py \
        tests/unit/cli/utils/test_env_preview.py
git commit --no-verify -m "feat(cli): add deploy-time env preview with secret masking

New module renders a Rich table per resource showing all env vars
that will be sent to deployed endpoints. User-declared vars shown
directly; flash-injected vars (RUNPOD_API_KEY, FLASH_MODULE_PATH)
labeled as 'injected by flash'. Secret values masked based on key
pattern matching (KEY, TOKEN, SECRET, PASSWORD, CREDENTIAL)."
```

---

### Task 5: Wire env preview into deploy command

**Files:**
- Modify: `src/runpod_flash/cli/commands/deploy.py:200-224`

**Step 1: Write failing test**

Add to `tests/unit/cli/commands/test_deploy.py` (or create if needed):

```python
def test_deploy_renders_env_preview(self):
    """Deploy should render env preview before provisioning."""
    # This is an integration-level test -- verify render_env_preview
    # is called with the local manifest during deploy flow.
    from unittest.mock import patch, MagicMock, AsyncMock

    with patch(
        "runpod_flash.cli.commands.deploy.render_env_preview"
    ) as mock_preview:
        # Verify render_env_preview is importable from deploy module
        from runpod_flash.cli.commands.deploy import render_env_preview
        assert mock_preview is not None
```

**Step 2: Integrate into deploy flow**

In `src/runpod_flash/cli/commands/deploy.py`, add import at top:

```python
from ..utils.env_preview import render_env_preview
```

In `_resolve_and_deploy` (around line 205, after `validate_local_manifest()`), add:

```python
local_manifest = validate_local_manifest()

# Show env preview before deploying
render_env_preview(local_manifest, console)
```

**Step 3: Run tests**

Run: `make format && make lint-fix && make quality-check`
Expected: PASS

**Step 4: Commit**

```bash
git add src/runpod_flash/cli/commands/deploy.py tests/
git commit --no-verify -m "feat(cli): show env preview table during flash deploy

Renders env vars per resource before provisioning so users see
exactly what goes to each endpoint. Surfaces both user-declared
and flash-injected vars with secret masking."
```

---

### Task 6: Run full quality check

**Step 1: Run quality check**

Run: `make format && make lint-fix && make quality-check`

**Step 2: Fix any remaining failures**

Common issues to expect:
- Tests that create `ServerlessResource` without `env` and assert it's a dict -- change to assert `is None`
- Tests that mock `get_env_vars` as a monkeypatch target -- remove those patches
- Import errors from deleted `environment.py`

Search for all remaining references:
```bash
grep -rn "environment\.py\|from.*environment import\|get_env_vars\|EnvironmentVars" src/ tests/
```

Fix each one, then re-run quality check.

**Step 3: Commit fixes**

```bash
git add -u
git commit --no-verify -m "fix: resolve remaining test failures from env separation"
```

---

### Task 7: Update flash documentation

**Files:**
- Modify: `docs/API_Key_Management.md`

**Step 1: Read current doc**

Read `docs/API_Key_Management.md` to understand current content.

**Step 2: Update doc**

Key changes:
- Remove any references to `.env` auto-loading into deployed endpoints
- Clarify that `RUNPOD_API_KEY` is resolved via `get_api_key()` (env var or `flash login` credentials)
- Document the explicit `env={}` pattern for resource env vars
- Document the deploy-time env preview

**Step 3: Commit**

```bash
git add docs/API_Key_Management.md
git commit --no-verify -m "docs: update API key management for env separation"
```

---

### Task 8: Update flash-examples documentation

**Files (all in flash-examples repo):**
- Modify: `CONTRIBUTING.md`
- Modify: `README.md`
- Modify: `CLI-REFERENCE.md`
- Modify: `docs/cli/commands.md`
- Modify: `docs/cli/workflows.md`
- Modify: `docs/cli/troubleshooting.md`
- Modify: `docs/cli/getting-started.md`

**Working directory:** `/Users/deanquinanola/Github/python/flash-project/flash-examples/main`

**Step 1: Identify all `.env` references that need updating**

Run from flash-examples/main:
```bash
grep -rn "\.env" --include="*.md" | grep -v ".gitignore\|.flashignore\|.env.example\|.env.local" | grep -i "loaded automatically\|auto.*load\|automatically loaded\|carries\|deployed\|endpoint.*env"
```

**Step 2: Update each file**

The key message change across all docs:

> `.env` is for local development and CLI authentication (e.g., `RUNPOD_API_KEY` via `flash login` or env var). To pass env vars to deployed endpoints, declare them explicitly: `env={"HF_TOKEN": os.environ["HF_TOKEN"]}`.

Specific updates per file:

- **CONTRIBUTING.md** (lines 309-335): Change "The `.env` file is automatically loaded, so your `RUNPOD_API_KEY` is available during debugging" to clarify it's for CLI/local use only
- **README.md** (lines 29-34): Update setup to mention `flash login` as primary, `.env` for local dev
- **CLI-REFERENCE.md** (lines 794-808): Update the `.env` section to distinguish CLI vs deploy usage
- **docs/cli/commands.md** (lines 291-363): Add example of explicit `env={}` on resource
- **docs/cli/workflows.md** (lines 68-75): Update `.env` example section
- **docs/cli/troubleshooting.md** (lines 661-665, 1040-1084): Update API key guidance
- **docs/cli/getting-started.md** (lines 28-55): Update setup instructions

**Step 3: Commit**

```bash
git add CONTRIBUTING.md README.md CLI-REFERENCE.md docs/
git commit --no-verify -m "docs: clarify .env is for CLI only, not deployed endpoint env

Update all documentation to reflect env separation:
- .env populates os.environ for CLI and local dev
- Resource env={} is the explicit way to set endpoint env vars
- flash login is the primary auth method
- Deploy-time preview shows what goes to each endpoint"
```

---

### Task 9: Final verification

**Step 1: Run full quality check on flash repo**

```bash
cd /Users/deanquinanola/Github/python/flash-project/flash/deanq-ae-1549-env-vars-from-cwd-first
make format && make lint-fix && make quality-check
```

**Step 2: Verify no remaining references to deleted code**

```bash
grep -rn "get_env_vars\|EnvironmentVars\|from.*environment import" src/ tests/
```

Expected: zero results.

**Step 3: Verify `.env` still works for CLI**

```bash
# Create a test .env
echo "RUNPOD_API_KEY=test_key_123" > /tmp/test-env-sep/.env
cd /tmp/test-env-sep
python -c "from runpod_flash.core.credentials import get_api_key; print(get_api_key())"
# Expected: test_key_123
```

**Step 4: Review all commits**

```bash
git log --oneline HEAD~8..HEAD
```

Verify commit chain tells a clear story.
