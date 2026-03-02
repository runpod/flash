## Flash SDK Reference

This section documents the complete Flash SDK API. Reference this section when building applications.

### Overview

**runpod-flash** is the underlying SDK powering the Flash framework. It provides:
- The `Endpoint` class for configuring and decorating distributed workers
- GPU/CPU specifications and scaling configuration
- Queue-based (reliable, retry-enabled) and load-balanced (low-latency HTTP) execution models
- Client mode for calling external images and existing endpoints

**Import from `runpod_flash`, not `flash`.** The Flash CLI wraps runpod-flash functionality.

### Main Exports

Core imports for Flash applications:

```python
# unified endpoint class (primary API)
from runpod_flash import Endpoint, EndpointJob

# GPU and CPU specifications
from runpod_flash import GpuType, GpuGroup, CpuInstanceType

# advanced features
from runpod_flash import (
    NetworkVolume,
    PodTemplate,
    CudaVersion,
    DataCenter,
    ServerlessScalerType,
    FlashApp,
)
```

### The Endpoint Class

`Endpoint` is the single entry point for configuring flash workers. It replaces the previous 8-class resource hierarchy and the `@remote` decorator.

#### Usage Modes

**1. Queue-Based (QB) -- one function per endpoint:**

```python
from runpod_flash import Endpoint, GpuType

@Endpoint(name="my-worker", gpu=GpuType.ANY, workers=(0, 3))
async def process(data: dict) -> dict:
    return {"result": data}
```

**2. Load-Balanced (LB) -- multiple HTTP routes, shared workers:**

```python
from runpod_flash import Endpoint, GpuGroup

api = Endpoint(name="my-api", gpu=GpuGroup.ADA_24, workers=(1, 5))

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/compute")
async def compute(request: dict) -> dict:
    return {"result": request}
```

**3. External Image (deploy a pre-built image, call it as a client):**

```python
from runpod_flash import Endpoint

vllm = Endpoint(name="vllm", image="vllm/vllm-openai:latest", gpu=GpuGroup.ADA_24)

result = await vllm.post("/v1/completions", {"prompt": "hello"})
models = await vllm.get("/v1/models")
```

**4. Existing Endpoint (connect to an already-deployed endpoint by id):**

```python
from runpod_flash import Endpoint

ep = Endpoint(id="abc123")

job = await ep.runsync({"prompt": "hello"})
print(job.output)
```

#### How Mode Is Determined

- `@Endpoint(...)` on a function or class = QB (queue-based)
- `ep = Endpoint(...)` then `@ep.get("/path")` = LB (load-balanced)
- `image=` set = deploys the image, then client mode
- `id=` set = pure client, no provisioning
- Live vs deploy is determined by the runtime environment (`flash run` vs `flash deploy`)

#### Complete Signature

```python
Endpoint(
    name: str = None,                    # endpoint name (required unless id= is set)
    *,
    id: str = None,                      # connect to existing endpoint (client mode)
    gpu: GpuGroup | GpuType | list = None,  # GPU type(s); default GpuType.ANY
    cpu: str | CpuInstanceType | list = None,  # CPU instance(s); mutually exclusive with gpu
    workers: int | tuple[int, int] = None,  # (min, max) or just max; default (0, 1)
    idle_timeout: int = 60,              # seconds before idle worker terminates
    dependencies: list[str] = None,      # pip packages to install
    system_dependencies: list[str] = None,  # apt packages to install
    accelerate_downloads: bool = True,   # CDN acceleration for dependency downloads
    volume: NetworkVolume = None,        # persistent storage
    datacenter: DataCenter = DataCenter.EU_RO_1,
    env: dict[str, str] = None,          # environment variables
    gpu_count: int = 1,                  # GPUs per worker
    execution_timeout_ms: int = 0,       # function timeout (0 = no limit)
    flashboot: bool = True,              # enable flashboot
    image: str = None,                   # deploy a pre-built image (client mode)
    scaler_type: ServerlessScalerType = ServerlessScalerType.QUEUE_DELAY,
    scaler_value: int = 4,              # scaling threshold
    template: PodTemplate = None,        # custom pod configuration
)
```

