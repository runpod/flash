# Flash Rules for AI Coding Agents

## Use the Flash CLI — Do Not Call Runpod REST or GraphQL Directly

For anything Flash supports, use the `flash` CLI. **Do not** generate `curl`, `httpx`, `requests`, or `gql` calls against `api.runpod.io`, `api.runpod.ai`, or `*.runpod.net` to build, deploy, list, scale, log, or invoke endpoints. The CLI handles auth, hashing, drift detection, manifest generation, and image selection. Direct API calls bypass all of that and will silently desync from Flash state.

| Intent | Command | Do NOT |
|--------|---------|--------|
| Scaffold a project | `flash init <name>` | Hand-write `pyproject.toml` + manifest |
| Local dev server | `flash dev` | Run `uvicorn` against generated server manually |
| Package artifact | `flash build` | Tar `src/` and POST it |
| Deploy to Runpod | `flash deploy` | Call `saveEndpoint` / REST `POST /v1/endpoints` |
| Preview locally | `flash deploy --preview` | Hand-write `docker-compose.yml` |
| Tear down | `flash undeploy` | Call `deleteEndpoint` mutation |
| List apps/envs | `flash app list` / `flash env list` | Query GraphQL `myself.endpoints` |

If a Flash command does not exist for what the user is asking, surface that gap (`flash <area> --help` first), then ask before reaching for raw API calls. Raw Runpod SDK use (`runpod.Endpoint(...)`) is acceptable only for invoking already-deployed endpoints from non-Flash code — never for lifecycle operations.

## Identity

Flash is a Python SDK for deploying AI workloads to Runpod GPUs. You write decorated Python functions, Flash handles infrastructure, scaling, and deployment.

## Endpoint Patterns

### Pattern A: Queue-based function endpoint

```python
from runpod_flash import Endpoint, GpuType

@Endpoint(
    name="my-gpu-worker",
    gpu=GpuType.NVIDIA_GEFORCE_RTX_4090,
    workers=(0, 3),
    dependencies=["torch"],
)
async def process(input_data: dict) -> dict:
    import torch
    return {"gpu": torch.cuda.get_device_name(0)}
```

### Pattern B: Load-balanced routes

```python
from runpod_flash import Endpoint

api = Endpoint(name="my-api", cpu="cpu3c-1-2", workers=(1, 3))

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/compute")
async def compute(numbers: list[float]) -> dict:
    return {"sum": sum(numbers)}
```

### Pattern C: Class-based worker (stateful)

```python
from runpod_flash import Endpoint, GpuType

@Endpoint(
    name="my-model",
    gpu=GpuType.NVIDIA_GEFORCE_RTX_4090,
    workers=(1, 3),
    dependencies=["torch", "transformers"],
)
class MyModel:
    def __init__(self):
        import torch
        from transformers import pipeline
        self.pipe = pipeline("text-generation", device="cuda")

    async def generate(self, prompt: str) -> dict:
        return {"text": self.pipe(prompt)[0]["generated_text"]}
```

### Pattern D: Pre-built container image (no decorated function)

For workloads that already serve HTTP — vLLM, TGI, ComfyUI, Ollama, custom images — provision the endpoint with an `image=` argument and call it as a client. No Python handler to write. Flash deploys the image and gives you HTTP + queue access to it.

```python
from runpod_flash import Endpoint, GpuGroup

vllm = Endpoint(
    name="vllm",
    image="runpod/worker-v1-vllm:v2.18.1",
    gpu=GpuGroup.ADA_24,
    workers=(0, 3),
    env={"MODEL_NAME": "meta-llama/Llama-3.1-8B-Instruct"},
)

# QB-style — the Runpod vLLM worker speaks the queue protocol
result = await vllm.runsync({"input": {"prompt": "hello", "max_tokens": 64}})

# Or LB-style HTTP if you've routed through a load-balanced front
models = await vllm.get("/v1/models")
```

When to use this pattern: the upstream project already publishes a serving image and you don't need to add any Python logic on top. If you need pre/post-processing, wrap the call inside a Pattern A or B `@Endpoint` instead.

To attach to an already-deployed endpoint (no provisioning), pass `id=` instead of `image=`:

```python
ep = Endpoint(id="abc123")
result = await ep.runsync({"prompt": "hello"})
```

## Rules That Break If Violated

- `import torch` and heavy libraries INSIDE the function body, never at module level
- Declare runtime dependencies in `@Endpoint(dependencies=[...])`, not in `pyproject.toml`
- Endpoint functions can be sync (`def`) or async (`async def`). Use async when awaiting other endpoints or async I/O
- `workers=N` is shorthand for `(0, N)` — auto-scales from 0 (cold start on every burst). Use `workers=(N, N)` to pin a fixed count; `workers=(1, N)` to keep at least one warm worker
- `workers=(min, max)` is the explicit range form — prefer it when you care about cold-start behavior
- Class workers: model loading in `__init__`, request handling in instance methods
- Cross-worker calls use `await` — call `@Endpoint`-decorated functions as if local; Flash handles remote dispatch
- System-level packages (ffmpeg, libgl1) go in `system_dependencies`, not `dependencies`
- `@Endpoint` is the canonical decorator. `@remote` is the legacy alias

## Common Agent Mistakes

| Mistake | Fix |
|---------|-----|
| Writing raw FastAPI instead of `@Endpoint` | Use `@Endpoint` decorator, Flash generates FastAPI |
| `import torch` at top of file | Move inside function body |
| Adding deps to `pyproject.toml` only | Add to `@Endpoint(dependencies=[...])` |
| Forcing `async def` on all endpoints | Both sync and async are valid; use async only when awaiting |
| Creating `main.py` or `app.py` | Not needed — Flash auto-discovers decorated functions |
| Using `docker-compose` manually | Use `flash deploy --preview` for local container testing |
| Wrapping vLLM/TGI/Comfy in a custom handler for no reason | Use `Endpoint(name=..., image=...)` and call via `.post()`/`.run()` — Pattern D |
| Calling Runpod REST/GraphQL directly | Use `flash` CLI — see top of this file |
