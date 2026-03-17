# Flash SDK Reference

Complete API reference for the `runpod_flash` package.

## Endpoint

The unified class for all Flash functionality. Supports four usage patterns: queue-based (QB) decorator, load-balanced (LB) routes, external image deployment, and existing endpoint client.

### Constructor

```python
Endpoint(
    name: Optional[str] = None,
    *,
    id: Optional[str] = None,
    gpu: Optional[Union[GpuGroup, GpuType, List[Union[GpuGroup, GpuType]]]] = None,
    cpu: Optional[Union[str, CpuInstanceType, List[Union[str, CpuInstanceType]]]] = None,
    workers: Union[int, Tuple[int, int], None] = None,
    idle_timeout: int = 60,
    dependencies: Optional[List[str]] = None,
    system_dependencies: Optional[List[str]] = None,
    accelerate_downloads: bool = True,
    volume: Optional[Union[NetworkVolume, List[NetworkVolume]]] = None,
    datacenter: Optional[Union[DataCenter, List[DataCenter], str, List[str]]] = None,
    env: Optional[Dict[str, str]] = None,
    gpu_count: int = 1,
    execution_timeout_ms: int = 0,
    flashboot: bool = True,
    image: Optional[str] = None,
    scaler_type: Optional[ServerlessScalerType] = None,
    scaler_value: int = 4,
    template: Optional[PodTemplate] = None,
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | `None` | Endpoint name. Required unless `id=` is used. |
| `id` | `str` | `None` | Existing endpoint ID. Mutually exclusive with `image`. |
| `gpu` | `GpuGroup`, `GpuType`, or list | `None` | GPU type(s). Mutually exclusive with `cpu`. Defaults to `GpuGroup.ANY` if neither is set. |
| `cpu` | `str`, `CpuInstanceType`, or list | `None` | CPU instance type(s). Mutually exclusive with `gpu`. |
| `workers` | `int` or `(int, int)` | `(0, 3)` | Worker scaling. `N` = `(0, N)`. `(min, max)` = explicit range. |
| `idle_timeout` | `int` | `60` | Seconds before idle workers scale down. |
| `dependencies` | `list[str]` | `None` | Python packages to install (e.g., `["torch", "numpy==1.24"]`). |
| `system_dependencies` | `list[str]` | `None` | System packages to install. |
| `accelerate_downloads` | `bool` | `True` | Enable accelerated downloads. |
| `volume` | `NetworkVolume` or list | `None` | Network volume(s) for persistent storage. One volume per datacenter. |
| `datacenter` | `DataCenter`, list, `str`, or `None` | `None` | Datacenter(s) to deploy into. `None` means all available DCs. Accepts a single value, a list, or string DC IDs. CPU endpoints must use DCs in `CPU_DATACENTERS`. |
| `env` | `dict[str, str]` | `None` | Environment variables for the endpoint. |
| `gpu_count` | `int` | `1` | GPUs per worker. |
| `execution_timeout_ms` | `int` | `0` | Max execution time in ms. 0 = no limit. |
| `flashboot` | `bool` | `True` | Enable Flashboot fast startup. |
| `image` | `str` | `None` | Custom Docker image to deploy. Mutually exclusive with `id`. |
| `scaler_type` | `ServerlessScalerType` | auto | Scaling strategy. Auto-selects `QUEUE_DELAY` for QB, `REQUEST_COUNT` for LB. |
| `scaler_value` | `int` | `4` | Scaling threshold value. |
| `template` | `PodTemplate` | `None` | Pod template overrides (e.g., `PodTemplate(containerDiskInGb=100)`). |

**Validation rules:**
- `gpu` and `cpu` are mutually exclusive
- `id` and `image` are mutually exclusive
- `name` or `id` is required
- `workers` rejects negative values and `min > max`

### Usage Patterns

#### Queue-Based (QB) -- decorator on function

```python
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="my-worker", gpu=GpuGroup.ADA_24, workers=(0, 3))
async def process(data: dict) -> dict:
    return {"result": data}