#### Key Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | Required | Unique endpoint name |
| `gpu` | `GpuType/GpuGroup/list` | `GpuType.ANY` | GPU type(s) for this endpoint |
| `cpu` | `str/CpuInstanceType/list` | `None` | CPU instance type(s); mutually exclusive with `gpu` |
| `workers` | `int/(min, max)` | `(0, 1)` | Worker scaling. `3` means `(0, 3)`. `(1, 5)` means min=1, max=5 |
| `idle_timeout` | `int` | `60` | Seconds before idle worker terminates |
| `dependencies` | `list[str]` | `None` | Python packages to install (pip) |
| `system_dependencies` | `list[str]` | `None` | System packages to install (apt-get) |
| `scaler_type` | `ServerlessScalerType` | `QUEUE_DELAY` | Auto-scaling strategy |
| `scaler_value` | `int` | `4` | Scaling threshold for the chosen strategy |
| `template` | `PodTemplate` | `None` | Custom pod config (docker args, disk size, etc.) |
| `image` | `str` | `None` | Deploy a pre-built Docker image (client mode) |
| `id` | `str` | `None` | Connect to existing endpoint by id (client mode) |

#### Return Behavior

QB-decorated functions are always awaitable:

```python
@Endpoint(name="worker", gpu=GpuType.ANY)
async def my_function(data: dict) -> dict:
    return {"result": "success"}

result = await my_function({"input": "value"})
```

### EndpointJob

`EndpointJob` wraps the response from `Endpoint.run()` and `Endpoint.runsync()`. It provides property-based access and async polling.

```python
ep = Endpoint(id="abc123")

# submit async job
job = await ep.run({"prompt": "hello"})
job.id       # "job-abc123"

# poll for status
await job.status()  # "IN_PROGRESS"
await job.status()  # "COMPLETED"
job.output          # {"text": "world"}
job.done            # True

# or wait in one call
job = await ep.run({"prompt": "hello"})
await job.wait(timeout=30)
print(job.output)

# cancel a job
await job.cancel()
```

| Property/Method | Description |
|----------------|-------------|
| `job.id` | Job ID assigned by RunPod |
| `job.output` | Job output payload (available after COMPLETED) |
| `job.error` | Error message (available after FAILED) |
| `job.done` | True if job reached a terminal status |
| `await job.status()` | Poll for current status, update internal state |
| `await job.wait(timeout=)` | Poll until terminal status with exponential backoff |
| `await job.cancel()` | Cancel the job |

### Queue-Based Endpoints

Use `@Endpoint(...)` as a decorator on a single function. Each decorated function gets its own endpoint with its own workers.

#### GPU Worker

```python
from runpod_flash import Endpoint, GpuType

@Endpoint(
    name="ml-inference",
    gpu=GpuType.ANY,
    workers=(0, 3),
    dependencies=["torch>=2.0.0", "transformers>=4.30.0"],
)
async def inference(data: dict) -> dict:
    import torch
    from transformers import pipeline

    nlp = pipeline("text-generation")
    result = nlp(data["prompt"])
    return {"output": result}

result = await inference({"prompt": "hello"})
```

#### CPU Worker

```python
from runpod_flash import Endpoint

@Endpoint(name="data-processor", cpu="cpu3c-1-2", workers=(0, 5))
async def process_data(items: list) -> dict:
    results = [str(item).upper() for item in items]
    return {"processed": len(results)}
```

#### Auto-Scaling Configuration

