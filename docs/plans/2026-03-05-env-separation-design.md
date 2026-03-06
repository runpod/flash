# Design: Separate .env from Resource Deployment Env

**Date:** 2026-03-05
**Status:** Approved
**Branch base:** `deanq/ae-1549-env-vars-from-cwd-first`

## Problem

`ServerlessResource.env` defaults to `get_env_vars()`, which reads the entire `.env` file via `dotenv_values()`. Every key-value pair from `.env` (HF_TOKEN, WANDB_API_KEY, dev-only vars, etc.) gets baked into the manifest and sent to RunPod's `saveTemplate` mutation -- even if the user only intended those vars for local CLI usage.

This causes:
- Platform-injected vars (`PORT`, `PORT_HEALTH`) overwritten on template updates
- False config drift from runtime var injection into `self.env`
- User confusion about what actually reaches deployed workers
- The entire class of bugs addressed in the ae-1549 branch

## Solution

Clean separation between two concerns:

1. **`.env` = CLI/runtime only.** Populates `os.environ` via `load_dotenv()` at import time. Used by `get_api_key()`, CLI commands, local dev server. Never auto-carried to deployed endpoints.

2. **Resource `env={}` = explicit deploy-time vars.** Users declare exactly what goes to each endpoint. Flash injects runtime vars (`RUNPOD_API_KEY`, `FLASH_MODULE_PATH`) into `template.env` separately via existing `_inject_runtime_template_vars()`.

3. **Deploy-time env preview table.** Before provisioning, render a Rich table per resource showing all env vars (user-declared + flash-injected). Secret masking applied.

## Detailed Changes

### Core: `env` field default

- `ServerlessResource.env` default changes from `Field(default_factory=get_env_vars)` to `Field(default=None)`
- Delete `get_env_vars()` function in `serverless.py`
- Delete `EnvironmentVars` class and `environment.py` file entirely
- `load_dotenv(find_dotenv(usecwd=True))` in `__init__.py` stays unchanged

### Manifest pipeline

- `_extract_deployment_config` in `manifest.py`: reads `resource.env` as-is (now `None` or explicit dict). If `None` or otherwise falsy, the manifest omits the `"env"` key.
- Remove the existing `RUNPOD_API_KEY` stripping logic -- it won't be in user env anymore, and runtime injection handles it via `_inject_runtime_template_vars()`.

### Template creation

- `serverless.py:_create_new_template`: change `env=KeyValuePair.from_dict(self.env or get_env_vars())` to `env=KeyValuePair.from_dict(self.env or {})`

### Deploy-time env preview

New functionality in deploy command (either in `deploy.py` or a new `cli/utils/env_preview.py`):

- Collect final env per resource: user-declared env + flash-injected runtime vars
- Render Rich table before proceeding with deployment
- Flash-injected vars labeled with `(injected by flash)` suffix
- Mask values where key matches `KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL` pattern: show first 6 chars + `****`
- Show all other values in full

Example output:
```
Resource: my-gpu
  Environment Variables:
    HF_TOKEN          = hf_abc...****
    MODEL_ID          = llama-3
    RUNPOD_API_KEY    = rp_***...****  (injected by flash)
    FLASH_MODULE_PATH = app.model      (injected by flash)

Resource: my-cpu
  Environment Variables:
    (none)
```

### Unchanged

- `load_dotenv()` in `__init__.py` -- `os.environ` population for CLI
- `get_api_key()` in `credentials.py` -- credential resolution (env -> credentials.toml)
- `_inject_runtime_template_vars()` -- runtime var injection into `template.env`
- `skip_env` logic in `update()` -- platform var preservation (`PORT`, `PORT_HEALTH`)
- `flash env` CLI -- unrelated (deployment environments)
- ae-1549 branch fixes: `_inject_template_env()`, `_inject_runtime_template_vars()`, `skip_env`

### Breaking change strategy

Hard break, no deprecation period. The deploy-time preview table communicates the change clearly -- users see exactly what env vars go to each endpoint. If `env` is empty and `.env` exists, the preview shows only flash-injected vars, making it obvious no user vars are being sent.

## Files to Modify

### Flash repo

| File | Action |
|------|--------|
| `src/runpod_flash/core/resources/environment.py` | Delete entirely |
| `src/runpod_flash/core/resources/serverless.py` | Remove `get_env_vars()`, change `env` default to `None`, update `_create_new_template` |
| `src/runpod_flash/cli/commands/build_utils/manifest.py` | Remove `RUNPOD_API_KEY` stripping |
| `src/runpod_flash/cli/commands/deploy.py` or new `cli/utils/env_preview.py` | Deploy-time env preview table |
| `tests/unit/test_dotenv_loading.py` | Remove or rewrite |
| Tests importing `get_env_vars`/`EnvironmentVars` | Update |
| New tests for env preview | Mask logic, rendering, injected-var labeling |
| `docs/API_Key_Management.md` | Update to reflect runtime injection via `get_api_key()` |

### Flash-examples repo

| File | Action |
|------|--------|
| `CONTRIBUTING.md` | Clarify `.env` is for CLI auth, not endpoint env |
| `README.md` | Same clarification |
| `CLI-REFERENCE.md` | Update `.env` section |
| `docs/cli/commands.md` | Show explicit `env={}` for deploy-time vars |
| `docs/cli/workflows.md` | Update `.env` example section |
| `docs/cli/troubleshooting.md` | Update API key troubleshooting: `flash login` primary, `.env` for CLI only |
| `docs/cli/getting-started.md` | Update setup instructions |

## Secret Masking Strategy

Mask values where the key contains (case-insensitive): `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL`.

Format: first 6 characters + `****`. All other values shown in full.

## User-Facing Example

Before (implicit):
```python
# .env
HF_TOKEN=hf_abc123
MODEL_ID=llama-3

# gpu_worker.py
@Endpoint(name="my-gpu", gpu=GpuGroup.ANY)
async def infer(prompt: str) -> dict:
    ...
# Both HF_TOKEN and MODEL_ID silently sent to endpoint
```

After (explicit):
```python
# .env
RUNPOD_API_KEY=rp_xxx  # CLI/auth only, handled by flash login or get_api_key()

# gpu_worker.py
@Endpoint(
    name="my-gpu",
    gpu=GpuGroup.ANY,
    env={"HF_TOKEN": os.environ["HF_TOKEN"], "MODEL_ID": "llama-3"},
)
async def infer(prompt: str) -> dict:
    ...
# Only declared vars sent to endpoint, visible in deploy preview
```