# call it
result = await process({"key": "value"})
```

#### Queue-Based (QB) -- decorator on class

```python
@Endpoint(name="model", gpu=GpuGroup.AMPERE_80, dependencies=["torch"])
class MyModel:
    def __init__(self):
        import torch
        self.model = torch.load("/models/model.pt")

    def predict(self, text: str) -> dict:
        return {"prediction": self.model(text)}

    def embed(self, text: str) -> dict:
        return {"embedding": [0.1, 0.2]}
```

The class is instantiated once per worker (singleton). For single-method classes, input is auto-dispatched to the method. For multi-method classes, include `"method"` in the input payload.

#### Load-Balanced (LB) -- instance with route decorators

```python
from runpod_flash import Endpoint

api = Endpoint(name="my-api", cpu="cpu3c-4-8", workers=(1, 5))

@api.post("/compute")
async def compute(data: dict) -> dict:
    return {"result": data}

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.put("/items/{item_id}")
async def update_item(item_id: int, data: dict):
    return {"updated": item_id}

@api.delete("/items/{item_id}")
async def delete_item(item_id: int):
    return {"deleted": item_id}

@api.patch("/items/{item_id}")
async def patch_item(item_id: int, data: dict):
    return {"patched": item_id}
```

**Route decorator rules:**
- Path must start with `/`
- Paths `/execute` and `/ping` are reserved
- Duplicate method+path combinations are rejected
- Available methods: `.get()`, `.post()`, `.put()`, `.delete()`, `.patch()`

#### External Image -- deploy and call a pre-built image

```python
from runpod_flash import Endpoint, GpuGroup

vllm = Endpoint(
    name="vllm-server",
    image="vllm/vllm-openai:latest",
    gpu=GpuGroup.AMPERE_80,
    workers=(1, 3),
)

# LB-style HTTP calls
result = await vllm.post("/v1/completions", {"prompt": "hello"})
models = await vllm.get("/v1/models")

# QB-style calls
job = await vllm.run({"prompt": "hello"})
await job.wait()
print(job.output)
```

#### Existing Endpoint -- connect by ID

```python
from runpod_flash import Endpoint

ep = Endpoint(id="abc123")

# QB calls
job = await ep.run({"prompt": "hello"})
result = await ep.runsync({"prompt": "hello"})

# LB calls
data = await ep.post("/v1/completions", {"prompt": "hello"})
info = await ep.get("/v1/models")
```

### Client Methods (id= and image= modes)

#### run(input_data, timeout=60.0)

Submit an async job to the endpoint. Returns an `EndpointJob`.

```python
job = await ep.run({"prompt": "hello"})
print(job.id)  # "job-abc123"
```

#### runsync(input_data, timeout=60.0)

Submit a synchronous job. Returns an `EndpointJob` with the result already populated.

```python
job = await ep.runsync({"prompt": "hello"})
print(job.output)  # {"text": "world"}
```

#### cancel(job_id)

Cancel a running job. Returns an `EndpointJob`.

```python
job = await ep.cancel("job-abc123")
print(job.status)  # "CANCELLED"
```

#### get(path, data=None, **kwargs)

Make an HTTP GET request to an LB endpoint. Returns raw response data.

```python
models = await ep.get("/v1/models")
```

#### post(path, data=None, **kwargs)

Make an HTTP POST request to an LB endpoint. Returns raw response data.

```python
result = await ep.post("/v1/completions", {"prompt": "hello"})
```

#### put(path, data=None, **kwargs) / delete(path, ...) / patch(path, ...)

HTTP PUT, DELETE, PATCH requests. Same interface as `post()`.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_cpu` | `bool` | Whether this is a CPU endpoint |
| `is_client` | `bool` | Whether this is a client-only endpoint (`id=` or `image=`) |
| `is_load_balanced` | `bool` | Whether this endpoint has LB routes registered |
| `workers_min` | `int` | Minimum worker count |
| `workers_max` | `int` | Maximum worker count |
| `scaler_type` | `ServerlessScalerType` | Effective scaler type (auto-selected or explicit) |