```python
from runpod_flash import Endpoint, GpuGroup, ServerlessScalerType

@Endpoint(
    name="scale-to-zero",
    gpu=GpuGroup.ANY,
    workers=(0, 3),
    idle_timeout=5,
    scaler_type=ServerlessScalerType.QUEUE_DELAY,
    scaler_value=4,
)
async def scale_to_zero_inference(payload: dict) -> dict:
    return {"result": payload}

@Endpoint(
    name="high-throughput",
    gpu=GpuGroup.ADA_24,
    workers=(2, 10),
    scaler_type=ServerlessScalerType.REQUEST_COUNT,
    scaler_value=50,
)
async def high_throughput(payload: dict) -> dict:
    return {"result": payload}
```

#### Custom Pod Template

```python
from runpod_flash import Endpoint, GpuGroup, PodTemplate

template = PodTemplate(
    imageName="runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
    containerDiskInGb=30,
    dockerArgs="--shm-size=2g",
    startScript="echo 'Worker starting'",
    ports="8080/http",
)

@Endpoint(name="custom-image", gpu=GpuGroup.ADA_24, template=template)
async def process(data: dict) -> dict:
    return {"result": data}
```

#### Class-Based Workers (Stateful)

Decorate a class to keep state (e.g., loaded models) across requests:

```python
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="sd-worker", gpu=GpuGroup.ADA_24, dependencies=["diffusers", "torch"])
class SimpleSD:
    def __init__(self):
        from diffusers import StableDiffusionPipeline
        self.pipe = StableDiffusionPipeline.from_pretrained("runwayml/stable-diffusion-v1-5")
        self.pipe = self.pipe.to("cuda")

    async def generate_image(self, prompt: str) -> dict:
        image = self.pipe(prompt=prompt, num_inference_steps=20).images[0]
        image.save("/tmp/output.png")
        return {"image_path": "/tmp/output.png"}
```

The class is instantiated once at worker startup. The model stays in GPU memory and every request calls methods on the same instance.

### Load-Balanced Endpoints

Create an `Endpoint` instance and register routes with `.get()`, `.post()`, `.put()`, `.delete()`, `.patch()`. All routes share the same workers.

```python
from runpod_flash import Endpoint, GpuGroup

api = Endpoint(name="user-service", gpu=GpuGroup.ADA_24, workers=(1, 5))

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/users")
async def create_user(name: str, email: str):
    return {"id": 1, "name": name, "email": email}

@api.get("/users/{user_id}")
def get_user(user_id: int):
    return {"id": user_id, "name": "Alice"}

@api.delete("/users/{user_id}")
async def delete_user(user_id: int):
    return {"deleted": True}
```

#### CPU Load-Balanced Endpoint

```python
from runpod_flash import Endpoint

api = Endpoint(name="cpu-api", cpu="cpu3c-1-2", workers=(1, 3))

@api.post("/process")
async def process(data: dict) -> dict:
    return {"echo": data}

@api.get("/health")
async def health():
    return {"status": "healthy"}
```

#### Reserved Paths

The following paths are reserved and cannot be used as routes:
- `/execute` -- framework endpoint for internal function execution
- `/ping` -- health check endpoint

### GPU Types and Groups

#### GpuType (Specific GPU Model)

Use `GpuType` when you need a specific GPU model:

```python
from runpod_flash import GpuType

GpuType.ANY                           # any available GPU
GpuType.NVIDIA_GEFORCE_RTX_4090      # RTX 4090, 24GB
GpuType.NVIDIA_L4                     # L4, 24GB
GpuType.NVIDIA_A100_80GB_PCIE        # A100, 80GB
# ... and more
```

#### GpuGroup (GPU Family/Tier)

Use `GpuGroup` when you want any GPU in a performance tier:

