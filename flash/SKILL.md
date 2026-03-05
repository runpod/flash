---
name: flash
description: Complete knowledge of the runpod-flash framework - SDK, CLI, architecture, deployment, and codebase. Use when working with runpod-flash code, writing Endpoint classes, configuring GPU/CPU endpoints, debugging deployments, or understanding the framework internals. Triggers on "flash", "runpod-flash", "Endpoint", "serverless", "deploy", "GpuGroup", "CpuInstanceType", "EndpointJob", "remote GPU".
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash
---

# Runpod Flash (v1.7.0)

Python SDK for running AI workloads on RunPod serverless. One class -- `Endpoint` -- handles everything.

`pip install runpod-flash` | `from runpod_flash import Endpoint, GpuGroup` | Python >=3.10 | Source: `src/runpod_flash/`

## Endpoint: Three Modes

### Mode 1: Your Code (Queue-Based Decorator)

One function = one endpoint with its own workers.

```python
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="my-worker", gpu=GpuGroup.AMPERE_80, workers=3, dependencies=["torch"])
async def compute(data):
    import torch  # MUST import inside function (cloudpickle)
    return {"sum": torch.tensor(data, device="cuda").sum().item()}

result = await compute([1, 2, 3])
```

### Mode 2: Your Code (Load-Balanced Routes)

Multiple HTTP routes share one pool of workers.

```python
from runpod_flash import Endpoint, GpuGroup

api = Endpoint(name="my-api", gpu=GpuGroup.ADA_24, workers=(1, 5), dependencies=["torch"])

@api.post("/predict")
async def predict(data: list[float]):
    import torch
    return {"result": torch.tensor(data, device="cuda").sum().item()}

@api.get("/health")
async def health():
    return {"status": "ok"}
```

### Mode 3: External Image (Client)

Deploy a pre-built Docker image and call it via HTTP.

```python
from runpod_flash import Endpoint, GpuGroup, PodTemplate

server = Endpoint(
    name="my-server",
    image="my-org/my-image:latest",
    gpu=GpuGroup.AMPERE_80,
    workers=1,
    env={"HF_TOKEN": "xxx"},
    template=PodTemplate(containerDiskInGb=100),
)

# LB-style
result = await server.post("/v1/completions", {"prompt": "hello"})
models = await server.get("/v1/models")

# QB-style
job = await server.run({"prompt": "hello"})
await job.wait()
print(job.output)
```

Connect to an existing endpoint by ID (no provisioning):

```python
ep = Endpoint(id="abc123")
job = await ep.runsync({"input": "hello"})
print(job.output)
```

## How Mode Is Determined

| Parameters | Mode |
|-----------|------|
| `name=` only | Decorator (your code) |
| `image=` set | Client (deploys image, then HTTP calls) |
| `id=` set | Client (connects to existing, no provisioning) |

## Endpoint Constructor

```python
Endpoint(
    name="endpoint-name",                  # required (unless id= set)
    id=None,                               # connect to existing endpoint
    gpu=GpuGroup.AMPERE_80,               # GPU type (default: ANY)
    cpu=CpuInstanceType.CPU5C_4_8,        # CPU type (mutually exclusive with gpu)
    workers=3,                             # shorthand for (0, 3)
    workers=(1, 5),                        # explicit (min, max)
    idle_timeout=60,                       # seconds before scale-down (default: 60)
    dependencies=["torch"],                # pip packages for remote exec
    system_dependencies=["ffmpeg"],        # apt-get packages
    image="org/image:tag",                 # pre-built Docker image (client mode)
    env={"KEY": "val"},                    # environment variables
    volume=NetworkVolume(...),             # persistent storage
    gpu_count=1,                           # GPUs per worker
    template=PodTemplate(containerDiskInGb=100),
    flashboot=True,                        # fast cold starts
)
```

- `gpu=` and `cpu=` are mutually exclusive
- `workers=3` means `(0, 3)`. Default is `(0, 1)`
- `idle_timeout` default is **60 seconds**

## Cloudpickle Scoping (CRITICAL)

Decorated functions are serialized. They can ONLY access:
- Parameters, local variables, imports inside the function, builtins

