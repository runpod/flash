---
name: flash
description: Complete knowledge of runpod-flash - the Endpoint class, CLI, deployment, architecture.
  Triggers on "flash", "runpod-flash", "Endpoint", "serverless", "deploy", "GpuType", "GpuGroup".
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash
---

# Runpod Flash

**runpod-flash** (v1.6.0) is a Python SDK for distributed inference and serving on Runpod serverless. Write Python functions locally, configure with the `Endpoint` class, and Flash handles GPU/CPU provisioning, dependency management, and data transfer.

- **Package**: `pip install runpod-flash`
- **Import**: `from runpod_flash import Endpoint, GpuGroup, GpuType, ...`
- **CLI**: `flash`
- **Python**: >=3.10, <3.15

## Getting Started

### 1. Install Flash

```bash
pip install runpod-flash
```

### 2. Authenticate

Either log in via browser (recommended):

```bash
flash login
```

Or set your API key manually. Get a key from [Runpod account settings](https://docs.runpod.io/get-started/api-keys):

```bash
export RUNPOD_API_KEY=your_api_key_here
```

Or save in a `.env` file (Flash auto-loads via `python-dotenv`):

```bash
echo "RUNPOD_API_KEY=your_api_key_here" > .env
```

### 3. Write and run a remote function

```python
import asyncio
from runpod_flash import Endpoint, GpuType

@Endpoint(name="my-first-worker", gpu=GpuType.ANY, dependencies=["torch"])
async def gpu_task(data):
    import torch
    tensor = torch.tensor(data, device="cuda")
    return {"sum": tensor.sum().item(), "gpu": torch.cuda.get_device_name(0)}

async def main():
    result = await gpu_task([1, 2, 3, 4, 5])
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

First run takes ~1 minute (endpoint provisioning). Subsequent runs take ~1 second.

### 4. Or create a Flash API project

```bash
flash init my_project
cd my_project
pip install -r requirements.txt
# Edit .env and add your RUNPOD_API_KEY
flash run                    # Start local FastAPI server at localhost:8888
```

API explorer available at `http://localhost:8888/docs`.

### 5. Build and deploy to production

```bash
flash build                              # Scan endpoints, package artifact
flash build --exclude torch,torchvision  # Exclude packages in base image (500MB limit)
flash deploy new production              # Create deployment environment
flash deploy send production             # Upload and deploy
flash deploy list                        # List environments
flash deploy info production             # Show details
flash deploy delete production           # Tear down
```

## The Endpoint Class: Four Modes

The `Endpoint` class is the single entry point for all Flash functionality. It replaces the old 8-class resource hierarchy (`LiveServerless`, `CpuLiveServerless`, etc.) which still works but emits `DeprecationWarning`.

### Mode 1: Queue-Based Decorator (QB)

One function = one endpoint = own workers. Best for batch processing, long-running tasks, automatic retries.

```python
from runpod_flash import Endpoint, GpuType

@Endpoint(name="gpu_worker", gpu=GpuType.ANY, dependencies=["torch"])
async def gpu_hello(input_data: dict) -> dict:
    import torch
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else "No GPU"
    return {
        "message": input_data.get("message", "Hello from GPU worker!"),
        "gpu": {"available": gpu_available, "name": gpu_name},
    }
```

QB returns a `JobOutput` with `.output`, `.error`, `.status` fields:

```python
result = await gpu_hello({"message": "test"})
# result.output contains the return dict
```

### Mode 2: Load-Balanced Decorator (LB)

Multiple routes, shared workers. Best for real-time APIs, low-latency HTTP.

```python
from runpod_flash import Endpoint

api = Endpoint(name="lb_worker", cpu="cpu3c-1-2", workers=(1, 3))

@api.post("/process")
async def process(input_data: dict) -> dict:
    from datetime import datetime
    return {"status": "success", "echo": input_data, "timestamp": datetime.now().isoformat()}

@api.get("/health")
async def health() -> dict:
    return {"status": "healthy"}
```

LB returns the dict directly (no `JobOutput` wrapper). Supported methods: `GET`, `POST`, `PUT`, `DELETE`, `PATCH`. Reserved paths: `/execute`, `/ping`.

### Mode 3: External Image Client

Deploy a pre-built Docker image and call it as a client. No `@decorator` -- the Endpoint provisions the image and provides QB and LB client methods.

```python
from runpod_flash import Endpoint, GpuGroup

vllm = Endpoint(name="vllm", image="vllm/vllm-openai:latest", gpu=GpuGroup.ADA_24)

# LB-style calls
result = await vllm.post("/v1/completions", {"prompt": "hello"})
models = await vllm.get("/v1/models")

# QB-style calls
job = await vllm.run({"prompt": "hello"})
await job.wait()
print(job.output)
```

### Mode 4: Existing Endpoint Client

Connect to an already-deployed endpoint by ID. No provisioning.

```python
from runpod_flash import Endpoint

ep = Endpoint(id="abc123")

# QB-style
job = await ep.runsync({"prompt": "hello"})
print(job.output)

# LB-style
result = await ep.post("/v1/completions", {"prompt": "hello"})
```

## Constructor Parameters

```python
Endpoint(
    name: str = None,                    # Endpoint name (required unless id= is set)
    *,
    id: str = None,                      # Connect to existing endpoint (client mode)
    gpu: GpuGroup | GpuType | list = None,  # GPU type(s) -- mutually exclusive with cpu
    cpu: str | CpuInstanceType | list = None, # CPU type(s) -- mutually exclusive with gpu
    workers: int | tuple[int, int] = None,    # Max workers (int) or (min, max) tuple. Default: (0, 1)
    idle_timeout: int = 60,              # Seconds before scale-down
    dependencies: list[str] = None,      # pip packages to install
    system_dependencies: list[str] = None, # apt-get packages to install
    accelerate_downloads: bool = True,   # CDN download acceleration
    volume: NetworkVolume = None,        # Persistent storage
    datacenter: DataCenter = DataCenter.EU_RO_1,  # Data center location
    env: dict[str, str] = None,          # Environment variables
    gpu_count: int = 1,                  # GPUs per worker
    execution_timeout_ms: int = 0,       # Execution timeout (0 = no limit)
    flashboot: bool = True,              # FlashBoot for fast cold starts
    image: str = None,                   # Docker image (external image mode, mutually exclusive with id)
    scaler_type: ServerlessScalerType = None,  # QUEUE_DELAY (QB default) or REQUEST_COUNT (LB default)
    scaler_value: int = 4,               # Scaler parameter
    template: PodTemplate = None,        # Pod template overrides
)
```

**Mutual exclusions:**
- `gpu` and `cpu` cannot both be set
- `id` and `image` cannot both be set
- `name` or `id` is required

**Defaults:**
- If neither `gpu` nor `cpu` is set (and not client mode), defaults to `gpu=GpuGroup.ANY`
- `workers=5` means `(0, 5)`. `workers=(2, 5)` means min 2, max 5.

## EndpointJob

Returned by `Endpoint.run()` and `Endpoint.runsync()` in client mode (image= or id=).

```python
job = await ep.run({"prompt": "hello"})

# Properties
job.id        # "job-abc123"
job.output    # Result payload (after COMPLETED)
job.error     # Error message (after FAILED)
job.done      # True if terminal status (COMPLETED, FAILED, CANCELLED, TIMED_OUT)

# Methods
await job.status()            # Poll, update internal state, return status string
await job.wait(timeout=60)    # Poll until terminal status (exponential backoff)
await job.cancel()            # Cancel the job
```

## GPU & CPU Types

### GPU Groups (GpuGroup enum)

VRAM-class groups that map to one or more specific GPU models:

| Group | VRAM | GPUs |
|-------|------|------|
| `GpuGroup.ANY` | Any | Any available (not for production) |
| `GpuGroup.AMPERE_16` | 16GB | RTX A4000, RTX A4500, RTX 4000 Ada, RTX 2000 Ada |
| `GpuGroup.AMPERE_24` | 24GB | RTX A5000, L4, RTX 3090 |
| `GpuGroup.ADA_24` | 24GB | RTX 4090 |
| `GpuGroup.ADA_32_PRO` | 32GB | RTX 5090 |
| `GpuGroup.AMPERE_48` | 48GB | A40, RTX A6000 |
| `GpuGroup.ADA_48_PRO` | 48GB | RTX 6000 Ada, L40, L40S |
| `GpuGroup.AMPERE_80` | 80GB | A100 80GB PCIe, A100-SXM4-80GB |
| `GpuGroup.ADA_80_PRO` | 80GB | H100 PCIe, H100 80GB HBM3, H100 NVL |
| `GpuGroup.HOPPER_141` | 141GB | H200 |

### GPU Types (GpuType enum)

Specific GPU models for exact hardware selection:

`NVIDIA_GEFORCE_RTX_4090`, `NVIDIA_GEFORCE_RTX_5090`, `NVIDIA_RTX_6000_ADA_GENERATION`, `NVIDIA_H100_80GB_HBM3`, `NVIDIA_RTX_A4000`, `NVIDIA_RTX_A4500`, `NVIDIA_RTX_4000_ADA_GENERATION`, `NVIDIA_RTX_2000_ADA_GENERATION`, `NVIDIA_RTX_A5000`, `NVIDIA_L4`, `NVIDIA_GEFORCE_RTX_3090`, `NVIDIA_A40`, `NVIDIA_RTX_A6000`, `NVIDIA_A100_80GB_PCIe`, `NVIDIA_A100_SXM4_80GB`, `NVIDIA_H200`

Usage: `gpu=GpuType.NVIDIA_GEFORCE_RTX_4090` or `gpu=[GpuType.NVIDIA_A100_80GB_PCIe, GpuType.NVIDIA_A100_SXM4_80GB]`

### CPU Instance Types (CpuInstanceType enum)

Format: `CPU{generation}{type}_{vcpu}_{memory_gb}`. Can also use string shorthand: `cpu="cpu3c-1-2"`.

| Instance Type | Gen | Type | vCPU | RAM | Max Disk |
|--------------|-----|------|------|-----|----------|
| `CPU3G_1_4` | 3rd | General | 1 | 4GB | 10GB |
| `CPU3G_2_8` | 3rd | General | 2 | 8GB | 20GB |
| `CPU3G_4_16` | 3rd | General | 4 | 16GB | 40GB |
| `CPU3G_8_32` | 3rd | General | 8 | 32GB | 80GB |
| `CPU3C_1_2` | 3rd | Compute | 1 | 2GB | 10GB |
| `CPU3C_2_4` | 3rd | Compute | 2 | 4GB | 20GB |
| `CPU3C_4_8` | 3rd | Compute | 4 | 8GB | 40GB |
| `CPU3C_8_16` | 3rd | Compute | 8 | 16GB | 80GB |
| `CPU5C_1_2` | 5th | Compute | 1 | 2GB | 15GB |
| `CPU5C_2_4` | 5th | Compute | 2 | 4GB | 30GB |
| `CPU5C_4_8` | 5th | Compute | 4 | 8GB | 60GB |
| `CPU5C_8_16` | 5th | Compute | 8 | 16GB | 120GB |

## Cloudpickle Scoping Rules

Functions decorated with `@Endpoint(...)` are serialized with cloudpickle. They can ONLY access:
- Function parameters
- Local variables defined inside the function
- Imports done inside the function
- Built-in Python functions

They CANNOT access: module-level imports, global variables, external functions/classes.

```python
# WRONG - external references
import torch
@Endpoint(name="worker", gpu=GpuGroup.ADA_24)
async def bad(data):
    return torch.tensor(data)  # torch not accessible remotely

# CORRECT - everything inside, dependencies declared
@Endpoint(name="worker", gpu=GpuGroup.ADA_24, dependencies=["torch"])
async def good(data):
    import torch
    return torch.tensor(data)
```

All pip packages must be listed in `dependencies=[]`. System packages go in `system_dependencies=[]`.

## CLI Commands

### flash login

```bash
flash login [--no-open] [--timeout SECONDS]
```

Authenticate via browser. Opens Runpod console for authorization, saves credentials locally.

### flash init

```bash
flash init [project_name]
```

Creates a project with three template workers:
- `gpu_worker.py` -- QB GPU endpoint using `@Endpoint` decorator
- `cpu_worker.py` -- QB CPU endpoint using `@Endpoint` decorator
- `lb_worker.py` -- LB CPU endpoint with `@api.post` and `@api.get` routes

### flash run

```bash
flash run [--host HOST] [--port PORT]
```

Starts a local FastAPI dev server at `localhost:8888` with auto-generated routes for all discovered endpoints. API explorer at `/docs`.

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `localhost` | Server host (or `FLASH_HOST` env) |
| `--port` | `8888` | Server port (or `FLASH_PORT` env) |

### flash build

```bash
flash build [--exclude PACKAGES] [--keep-build] [--preview]
```

Scans `@Endpoint` decorators, groups by resource config, creates `flash_manifest.json`, installs dependencies for Linux x86_64, packages into `.flash/artifact.tar.gz`.

| Option | Description |
|--------|-------------|
| `--exclude pkg1,pkg2` | Skip packages already in base Docker image |
| `--keep-build` | Don't delete `.flash/.build/` after packaging |
| `--preview` | Build then run in local Docker containers |

**500MB deployment limit** -- use `--exclude` for packages in base image:

```bash
flash build --exclude torch,torchvision,torchaudio
```

**`--preview` mode**: Creates Docker containers per resource config, starts mothership on `localhost:8000`, enables end-to-end local testing.

### flash deploy

```bash
flash deploy new <env_name> [--app-name NAME]   # Create environment
flash deploy send <env_name> [--app-name NAME]   # Deploy archive
flash deploy list [--app-name NAME]               # List environments
flash deploy info <env_name> [--app-name NAME]    # Show details
flash deploy delete <env_name> [--app-name NAME]  # Delete (double confirmation)
```

`flash deploy send` requires `flash build` to have been run first.

### flash undeploy

```bash
flash undeploy list          # List all deployed resources
flash undeploy <name>        # Undeploy specific resource
```

### flash env / flash app

```bash
flash env list|create|get|delete <name>   # Environment management
flash app list|get <name>                 # App management
```

## Common Patterns

### QB GPU Endpoint

```python
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="inference", gpu=GpuGroup.AMPERE_80, workers=(0, 3), dependencies=["torch"])
async def inference(data: dict) -> dict:
    import torch
    tensor = torch.tensor(data["values"], device="cuda")
    return {"result": tensor.sum().item()}
```

### QB CPU Endpoint

```python
from runpod_flash import Endpoint

@Endpoint(name="cpu_worker", cpu="cpu3c-1-2")
async def cpu_hello(input_data: dict) -> dict:
    import platform
    from datetime import datetime
    return {
        "message": input_data.get("message", "Hello from CPU worker!"),
        "timestamp": datetime.now().isoformat(),
        "python_version": platform.python_version(),
    }
```

### LB HTTP API

```python
from runpod_flash import Endpoint

api = Endpoint(name="my-api", gpu=GpuGroup.ADA_24, workers=(1, 5))

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/compute")
async def compute(request: dict) -> dict:
    return {"result": request}
```

### External Image Deployment

```python
from runpod_flash import Endpoint, GpuGroup

vllm = Endpoint(name="vllm-server", image="vllm/vllm-openai:latest", gpu=GpuGroup.ADA_80_PRO)
result = await vllm.post("/v1/completions", {"prompt": "hello", "model": "meta-llama/Llama-3-8B"})
```

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

### Parallel Execution

```python
import asyncio

results = await asyncio.gather(
    process_item(item1),
    process_item(item2),
    process_item(item3),
)
```

### NetworkVolume

```python
from runpod_flash import Endpoint, GpuGroup, NetworkVolume, DataCenter

volume = NetworkVolume(name="model-storage", size=100, dataCenterId=DataCenter.EU_RO_1)

@Endpoint(name="worker", gpu=GpuGroup.AMPERE_80, volume=volume)
async def worker(data: dict) -> dict:
    ...
```

### PodTemplate

```python
from runpod_flash import Endpoint, GpuGroup, PodTemplate

template = PodTemplate(containerDiskInGb=100)

@Endpoint(name="worker", gpu=GpuGroup.AMPERE_80, template=template)
async def worker(data: dict) -> dict:
    ...
```

## Error Handling

### Queue-Based (QB) Resources

```python
job_output = await my_function(data)
if job_output.error:
    print(f"Failed: {job_output.error}")
else:
    result = job_output.output
```

`JobOutput` fields: `id`, `status`, `output`, `error`, `started_at`, `ended_at`

### Load-Balanced (LB) Resources

```python
try:
    result = await my_function(data)  # Returns dict directly
except Exception as e:
    print(f"Error: {e}")
```

### EndpointJob (Client Mode)

```python
job = await ep.run({"prompt": "hello"})
await job.wait(timeout=120)
if job.error:
    print(f"Failed: {job.error}")
else:
    print(job.output)
```

### Runtime Exceptions

```
FlashRuntimeError (base)
  RemoteExecutionError      # Remote function failed
  SerializationError        # cloudpickle serialization failed
  GraphQLError              # GraphQL base error
    GraphQLMutationError    # Mutation failed
    GraphQLQueryError       # Query failed
  ManifestError             # Invalid/missing manifest
  ManifestServiceUnavailableError  # State Manager unreachable
```

## Architecture Overview

### Deployment Architecture

**Mothership Pattern**: Coordinator endpoint + distributed child endpoints.

1. `flash build` scans code, creates manifest + archive
2. `flash deploy send` uploads archive, provisions resources
3. Mothership boots, reconciles desired vs current state
4. Child endpoints query State Manager GraphQL for service discovery (peer-to-peer)
5. Functions route locally or remotely based on manifest

### How Endpoint Resolves to Internal Classes

The `Endpoint` class automatically selects the right internal resource class based on:
- **QB vs LB**: Inferred from usage (direct `@Endpoint` decorator = QB, `.get()`/`.post()` routes = LB)
- **GPU vs CPU**: From `gpu=` or `cpu=` parameter
- **Live vs Deploy**: From runtime environment (`flash run` = live, `flash deploy` = deploy classes)

This means 8 internal classes are selected automatically -- users never need to pick one.

### Cross-Endpoint Routing

Functions on different endpoints can call each other transparently:
1. `ProductionWrapper` intercepts calls
2. `ServiceRegistry` looks up function in manifest
3. Local function? Execute directly
4. Remote function? Serialize args (cloudpickle), POST to remote endpoint

**Serialization**: cloudpickle + base64, max 10MB payload. Pass URLs/paths instead of large data.

## Common Gotchas

1. **External scope in decorated functions** -- Most common error. All imports and logic must be inside the function body.
2. **Forgetting `await`** -- All remote functions must be awaited.
3. **Undeclared dependencies** -- Must be in `dependencies=[]` parameter.
4. **QB vs LB return types** -- QB returns `JobOutput` wrapper, LB returns dict directly.
5. **Large serialization** -- Max 10MB. Pass URLs/paths, not large data objects.
6. **Imports at module level** -- Import inside decorated functions, not at top of file.
7. **Bundle too large (>500MB)** -- Use `--exclude` for packages in base Docker image.
8. **Endpoints accumulate** -- Clean up with `flash undeploy list` / `flash undeploy <name>`.
9. **Mixing decorator patterns** -- Cannot use `@Endpoint(...)` as direct decorator AND register routes (`.get()`/`.post()`) on the same instance.
10. **Client mode restrictions** -- `Endpoint(id=...)` and `Endpoint(image=...)` are clients, not decorators. Cannot use `@ep.post("/path")` to register routes on a client.