```python
from runpod_flash import GpuGroup

# ampere GPUs
GpuGroup.AMPERE_16    # RTX A4000, 16GB VRAM
GpuGroup.AMPERE_24    # RTX A5000, 24GB VRAM
GpuGroup.AMPERE_48    # A40, RTX A6000, 48GB VRAM
GpuGroup.AMPERE_80    # A100, 80GB VRAM

# ada GPUs
GpuGroup.ADA_24       # RTX 4090, 24GB VRAM
GpuGroup.ADA_32_PRO   # RTX 5090, 32GB VRAM
GpuGroup.ADA_48_PRO   # RTX 6000 Ada, 48GB VRAM
GpuGroup.ADA_80_PRO   # H100, 80GB VRAM

# hopper GPUs
GpuGroup.HOPPER_141   # H200, 141GB VRAM

# flexible
GpuGroup.ANY          # any available GPU (expands to all groups)
```

**When to use which:**
- `GpuType` for simple examples or when targeting a specific card
- `GpuGroup` for production when you want any GPU in a tier for better availability and scale

### CPU Instance Types

```python
from runpod_flash import Endpoint

# pass as string
@Endpoint(name="worker", cpu="cpu3c-1-2")
async def process(data: dict) -> dict:
    return data

# or use the enum
from runpod_flash import CpuInstanceType

@Endpoint(name="worker", cpu=CpuInstanceType.CPU3G_2_8)
async def process(data: dict) -> dict:
    return data
```

### Function Requirements

#### Cloudpickle Scoping Rules

Functions decorated with `@Endpoint(...)` are serialized using cloudpickle and executed remotely. They can ONLY access:

1. **Function parameters** passed at call time
2. **Local variables** defined inside the function
3. **Imports** done inside the function
4. **Built-in Python functions** (print, len, etc.)

They CANNOT access:
- Module-level imports
- Global variables
- Functions/classes defined outside the function
- Module-level constants

```python
# wrong -- external references
import torch

@Endpoint(name="worker", gpu=GpuType.ANY)
async def inference(prompt: str) -> dict:
    device = torch.device("cuda")  # torch not accessible

# correct -- everything inside function
@Endpoint(name="worker", gpu=GpuType.ANY)
async def inference(prompt: str) -> dict:
    import torch
    device = torch.device("cuda")
    model = torch.load("model.pt")
    return {"result": model.generate(prompt)}
```

**Exception**: `Endpoint` parameters (gpu, workers, etc.) are evaluated at decoration time, so they can reference external variables:

```python
my_gpu = GpuType.ANY

@Endpoint(name="worker", gpu=my_gpu)  # OK
async def my_function(data: dict) -> dict:
    return {"status": "ok"}
```

#### Must Be Async

```python
# correct
@Endpoint(name="worker", gpu=GpuType.ANY)
async def my_function(data: dict) -> dict:
    return data
```

#### Arguments Must Be Serializable

Standard types work: dict, list, tuple, set, str, int, float, bool, None, numpy arrays, pydantic models. Pass data identifiers (URLs, S3 paths) instead of large objects.

### Dependency Management

#### Python Dependencies (pip)

```python
@Endpoint(
    name="worker",
    gpu=GpuType.ANY,
    dependencies=["torch>=2.0.0", "transformers==4.30.2", "numpy"],
)
async def my_function(data: dict) -> dict:
    import torch
    return {"status": "ok"}
```

#### System Dependencies (apt-get)

```python
@Endpoint(
    name="worker",
    gpu=GpuType.ANY,
    system_dependencies=["build-essential", "ffmpeg"],
)
async def process_video(video_url: str) -> dict:
    import subprocess
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
    return {"ffmpeg": "available"}
```

### Network Volumes

```python
from runpod_flash import Endpoint, NetworkVolume, GpuGroup

volume = NetworkVolume(name="model_storage", size=50)

@Endpoint(name="inference", gpu=GpuGroup.AMPERE_80, volume=volume)
async def inference(prompt: str) -> dict:
    import torch
    model = torch.load("/runpod-volume/model.bin")
    return {"output": model.generate(prompt)}
```

### Environment Variables