## EndpointJob

Represents a submitted job on a Runpod endpoint. Returned by `Endpoint.run()` and `Endpoint.runsync()`.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | `str` | Job ID assigned by Runpod |
| `output` | `Any` | Job output. Available after completion. |
| `error` | `Optional[str]` | Error message if job failed |
| `done` | `bool` | Whether job is in a terminal state |

### Methods

#### status()

Poll the job status. Updates internal data and returns the status string.

```python
s = await job.status()  # "IN_PROGRESS", "COMPLETED", "FAILED", etc.
```

#### cancel()

Cancel the job. Returns self for chaining.

```python
await job.cancel()
```

#### wait(timeout=None)

Wait for the job to complete, polling with exponential backoff. Returns self.

```python
await job.wait(timeout=120.0)
print(job.output)
```

Raises `TimeoutError` if the timeout is exceeded.

## Enums

### GpuGroup

Architecture-level GPU selection. Common values:

| Value | Description |
|-------|-------------|
| `GpuGroup.ANY` | Any available GPU (default) |
| `GpuGroup.ADA_24` | RTX 4090 (24GB) |
| `GpuGroup.ADA_32_PRO` | RTX 5090 (32GB) |
| `GpuGroup.ADA_48_PRO` | L40, L40S, RTX 6000 Ada (48GB) |
| `GpuGroup.ADA_80_PRO` | H100 PCIe (80GB) |
| `GpuGroup.AMPERE_16` | RTX A4000 (16GB) |
| `GpuGroup.AMPERE_24` | RTX 3090, L4, RTX A5000 (24GB) |
| `GpuGroup.AMPERE_48` | A40, RTX A6000 (48GB) |
| `GpuGroup.AMPERE_80` | A100 80GB |
| `GpuGroup.HOPPER_141` | H200 (141GB) |

### GpuType

Specific GPU model selection. Common values:

| Value | Model | VRAM |
|-------|-------|------|
| `GpuType.ANY` | Any | varies |
| `GpuType.NVIDIA_GEFORCE_RTX_4090` | RTX 4090 | 24GB |
| `GpuType.NVIDIA_GEFORCE_RTX_5090` | RTX 5090 | 32GB |
| `GpuType.NVIDIA_RTX_6000_ADA_GENERATION` | RTX 6000 Ada | 48GB |
| `GpuType.NVIDIA_L4` | L4 | 24GB |
| `GpuType.NVIDIA_A100_80GB_PCIe` | A100 PCIe | 80GB |
| `GpuType.NVIDIA_A100_SXM4_80GB` | A100 SXM4 | 80GB |
| `GpuType.NVIDIA_H100_80GB_HBM3` | H100 | 80GB |
| `GpuType.NVIDIA_H200` | H200 | 141GB |

### CpuInstanceType

CPU instance selection. Can also be passed as a string to `cpu=`.

| Value | String | Specs |
|-------|--------|-------|
| `CpuInstanceType.CPU3G_1_4` | `"cpu3g-1-4"` | 1 vCPU, 4GB RAM |
| `CpuInstanceType.CPU3G_2_8` | `"cpu3g-2-8"` | 2 vCPU, 8GB RAM |
| `CpuInstanceType.CPU3G_4_16` | `"cpu3g-4-16"` | 4 vCPU, 16GB RAM |
| `CpuInstanceType.CPU3G_8_32` | `"cpu3g-8-32"` | 8 vCPU, 32GB RAM |
| `CpuInstanceType.CPU3C_1_2` | `"cpu3c-1-2"` | 1 vCPU, 2GB RAM |
| `CpuInstanceType.CPU3C_2_4` | `"cpu3c-2-4"` | 2 vCPU, 4GB RAM |
| `CpuInstanceType.CPU3C_4_8` | `"cpu3c-4-8"` | 4 vCPU, 8GB RAM |
| `CpuInstanceType.CPU3C_8_16` | `"cpu3c-8-16"` | 8 vCPU, 16GB RAM |
| `CpuInstanceType.CPU5C_1_2` | `"cpu5c-1-2"` | 1 vCPU, 2GB RAM |
| `CpuInstanceType.CPU5C_2_4` | `"cpu5c-2-4"` | 2 vCPU, 4GB RAM |
| `CpuInstanceType.CPU5C_4_8` | `"cpu5c-4-8"` | 4 vCPU, 8GB RAM |
| `CpuInstanceType.CPU5C_8_16` | `"cpu5c-8-16"` | 8 vCPU, 16GB RAM |

