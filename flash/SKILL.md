---
name: flash
description: Complete knowledge of runpod-flash - the Endpoint class, CLI, deployment, architecture.
  Triggers on "flash", "runpod-flash", "Endpoint", "serverless", "deploy", "GpuType", "GpuGroup".
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash
---

# Runpod Flash

**runpod-flash** (v1.6.0) -- Python SDK for distributed inference and serving on Runpod serverless.

- **Package**: `pip install runpod-flash`
- **Import**: `from runpod_flash import Endpoint, GpuGroup, GpuType, ...`
- **CLI**: `flash`
- **Python**: >=3.10, <3.15

## Getting Started

```bash
pip install runpod-flash
flash login                  # Authenticate via browser (recommended)
# Or: export RUNPOD_API_KEY=... or add to .env file
```

Minimal example:

```python
import asyncio
from runpod_flash import Endpoint, GpuType

@Endpoint(name="my-first-worker", gpu=GpuType.ANY, dependencies=["torch"])
async def gpu_task(data):
    import torch
    tensor = torch.tensor(data, device="cuda")
    return {"sum": tensor.sum().item(), "gpu": torch.cuda.get_device_name(0)}

asyncio.run(gpu_task([1, 2, 3, 4, 5]))
```

First run takes ~1 minute (endpoint provisioning). Subsequent runs take ~1 second.

Create a project with templates:

```bash
flash init my_project && cd my_project
flash run                    # Local FastAPI dev server at localhost:8888/docs
```

## The Endpoint Class: Four Modes

The `Endpoint` class is the single entry point for all Flash functionality.

### Mode 1: Queue-Based Decorator (QB)

One function = one endpoint = own workers. Best for batch, long-running tasks, automatic retries. Returns `JobOutput` with `.output`, `.error`, `.status`.

```python
from runpod_flash import Endpoint, GpuType

@Endpoint(name="gpu_worker", gpu=GpuType.ANY, dependencies=["torch"])
async def gpu_hello(input_data: dict) -> dict:
    import torch
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU"
    return {"message": input_data.get("message", "Hello!"), "gpu": gpu_name}

result = await gpu_hello({"message": "test"})
# result.output contains the return dict
```

### Mode 2: Load-Balanced Decorator (LB)

Multiple routes, shared workers. Best for real-time APIs, low-latency HTTP. Returns dict directly (no wrapper). Supported methods: `GET`, `POST`, `PUT`, `DELETE`, `PATCH`. Reserved paths: `/execute`, `/ping`.

```python
from runpod_flash import Endpoint

api = Endpoint(name="lb_worker", cpu="cpu3c-1-2", workers=(1, 3))

@api.post("/process")
async def process(input_data: dict) -> dict:
    from datetime import datetime
    return {"echo": input_data, "timestamp": datetime.now().isoformat()}

@api.get("/health")
async def health() -> dict:
    return {"status": "healthy"}
```

### Mode 3: External Image Client

Deploy a pre-built Docker image, call it as a client. Returns `EndpointJob` (see below).

```python
from runpod_flash import Endpoint, GpuGroup

vllm = Endpoint(name="vllm", image="vllm/vllm-openai:latest", gpu=GpuGroup.ADA_24)

result = await vllm.post("/v1/completions", {"prompt": "hello"})  # LB-style
job = await vllm.run({"prompt": "hello"})                         # QB-style
await job.wait()
print(job.output)
```

### Mode 4: Existing Endpoint Client

Connect to an already-deployed endpoint by ID. No provisioning. Returns `EndpointJob`.

```python
ep = Endpoint(id="abc123")
job = await ep.runsync({"prompt": "hello"})
print(job.output)
```

**EndpointJob** (returned by `.run()` / `.runsync()` in client modes): properties `.id`, `.output`, `.error`, `.done`; methods `await job.status()`, `await job.wait(timeout=60)`, `await job.cancel()`.

## Constructor Parameters

```python
Endpoint(
    name: str = None,                    # Required unless id= is set
    *,
    id: str = None,                      # Connect to existing endpoint (client mode)
    gpu: GpuGroup | GpuType | list = None,  # GPU type(s) -- mutually exclusive with cpu
    cpu: str | CpuInstanceType | list = None, # CPU type(s) -- mutually exclusive with gpu
    workers: int | tuple[int, int] = None,    # (min, max) tuple or just max. Default: (0, 1)
    idle_timeout: int = 60,              # Seconds before scale-down
    dependencies: list[str] = None,      # pip packages to install
    system_dependencies: list[str] = None, # apt-get packages
    accelerate_downloads: bool = True,   # CDN download acceleration
    volume: NetworkVolume = None,        # Persistent storage (NetworkVolume(name=..., size=100, dataCenterId=DataCenter.EU_RO_1))
    datacenter: DataCenter = DataCenter.EU_RO_1,
    env: dict[str, str] = None,          # Environment variables
    gpu_count: int = 1,                  # GPUs per worker
    execution_timeout_ms: int = 0,       # 0 = no limit
    flashboot: bool = True,              # Fast cold starts
    image: str = None,                   # Docker image (external image mode, mutually exclusive with id)
    scaler_type: ServerlessScalerType = None,  # QUEUE_DELAY (QB) or REQUEST_COUNT (LB)
    scaler_value: int = 4,
    template: PodTemplate = None,        # Pod overrides (e.g. PodTemplate(containerDiskInGb=100))
)
```