```python
@Endpoint(
    name="worker",
    gpu=GpuType.ANY,
    env={"MODEL_SIZE": "large", "LOG_LEVEL": "DEBUG"},
)
async def configurable_function(data: dict) -> dict:
    import os
    model_size = os.getenv("MODEL_SIZE", "small")
    return {"size": model_size}
```

### Client Mode

#### External Image

Deploy a pre-built Docker image and call it as an API client:

```python
from runpod_flash import Endpoint, GpuGroup

vllm = Endpoint(
    name="vllm-server",
    image="vllm/vllm-openai:latest",
    gpu=GpuGroup.ADA_24,
    workers=(1, 3),
)

# LB-style calls
result = await vllm.post("/v1/completions", {"prompt": "hello"})
models = await vllm.get("/v1/models")

# QB-style calls
job = await vllm.run({"prompt": "hello"})
await job.wait()
print(job.output)
```

#### Existing Endpoint

Connect to an already-deployed endpoint by ID:

```python
from runpod_flash import Endpoint

ep = Endpoint(id="abc123")

# synchronous call
job = await ep.runsync({"prompt": "hello"})
print(job.output)

# async call with polling
job = await ep.run({"prompt": "hello"})
await job.wait(timeout=60)
print(job.output)

# cancel
await job.cancel()
```

### Cost Optimization

```python
from runpod_flash import Endpoint, GpuGroup

# scale from zero -- cheapest
@Endpoint(
    name="cost-optimized",
    gpu=GpuGroup.AMPERE_24,
    workers=(0, 3),
    idle_timeout=300,
)
async def cheap_inference(data: dict) -> dict:
    return {"result": data}

# right-sized GPU -- use the smallest GPU that fits your model
@Endpoint(
    name="right-sized",
    gpu=GpuGroup.AMPERE_24,
    workers=3,
    idle_timeout=600,
)
async def efficient_inference(data: dict) -> dict:
    return {"result": data}
```

### Common Gotchas

1. **Accessing external scope**: only local variables accessible inside decorated functions.

2. **Forgetting `await`**: all remote functions must be awaited.
   ```python
   result = await my_remote_function(data)  # correct
   ```

3. **Undeclared dependencies**: list all pip packages in `dependencies=`.
   ```python
   @Endpoint(name="worker", gpu=GpuType.ANY, dependencies=["numpy"])
   async def my_function(data: dict) -> dict:
       import numpy as np  # available
   ```

4. **GPU vs CPU confusion**: `gpu=` and `cpu=` are mutually exclusive.
   ```python
   # GPU endpoint (default)
   @Endpoint(name="worker", gpu=GpuType.ANY)

   # CPU endpoint
   @Endpoint(name="worker", cpu="cpu3c-1-2")
   ```

5. **QB vs LB confusion**: `@Endpoint(...)` on a function = QB. `ep = Endpoint(...)` + `@ep.post()` = LB.

### Legacy API (Deprecated)

The following classes and the `@remote` decorator are deprecated and will be removed in a future release. Use `Endpoint` instead.

| Deprecated | Replacement |
|-----------|-------------|
| `@remote(resource_config=LiveServerless(...))` | `@Endpoint(name=..., gpu=...)` |
| `@remote(resource_config=CpuLiveServerless(...))` | `@Endpoint(name=..., cpu=...)` |
| `@remote(resource_config=LiveLoadBalancer(...), method=..., path=...)` | `ep = Endpoint(...)` + `@ep.post("/path")` |
| `@remote(resource_config=CpuLiveLoadBalancer(...), method=..., path=...)` | `ep = Endpoint(..., cpu=...)` + `@ep.post("/path")` |
| `ServerlessEndpoint`, `CpuServerlessEndpoint` | `Endpoint` (deploy-mode classes are selected internally) |
| `LoadBalancerSlsResource`, `CpuLoadBalancerSlsResource` | `Endpoint` (LB classes are selected internally) |