### ServerlessScalerType

| Value | Description | Default For |
|-------|-------------|------------|
| `QUEUE_DELAY` | Scale based on queue wait time | QB endpoints |
| `REQUEST_COUNT` | Scale based on active request count | LB endpoints |

### DataCenter

| Value | Location |
|-------|----------|
| `DataCenter.US_CA_2` | US - California |
| `DataCenter.US_GA_2` | US - Georgia |
| `DataCenter.US_IL_1` | US - Illinois |
| `DataCenter.US_KS_2` | US - Kansas |
| `DataCenter.US_MD_1` | US - Maryland |
| `DataCenter.US_MO_1` | US - Missouri |
| `DataCenter.US_MO_2` | US - Missouri |
| `DataCenter.US_NC_1` | US - North Carolina |
| `DataCenter.US_NC_2` | US - North Carolina |
| `DataCenter.US_NE_1` | US - Nebraska |
| `DataCenter.US_WA_1` | US - Washington |
| `DataCenter.EU_CZ_1` | Europe - Czech Republic |
| `DataCenter.EU_RO_1` | Europe - Romania |
| `DataCenter.EUR_IS_1` | Europe - Iceland |
| `DataCenter.EUR_NO_1` | Europe - Norway |

When `datacenter=None` (the default), the endpoint is available in all data centers.

CPU endpoints are restricted to the `CPU_DATACENTERS` subset: `EU_RO_1`.

### CudaVersion

| Value | Version |
|-------|---------|
| `CudaVersion.V11_8` | CUDA 11.8 |
| `CudaVersion.V12_0` | CUDA 12.0 |
| `CudaVersion.V12_1` through `V12_8` | CUDA 12.1-12.8 |

## Models

### NetworkVolume

Persistent storage that survives worker restarts. Each volume is tied to a specific datacenter.

```python
from runpod_flash import NetworkVolume, DataCenter

# existing volume by ID
vol = NetworkVolume(id="vol_abc123")

# create a new volume in a specific datacenter
vol = NetworkVolume(name="my-models", size=100, datacenter=DataCenter.US_GA_1)

# multiple volumes across datacenters (one per DC)
volumes = [
    NetworkVolume(name="models-us", size=100, datacenter=DataCenter.US_GA_1),
    NetworkVolume(name="models-eu", size=100, datacenter=DataCenter.EU_RO_1),
]
```

### PodTemplate

Override pod-level configuration:

```python
from runpod_flash import PodTemplate

template = PodTemplate(
    containerDiskInGb=100,
    env=[{"key": "MY_VAR", "value": "my_value"}],
)
```

### FlashApp

Application-level model. Used internally by `flash app` commands.

### ResourceManager

Singleton that manages dynamic provisioning, persistence, and config drift detection. Used internally by the runtime.

## Imports

All public symbols are available from the top-level package:

```python
from runpod_flash import (
    Endpoint,
    EndpointJob,
    GpuGroup,
    GpuType,
    CpuInstanceType,
    CudaVersion,
    DataCenter,
    CPU_DATACENTERS,
    NetworkVolume,
    PodTemplate,
    ServerlessScalerType,
)
```

Legacy imports (deprecated, will be removed in a future release):

```python
from runpod_flash import (
    remote,
    LiveServerless,
    CpuLiveServerless,
    LiveLoadBalancer,
    CpuLiveLoadBalancer,
    ServerlessEndpoint,
    CpuServerlessEndpoint,
    LoadBalancerSlsResource,
    CpuLoadBalancerSlsResource,
)
```