- `gpu` and `cpu` are mutually exclusive. `id` and `image` are mutually exclusive.
- If neither `gpu` nor `cpu` is set (non-client), defaults to `gpu=GpuGroup.ANY`.
- `workers=5` means `(0, 5)`. `workers=(2, 5)` means min 2, max 5.

## GPU & CPU Types

### GpuGroup (by VRAM class)

| Group | VRAM | GPUs |
|-------|------|------|
| `ANY` | Any | Any available (not for production) |
| `AMPERE_16` | 16GB | RTX A4000/A4500 |
| `AMPERE_24` | 24GB | RTX A5000, L4, RTX 3090 |
| `ADA_24` | 24GB | RTX 4090 |
| `ADA_32_PRO` | 32GB | RTX 5090 |
| `AMPERE_48` | 48GB | A40, RTX A6000 |
| `ADA_48_PRO` | 48GB | RTX 6000 Ada |
| `AMPERE_80` | 80GB | A100 |
| `ADA_80_PRO` | 80GB | H100 |
| `HOPPER_141` | 141GB | H200 |

For exact GPU selection, use `GpuType` enum (e.g. `GpuType.NVIDIA_GEFORCE_RTX_4090`). See `src/runpod_flash/core/resources/gpu.py` for full list.

### CPU Instance Types

Format: `cpu{gen}{type}-{vcpu}-{memory}`. Use string shorthand (`cpu="cpu3c-1-2"`) or `CpuInstanceType` enum.

Families: `cpu3g` (general, 4GB/vCPU), `cpu3c` (compute, 2GB/vCPU), `cpu5c` (5th gen compute, 2GB/vCPU). Each from 1 to 8 vCPUs. See `src/runpod_flash/core/resources/cpu.py` for full list.

## Cloudpickle Scoping Rules

Functions decorated with `@Endpoint(...)` are serialized with cloudpickle. They can ONLY access:
- Function parameters, local variables, imports done **inside** the function, built-ins

They CANNOT access: module-level imports, global variables, external functions/classes.

```python
# WRONG
import torch
@Endpoint(name="worker", gpu=GpuGroup.ADA_24)
async def bad(data):
    return torch.tensor(data)  # torch not accessible remotely

# CORRECT
@Endpoint(name="worker", gpu=GpuGroup.ADA_24, dependencies=["torch"])
async def good(data):
    import torch
    return torch.tensor(data)
```

All pip packages must be in `dependencies=[]`. System packages in `system_dependencies=[]`.

## CLI Commands

```bash
flash login                                      # Authenticate via browser
flash init [project_name]                        # Create project from templates
flash run [--host HOST] [--port PORT]            # Dev server at localhost:8888
flash build [--exclude pkg1,pkg2] [--preview]    # Package artifact (500MB limit)
flash deploy new|send|list|info|delete <env>     # Deployment lifecycle
flash undeploy list                              # List deployed resources
flash undeploy <name>                            # Remove specific resource
flash env list|create|get|delete <name>          # Environment management
flash app list|get <name>                        # App management
```

Key notes:
- `flash build --exclude torch,torchvision,torchaudio` -- exclude packages already in base Docker image to stay under 500MB limit
- `flash build --preview` -- run in local Docker containers for end-to-end testing
- `flash deploy send` requires `flash build` first

## Common Patterns

### Hybrid GPU/CPU Pipeline

```python
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="preprocessor", cpu="cpu5c-4-8", dependencies=["pandas"])
async def preprocess(data):
    import pandas as pd
    return pd.DataFrame(data).to_dict("records")

@Endpoint(name="inference", gpu=GpuGroup.AMPERE_80, dependencies=["torch"])
async def inference(data):
    import torch
    tensor = torch.tensor(data, device="cuda")
    return {"result": tensor.sum().item()}

async def pipeline(raw_data):
    clean = await preprocess(raw_data)
    return await inference(clean)
```

### External Image

```python
vllm = Endpoint(name="vllm-server", image="vllm/vllm-openai:latest", gpu=GpuGroup.ADA_80_PRO)
result = await vllm.post("/v1/completions", {"prompt": "hello", "model": "meta-llama/Llama-3-8B"})
```

## Error Handling

- **QB**: Returns `JobOutput` -- check `result.error` for failures, `result.output` for data
- **LB**: Returns dict directly -- use try/except
- **Client mode**: `EndpointJob` -- check `job.error` after `await job.wait()`
- **Serialization limit**: cloudpickle + base64, max 10MB. Pass URLs/paths for large data.

Exception hierarchy: `FlashRuntimeError` > `RemoteExecutionError`, `SerializationError`, `GraphQLError` > `GraphQLMutationError`/`GraphQLQueryError`, `ManifestError`.

## Common Gotchas

1. **External scope in decorated functions** -- #1 error. All imports and logic must be inside the function body.
2. **Forgetting `await`** -- All remote functions must be awaited.
3. **Undeclared dependencies** -- Must be in `dependencies=[]`.
4. **QB vs LB return types** -- QB returns `JobOutput` wrapper, LB returns dict directly.
5. **Large payloads** -- Max 10MB serialization. Pass URLs, not data.
6. **Bundle too large (>500MB)** -- Use `flash build --exclude` for packages in base image.
7. **Mixing patterns** -- Cannot use `@Endpoint(...)` as decorator AND `.get()`/`.post()` on same instance.
8. **Client vs decorator** -- `Endpoint(id=...)` and `Endpoint(image=...)` are clients, not decorators.
9. **Endpoints accumulate** -- Clean up with `flash undeploy`.