```python
# WRONG
import torch
@Endpoint(name="w", gpu=GpuGroup.ADA_24, dependencies=["torch"])
async def bad(x):
    return torch.tensor(x)  # NameError

# CORRECT
@Endpoint(name="w", gpu=GpuGroup.ADA_24, dependencies=["torch"])
async def good(x):
    import torch
    return torch.tensor(x)
```

## EndpointJob

Returned by `ep.run()` and `ep.runsync()` in client mode.

```python
job = await ep.run({"data": [1, 2, 3]})
await job.wait(timeout=120)        # poll until done
print(job.id, job.output, job.error, job.done)
await job.cancel()
```

## GPU Types (GpuGroup)

| Enum | GPU | VRAM |
|------|-----|------|
| `ANY` | any | varies |
| `AMPERE_16` | RTX A4000 | 16GB |
| `AMPERE_24` | RTX A5000/L4 | 24GB |
| `AMPERE_48` | A40/A6000 | 48GB |
| `AMPERE_80` | A100 | 80GB |
| `ADA_24` | RTX 4090 | 24GB |
| `ADA_32_PRO` | RTX 5090 | 32GB |
| `ADA_48_PRO` | RTX 6000 Ada | 48GB |
| `ADA_80_PRO` | H100 | 80GB |
| `HOPPER_141` | H200 | 141GB |

## CPU Types (CpuInstanceType)

Format: `CPU{gen}{type}_{vcpu}_{memory_gb}`. Example: `CPU5C_4_8` = 5th gen, compute, 4 vCPU, 8GB.

```python
from runpod_flash import Endpoint, CpuInstanceType

@Endpoint(name="cpu-work", cpu=CpuInstanceType.CPU5C_4_8, workers=5, dependencies=["pandas"])
async def process(data):
    import pandas as pd
    return pd.DataFrame(data).describe().to_dict()
```

## Common Patterns

### CPU + GPU Pipeline

```python
from runpod_flash import Endpoint, GpuGroup, CpuInstanceType

@Endpoint(name="preprocess", cpu=CpuInstanceType.CPU5C_4_8, workers=5, dependencies=["pandas"])
async def preprocess(raw):
    import pandas as pd
    return pd.DataFrame(raw).to_dict("records")

@Endpoint(name="infer", gpu=GpuGroup.AMPERE_80, workers=3, dependencies=["torch"])
async def infer(clean):
    import torch
    t = torch.tensor([[v for v in r.values()] for r in clean], device="cuda")
    return {"predictions": t.mean(dim=1).tolist()}

async def pipeline(data):
    return await infer(await preprocess(data))
```

### Parallel Execution

```python
import asyncio
results = await asyncio.gather(compute(a), compute(b), compute(c))
```

## CLI

| Command | Description |
|---------|-------------|
| `flash init [name]` | Create project template |
| `flash run [--auto-provision]` | Local dev server at localhost:8888 |
| `flash build [--exclude pkg1,pkg2]` | Package artifact (500MB limit) |
| `flash deploy new/send/list/info/delete <env>` | Deploy to production |
| `flash undeploy list/<name>` | Remove endpoints |

## Gotchas

1. **Imports outside function** -- most common error. Everything inside the decorated function.
2. **Forgetting await** -- all decorated functions and client methods need `await`.
3. **Missing dependencies** -- must list in `dependencies=[]`.
4. **gpu/cpu are exclusive** -- pick one per Endpoint.
5. **idle_timeout is seconds** -- default 60s, not minutes.
6. **10MB payload limit** -- pass URLs, not large objects.
7. **Client vs decorator** -- `image=`/`id=` = client. Otherwise = decorator.

## Architecture (for codebase work)

Source: `src/runpod_flash/`. Entry: `endpoint.py` (Endpoint class) delegates to `client.py` (@remote, internal). Build scanner: `cli/commands/build_utils/scanner.py`. Runtime: `runtime/` (handlers, service registry, serialization). Resources: `core/resources/` (internal classes auto-selected by Endpoint). Dev: `make dev`, `make test-unit`, `make lint`, `make format`, `make index`.
