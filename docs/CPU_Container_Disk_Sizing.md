# CPU Container Disk Sizing

## Overview

CPU endpoints in Flash have specific container disk sizing behavior that differs from GPU endpoints. This document covers how disk sizing is resolved for CPU endpoints and how the `PodTemplate` override mechanism works.

## How CPU Endpoints Work

When you create a CPU endpoint with `Endpoint(cpu=...)`, Flash internally selects the appropriate CPU resource class. CPU endpoints use a different base Docker image (`python:*-slim`) than GPU endpoints (`pytorch/pytorch:*`), and have a default container disk size of **20GB** (compared to 10GB for GPU endpoints).

```python
from runpod_flash import Endpoint

# cpu endpoint with default 20GB disk
@Endpoint(name="data-worker", cpu="cpu3c-4-8")
async def process(data: dict) -> dict:
    return {"result": data}

# cpu endpoint with custom disk size via template
from runpod_flash import PodTemplate

@Endpoint(
    name="large-data-worker",
    cpu="cpu3c-4-8",
    template=PodTemplate(containerDiskInGb=50),
)
async def process_large(data: dict) -> dict:
    return {"result": data}
```

## Disk Sizing Resolution

When Flash provisions a CPU endpoint, the container disk size is resolved in this order:

1. **Explicit `template=PodTemplate(containerDiskInGb=N)`** -- if you specify a `PodTemplate` with a disk size, that value takes precedence.
2. **Default for CPU** -- if no template is provided, CPU endpoints default to **20GB**.
3. **Default for GPU** -- GPU endpoints default to **10GB**.

```python
from runpod_flash import Endpoint, PodTemplate, GpuGroup

# 20GB default (CPU)
@Endpoint(name="cpu-default", cpu="cpu3c-1-2")
async def cpu_worker(data): ...

# 10GB default (GPU)
@Endpoint(name="gpu-default", gpu=GpuGroup.ANY)
async def gpu_worker(data): ...

# 100GB explicit override
@Endpoint(
    name="gpu-large-disk",
    gpu=GpuGroup.AMPERE_80,
    template=PodTemplate(containerDiskInGb=100),
)
async def gpu_large(data): ...
```

## Internal Architecture

When `Endpoint._build_resource_config()` runs, it selects the appropriate internal resource class:

| Endpoint Config | Internal Class | Default Disk |
|----------------|---------------|-------------|
| `gpu=...` (no routes) | `LiveServerless` | 10GB |
| `cpu=...` (no routes) | `CpuLiveServerless` | 20GB |
| `gpu=...` (with routes) | `LiveLoadBalancer` | 10GB |
| `cpu=...` (with routes) | `CpuLiveLoadBalancer` | 20GB |
| `image=..., gpu=...` | `ServerlessEndpoint` | 10GB |
| `image=..., cpu=...` | `CpuServerlessEndpoint` | 20GB |

The CPU mixin (`CpuEndpointMixin`) sets `containerDiskInGb=20` in its defaults, which are then merged with any user-provided `PodTemplate` overrides. The `PodTemplate` override mechanism uses a field-level merge: explicit fields in the user's template override the defaults, while unset fields inherit from the resource class defaults.

## When to Increase Disk Size

Common scenarios requiring larger container disks:

- **Large model weights**: Models like Llama 2 or Stable Diffusion XL can require 20-50GB+ of disk space
- **Dataset caching**: If your function downloads and caches datasets
- **Build artifacts**: Compilation output from packages like torch, scipy, etc.
- **Log files**: Long-running endpoints may accumulate logs

```python
from runpod_flash import Endpoint, PodTemplate

# large model serving
@Endpoint(
    name="llm-server",
    cpu="cpu3g-8-32",
    template=PodTemplate(containerDiskInGb=100),
    dependencies=["transformers", "torch"],
)
async def serve_llm(data: dict) -> dict:
    ...
```

## Related Documentation

- [Flash SDK Reference](Flash_SDK_Reference.md) -- complete API reference
- [GPU Provisioning](GPU_Provisioning.md) -- GPU provisioning architecture
- [Resource Config Drift Detection](Resource_Config_Drift_Detection.md) -- how disk size changes trigger drift
