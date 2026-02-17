## Flash SDK Reference

This section documents the complete Flash SDK API. Reference this section when building applications.

### Overview

**runpod-flash** is the underlying SDK powering the Flash framework. It provides:
- The `@remote` decorator for marking functions as distributed workers
- Resource configuration classes for defining compute requirements
- GPU/CPU specifications and pricing models
- Queue-based (reliable, retry-enabled) and load-balanced (low-latency HTTP) execution models

**Import from `runpod_flash`, not `flash`.** The Flash CLI wraps runpod-flash functionality.

### Main Exports

Core imports for Flash Examples:

```python
# Main decorator
from runpod_flash import remote

# Resource configuration classes (queue-based)
from runpod_flash import LiveServerless, CpuLiveServerless  # Development
from runpod_flash import ServerlessEndpoint, CpuServerlessEndpoint  # Production

# Resource configuration classes (load-balanced, HTTP)
from runpod_flash import LiveLoadBalancer, CpuLiveLoadBalancer  # Development
from runpod_flash import LoadBalancerSlsResource, CpuLoadBalancerSlsResource  # Production

# GPU and CPU specifications
from runpod_flash import GpuGroup, CpuInstanceType

# Advanced features
from runpod_flash import NetworkVolume, PodTemplate, CudaVersion, DataCenter
```

### The @remote Decorator

The `@remote` decorator marks a function for distributed execution. It's the core of runpod-flash.

#### Complete Signature

```python
def remote(
    resource_config: Union[
        LiveServerless,
        CpuLiveServerless,
        ServerlessEndpoint,
        CpuServerlessEndpoint,
        LiveLoadBalancer,
        CpuLiveLoadBalancer,
        LoadBalancerSlsResource,
        CpuLoadBalancerSlsResource,
    ],
    dependencies: Optional[list[str]] = None,
    system_dependencies: Optional[list[str]] = None,
    accelerate_downloads: bool = False,
    env: Optional[dict[str, str]] = None,
    max_retries: int = 1,
    timeout: int = 3600,
) -> Callable:
    """Mark function for remote execution on Runpod infrastructure."""
    pass
```

#### Key Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `resource_config` | Resource class | Required | Defines GPU/CPU, scaling, pricing model (queue vs load-balanced) |
| `dependencies` | `list[str]` | `None` | Python packages to install (pip dependencies) |
| `system_dependencies` | `list[str]` | `None` | System packages to install (apt-get on Linux) |
| `accelerate_downloads` | `bool` | `False` | Enable CDN acceleration for dependency downloads |
| `env` | `dict[str, str]` | `None` | Environment variables to set in worker container |
| `max_retries` | `int` | `1` | Number of retries on failure (queue-based only) |
| `timeout` | `int` | `3600` | Function timeout in seconds (1 hour default) |

#### Return Behavior

The decorated function becomes **always awaitable**:

```python
@remote(resource_config=config)
async def my_function(data: dict) -> dict:
    return {"result": "success"}

# Must be awaited, always
result = await my_function({"input": "value"})
```

Even if you don't use `async` in the decorator, the returned value must be awaited when calling it.

### Resource Configuration Quick Reference

Choose a resource class based on your needs:

| Use Case | Class | Queue | HTTP | Environment | Pricing |
|----------|-------|-------|------|-------------|---------|
| GPU inference with retries | `LiveServerless` | ✓ | ✗ | Development | Spot pricing |
| CPU processing with retries | `CpuLiveServerless` | ✓ | ✗ | Development | Spot pricing |
| GPU production (reliable) | `ServerlessEndpoint` | ✓ | ✗ | Production | On-demand pricing |
| CPU production (reliable) | `CpuServerlessEndpoint` | ✓ | ✗ | Production | On-demand pricing |
| GPU low-latency HTTP | `LiveLoadBalancer` | ✗ | ✓ | Development | Spot pricing |
| CPU low-latency HTTP | `CpuLiveLoadBalancer` | ✗ | ✓ | Development | Spot pricing |
| GPU production HTTP | `LoadBalancerSlsResource` | ✗ | ✓ | Production | On-demand pricing |
| CPU production HTTP | `CpuLoadBalancerSlsResource` | ✗ | ✓ | Production | On-demand pricing |

**Queue-based vs Load-Balanced:**
- **Queue-based**: Best for batch processing, long-running tasks, or when you need retries. Returns `JobOutput` with status tracking.
- **Load-balanced**: Best for real-time inference, API endpoints, low-latency requirements. Returns HTTP response directly.

### Resource Configuration Classes

All resource classes share common parameters. Differences are noted.

#### Common Parameters for All Resource Classes

```python
class ResourceConfig:
    # Required
    name: str                           # Unique name: format "{category}_{example}_{worker_type}"

    # Worker scaling
    workersMin: int = 0                 # Minimum workers to maintain
    workersMax: int = 3                 # Maximum workers allowed
    idleTimeout: int = 60               # Seconds before idle worker terminates

    # Networking
    networkVolumeId: Optional[str] = None  # Mount persistent storage

    # GPU (GPU classes only)
    gpus: list[GpuGroup] = [GpuGroup.ANY]  # GPU requirements

    # CPU (CPU classes only)
    cpuCount: int = 1                   # vCPU count (for CPU instances)

    # Custom configuration
    env: Optional[dict[str, str]] = None       # Environment variables
    podTemplate: Optional[PodTemplate] = None  # Advanced: custom pod config
```

#### Queue-Based (Reliable)

**LiveServerless - Development GPU**
```python
from runpod_flash import remote, LiveServerless, GpuGroup

gpu_config = LiveServerless(
    name="02_ml_inference_gpu_worker",
    gpus=[GpuGroup.AMPERE_24],      # RTX A5000, 24GB
    workersMin=0,
    workersMax=3,
    idleTimeout=600,
)

@remote(
    resource_config=gpu_config,
    dependencies=["torch>=2.0.0", "transformers>=4.30.0"],
    timeout=1800,
)
async def inference(data: dict) -> dict:
    import torch
    # Long-running inference job
    return {"result": "output"}

# Returns JobOutput with status, output, error fields
job_output = await inference({"prompt": "hello"})
if job_output.error:
    print(f"Job failed: {job_output.error}")
else:
    print(f"Result: {job_output.output}")
```

**CpuLiveServerless - Development CPU**
```python
from runpod_flash import remote, CpuLiveServerless

cpu_config = CpuLiveServerless(
    name="01_getting_started_cpu_worker",
    cpuCount=2,                 # 2 vCPU
    workersMin=0,
    workersMax=5,
)

@remote(resource_config=cpu_config)
async def process_data(items: list) -> dict:
    # Define helper inside function (required for cloudpickle)
    def process_item(item):
        # Your processing logic here
        return str(item).upper()

    # CPU-bound processing
    results = [process_item(item) for item in items]
    return {"processed": len(results)}
```

**ServerlessEndpoint - Production GPU**
```python
from runpod_flash import remote, ServerlessEndpoint, GpuGroup

prod_config = ServerlessEndpoint(
    name="02_ml_inference_gpu_prod",
    gpus=[GpuGroup.AMPERE_80],  # A100 80GB for production
    workersMin=1,               # Always keep 1 warm
    workersMax=10,              # Scale to 10 under load
    idleTimeout=300,
)

@remote(resource_config=prod_config)
async def production_inference(data: dict) -> dict:
    return {"status": "success"}
```

#### Load-Balanced (Low-Latency HTTP)

**LiveLoadBalancer - Development GPU**
```python
from runpod_flash import remote, LiveLoadBalancer, GpuGroup

lb_config = LiveLoadBalancer(
    name="03_load_balanced_gpu",
    gpus=[GpuGroup.ADA_24],     # RTX 4090, 24GB
    workersMin=1,
    workersMax=5,
    idleTimeout=30,             # Short timeout for fast-scaling
)

@remote(resource_config=lb_config)
async def real_time_inference(data: dict) -> dict:
    # Return dict directly (no JobOutput wrapper)
    return {"prediction": 0.95}
```

**LoadBalancerSlsResource - Production GPU**
```python
from runpod_flash import remote, LoadBalancerSlsResource, GpuGroup

prod_lb_config = LoadBalancerSlsResource(
    name="03_load_balanced_prod",
    gpus=[GpuGroup.HOPPER_141],  # H200 141GB for production
    workersMin=2,                # Always 2 warm
    workersMax=20,               # Scale aggressively
)

@remote(resource_config=prod_lb_config)
async def production_realtime(data: dict) -> dict:
    return {"status": "processed"}
```

### GPU Groups and Specifications

Complete `GpuGroup` enum with VRAM specifications:

```python
from runpod_flash import GpuGroup

# Ampere GPUs (Previous generation, lower cost)
GpuGroup.AMPERE_16    # RTX A4000, 16GB VRAM
GpuGroup.AMPERE_24    # RTX A5000, 24GB VRAM
GpuGroup.AMPERE_48    # A40 or RTX A6000, 48GB VRAM
GpuGroup.AMPERE_80    # A100, 80GB VRAM

# Ada GPUs (Current consumer, mid-range)
GpuGroup.ADA_24       # RTX 4090, 24GB VRAM
GpuGroup.ADA_32_PRO   # RTX 5090, 32GB VRAM
GpuGroup.ADA_48_PRO   # RTX 6000 Ada, 48GB VRAM
GpuGroup.ADA_80_PRO   # H100, 80GB VRAM

# Hopper GPUs (Latest, enterprise)
GpuGroup.HOPPER_141   # H200, 141GB VRAM

# Flexible (pick at runtime)
GpuGroup.ANY          # Any available GPU (not recommended for production)
```

**Multiple GPU Selection:**

```python
from runpod_flash import GpuGroup

config = LiveServerless(
    name="multi_gpu_example",
    gpus=[GpuGroup.AMPERE_80, GpuGroup.AMPERE_80],  # 2x A100 80GB
)
```

### CPU Instance Types

CPU configurations using `CpuInstanceType` enum:

```python
from runpod_flash import CpuInstanceType

# CPU instances (vCPU count)
CpuInstanceType.CPU_2      # 2 vCPU, ~2GB RAM
CpuInstanceType.CPU_4      # 4 vCPU, ~4GB RAM
CpuInstanceType.CPU_8      # 8 vCPU, ~8GB RAM
CpuInstanceType.CPU_16     # 16 vCPU, ~16GB RAM
CpuInstanceType.CPU_32     # 32 vCPU, ~32GB RAM
```

**Usage:**

```python
from runpod_flash import CpuLiveServerless, CpuInstanceType

config = CpuLiveServerless(
    name="cpu_processing",
    cpuCount=8,  # Or use CpuInstanceType if needed
)
```

### Function Requirements

Restrictions on functions decorated with `@remote`:

#### Cloudpickle Scoping Rules (CRITICAL)

Functions decorated with `@remote` are serialized using cloudpickle and executed remotely. They can ONLY access:

1. **Function parameters** passed at call time
2. **Local variables** defined inside the function
3. **Imports** done inside the function
4. **Built-in Python functions** (print, len, etc.)

They CANNOT access:
- Module-level imports
- Global variables
- Functions/classes defined outside the function
- Module-level constants

**❌ WRONG - External references:**
```python
import torch  # Module-level import

model_config = {"hidden_size": 768}  # External variable

def load_model():  # External function
    return torch.load("model.pt")

@remote(resource_config=config)
async def inference(prompt: str) -> dict:
    # NONE of these are accessible:
    model = load_model()  # ❌ Function not accessible
    config = model_config  # ❌ Variable not accessible
    device = torch.device("cuda")  # ❌ torch not accessible
    return {"result": "..."}
```

**✅ CORRECT - Everything inside function:**
```python
@remote(resource_config=config)
async def inference(prompt: str) -> dict:
    import torch  # ✅ Import inside

    # ✅ Define configuration inside
    model_config = {"hidden_size": 768}

    # ✅ Define helper inside
    def load_model():
        return torch.load("model.pt")

    model = load_model()
    device = torch.device("cuda")
    model.to(device)

    return {"result": model.generate(prompt)}
```

**Exception**: Decorator parameters like `resource_config` are evaluated at decoration time (when the function is defined), so they can reference external variables:
```python
# This is fine - decorator parameters evaluated at decoration time
config = LiveServerless(name="worker", gpus=[GpuGroup.ANY])

@remote(resource_config=config)  # ✅ OK - decorator parameter
async def my_function(data: dict) -> dict:
    # But inside here, only local scope works
    return {"status": "ok"}
```

#### Must Be Async

```python
# ✅ GOOD
@remote(resource_config=config)
async def my_function(data: dict) -> dict:
    result = await some_async_operation(data)
    return result

# ❌ BAD - Synchronous function
@remote(resource_config=config)
def my_function(data: dict) -> dict:  # No async!
    return data
```

#### Arguments Must Be Serializable

runpod-flash uses **cloudpickle** to serialize function arguments. Standard types work:

```python
# ✅ Serializable types
- dict, list, tuple, set
- str, int, float, bool, None
- numpy arrays (numpy installed)
- dataclasses with serializable fields
- Pydantic models
- Custom classes with __reduce__ or __getstate__

# ❌ Non-serializable types
- File objects (open files)
- Database connections
- Thread/Process objects
- Lambdas (sometimes, context-dependent)
- Objects with local references

# Handling non-serializable data
@remote(resource_config=config)
async def process(url: str) -> dict:  # Pass URL, not file object
    with open(url) as f:  # Open inside the function
        return process_file(f)
```

#### Import Patterns

Imports inside functions are recommended for large dependencies:

```python
@remote(
    resource_config=config,
    dependencies=["torch", "transformers"],
)
async def inference(prompt: str) -> dict:
    # ✅ GOOD - Import inside function for large packages
    import torch
    from transformers import pipeline

    nlp = pipeline("text-generation")
    result = nlp(prompt)
    return {"output": result}

# vs.

# ❌ NOT RECOMMENDED at module level (delays cold start)
import torch
from transformers import pipeline

@remote(resource_config=config)
async def inference(prompt: str) -> dict:
    nlp = pipeline("text-generation")
    return {"output": nlp(prompt)}
```

#### Return Types

Return must be JSON-serializable:

```python
# ✅ GOOD
@remote(resource_config=config)
async def my_function(data: dict) -> dict:
    result = perform_computation(data)
    return {
        "status": "success",
        "result": result,
        "timestamp": datetime.now().isoformat(),  # ISO format strings
        "values": [1, 2, 3],
    }

# ❌ BAD - Non-serializable return
@remote(resource_config=config)
async def my_function(data: dict):
    result = perform_computation(data)
    return datetime.now()  # datetime object, not serializable
```

### Dependency Management

#### Python Dependencies (pip)

```python
@remote(
    resource_config=config,
    dependencies=[
        "torch>=2.0.0,<3.0",      # Pin major.minor
        "transformers==4.30.2",   # Pin exact for reproducibility
        "numpy",                  # Or allow any version if stable
    ],
)
async def my_function(data: dict) -> dict:
    import torch  # Available in worker
    return {"status": "ok"}
```

**Guidelines:**
- List all dependencies used in the function
- Use exact versions for reproducibility
- Avoid installing during function execution
- Test dependencies locally first

#### System Dependencies (apt-get)

```python
@remote(
    resource_config=config,
    system_dependencies=[
        "build-essential",        # GCC, make, etc.
        "libffi-dev",            # For certain Python packages
        "ffmpeg",                # For audio/video processing
    ],
)
async def process_video(video_url: str) -> dict:
    # ffmpeg available in PATH
    import subprocess
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
    return {"ffmpeg": "available"}
```

#### Accelerate Downloads

For examples with large dependencies, enable CDN acceleration:

```python
@remote(
    resource_config=config,
    dependencies=["torch", "transformers", "diffusers"],
    accelerate_downloads=True,  # Enable CDN for faster downloads
)
async def inference(prompt: str) -> dict:
    # Dependencies download faster via CDN
    return {"status": "ok"}
```

### Error Handling and Return Values

Return type depends on resource model (queue vs load-balanced).

#### Queue-Based Resources

Queue resources wrap output in `JobOutput`:

```python
class JobOutput:
    id: str                    # Unique job ID
    status: str                # "COMPLETED", "FAILED", etc.
    output: Optional[Any]      # Your return value (if successful)
    error: Optional[str]       # Error message (if failed)
    started_at: int           # Unix timestamp
    ended_at: int             # Unix timestamp
```

**Usage:**

```python
from runpod_flash import remote, LiveServerless

config = LiveServerless(name="my_job", gpus=[GpuGroup.ANY])

@remote(resource_config=config)
async def my_job(data: dict) -> dict:
    if data.get("invalid"):
        raise ValueError("Invalid input")
    return {"result": "success"}

# Calling queue-based function returns JobOutput
job_output = await my_job({"invalid": False})

# Always check for errors
if job_output.error:
    print(f"Job {job_output.id} failed: {job_output.error}")
    # Handle error
else:
    print(f"Job {job_output.id} result: {job_output.output}")
    # Use job_output.output
```

#### Load-Balanced Resources

Load-balanced resources return your value directly as HTTP response:

```python
from runpod_flash import remote, LiveLoadBalancer, GpuGroup

lb_config = LiveLoadBalancer(name="api", gpus=[GpuGroup.ANY])

@remote(resource_config=lb_config)
async def inference(data: dict) -> dict:
    if data.get("invalid"):
        raise ValueError("Invalid input")
    return {"result": "success"}

# Calling load-balanced function returns your dict directly
result = await inference({"invalid": False})
# result is directly {"result": "success"}

# Errors raise exceptions
try:
    result = await inference({"invalid": True})
except Exception as e:
    print(f"Error: {e}")
```

#### Exception Handling in Remote Functions

```python
@remote(resource_config=config)
async def robust_function(data: dict) -> dict:
    async def external_api_call(data):
        # Your API call logic here (defined inside function)
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.example.com", json=data)
            return response.json()

    try:
        # Attempt operation
        result = await external_api_call(data)
        return {"status": "success", "data": result}
    except ValueError as e:
        # Return structured error for queue-based
        # (will appear in job_output.error)
        raise ValueError(f"Invalid input: {e}") from e
    except Exception as e:
        # Log for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise RuntimeError(f"Processing failed: {e}") from e
```

### Data Serialization Details

#### How Serialization Works

1. Function arguments are pickled with **cloudpickle**
2. Pickled bytes are transmitted to worker
3. Worker unpickles and executes function
4. Return value is pickled and sent back
5. Result is unpickled on client side

**Performance implications:**
- Large arguments/returns → slow (network transfer)
- Complex objects → slow (pickle overhead)
- Solution: Pass data identifiers (URLs, S3 paths) instead of full data

```python
# ❌ BAD - Serializing large data
@remote(resource_config=config)
async def process_image(image_array: np.ndarray) -> dict:
    import numpy as np

    # Entire array serialized, sent over network (slow!)
    # Your object detection logic here
    result = your_detection_model(image_array)
    return {"objects": result}

# ✅ GOOD - Pass reference
@remote(resource_config=config)
async def process_image(image_url: str) -> dict:
    # Only URL serialized, downloaded in worker
    import requests
    import numpy as np

    response = requests.get(image_url)
    image_array = np.frombuffer(response.content, dtype=np.uint8)

    # Your object detection logic here
    # Load model inside function and run inference
    import torch
    model = torch.load("detector.pt")
    result = model.predict(image_array)

    return {"objects": result}
```

#### Cloudpickle Caching

Arguments are hashed and cached by runpod-flash. Identical arguments in rapid succession reuse cached versions.

```python
# First call - argument cached
result1 = await my_function({"large": "data"})

# Rapid second call with same argument - uses cache
result2 = await my_function({"large": "data"})

# Different argument - new cache entry
result3 = await my_function({"large": "different"})
```

### Advanced Features

#### Local Testing Mode

Test functions locally without sending to cloud:

```python
@remote(resource_config=config, local=True)
async def my_function(data: dict) -> dict:
    # Executes locally, ignores resource_config
    return {"status": "success"}

# Runs on local machine, not on Runpod
result = await my_function({"input": "value"})
```

**Use cases:**
- Development and debugging
- CI/CD testing
- Rapid iteration

#### Network Volumes

Mount persistent storage for large models or datasets:

```python
from runpod_flash import remote, LiveServerless, NetworkVolume

volume = NetworkVolume(
    name="model_storage",
    mount_path="/models",  # Available at /models in worker
)

config = LiveServerless(
    name="ml_inference",
    gpus=[GpuGroup.AMPERE_80],
    networkVolumeId=volume.id,  # Mount the volume
)

@remote(resource_config=config)
async def inference(prompt: str) -> dict:
    import torch

    # Model already at /models, no download needed
    model = torch.load("/models/model.bin")
    model.eval()

    output = model.generate(prompt)
    return {"output": output}
```

#### Pod Templates

Advanced: Custom pod configuration for specialized requirements:

```python
from runpod_flash import PodTemplate

pod_template = PodTemplate(
    # Custom resource limits
    memory_gb=40,
    cpu_count=8,
    # Custom networking
    expose_ports=["8080", "8081"],
)

config = LiveServerless(
    name="custom_pod",
    gpus=[GpuGroup.ANY],
    podTemplate=pod_template,
)
```

#### Environment Variables

Pass configuration via environment:

```python
@remote(
    resource_config=config,
    env={
        "MODEL_SIZE": "large",
        "LOG_LEVEL": "DEBUG",
        "API_KEY": None,  # Will use local environment
    },
)
async def configurable_function(data: dict) -> dict:
    import os
    model_size = os.getenv("MODEL_SIZE", "small")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    return {"size": model_size, "log": log_level}
```

#### Class-Based Workers

Execute methods on remote classes:

```python
from runpod_flash import remote, LiveServerless

@remote(resource_config=config)
async def run_model(data: dict) -> dict:
    # Define class inside function (required for cloudpickle)
    class MyModel:
        def __init__(self):
            import torch
            self.model = torch.load("pretrained_model.pt")

        async def predict(self, data):
            return self.model(data)

    model = MyModel()
    prediction = await model.predict(data)
    return {"prediction": prediction}
```

### Common Patterns

#### Type Validation with Pydantic

```python
from pydantic import BaseModel, validator

class InferenceRequest(BaseModel):
    image_url: str
    threshold: float = 0.5

    @validator("threshold")
    def validate_threshold(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("threshold must be between 0 and 1")
        return v

@remote(resource_config=config)
async def inference(request: InferenceRequest) -> dict:
    import httpx

    async def download_image(url):
        # Download image inside function
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            return response.content

    # Type-safe access
    image = await download_image(request.image_url)

    # Your detection logic here
    import torch
    model = torch.load("detector.pt")
    result = model.predict(image, threshold=request.threshold)

    return {"result": result}
```

#### Retry Logic with Exponential Backoff

```python
import asyncio
from runpod_flash import remote, LiveServerless, LiveLoadBalancer

config = LiveServerless(name="retry_example", gpus=[GpuGroup.ANY])

@remote(resource_config=config, max_retries=3)
async def unreliable_operation(data: dict) -> dict:
    # runpod-flash handles retries automatically for queue-based
    async def flaky_external_api(data):
        # Your API call logic here
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.example.com", json=data)
            return response.json()

    result = await flaky_external_api(data)
    return {"result": result}

# Manual retry for load-balanced
lb_config = LiveLoadBalancer(name="lb_example", gpus=[GpuGroup.ANY])

@remote(resource_config=lb_config)
async def with_manual_retry(data: dict) -> dict:
    async def external_api(data):
        # Your API call logic here
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.example.com", json=data)
            return response.json()

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            return await external_api(data)
        except Exception as e:
            if attempt < max_attempts - 1:
                await asyncio.sleep(2**attempt)  # Exponential backoff
                continue
            raise RuntimeError(f"Failed after {max_attempts} attempts") from e
```

#### Conditional Execution

```python
@remote(resource_config=config)
async def smart_processing(data: dict) -> dict:
    # Skip expensive operation if not needed
    if not data.get("require_processing"):
        return {"status": "skipped"}

    async def heavy_computation(data):
        # Your expensive computation here
        import asyncio
        await asyncio.sleep(10)  # Simulate expensive work
        return {"computation": "done"}

    # Expensive operation
    result = await heavy_computation(data)
    return {"status": "processed", "result": result}
```

#### Streaming/Async Iteration

```python
import asyncio

@remote(resource_config=config)
async def batch_process(items: list) -> dict:
    results = []

    async def process_item(item):
        # Your item processing logic here
        # For example, simulate async processing
        await asyncio.sleep(0.1)
        return f"processed_{item}"

    # Process items asynchronously
    async def run_batch():
        tasks = [process_item(item) for item in items]
        return await asyncio.gather(*tasks)

    # Run concurrently
    results = await run_batch()

    return {"processed": len(results), "results": results}
```

### SDK Best Practices

#### When to Use Queue-Based vs Load-Balanced

**Use Queue-Based (LiveServerless, ServerlessEndpoint) when:**
- Processing takes > 30 seconds
- You need automatic retries
- Job status tracking is important
- Batch processing is acceptable
- Building batch inference APIs

**Use Load-Balanced (LiveLoadBalancer, LoadBalancerSlsResource) when:**
- Response must be < 30 seconds
- Real-time performance required
- Building REST APIs
- Need HTTP semantics (methods, headers)
- High request throughput needed

#### Cost Optimization

```python
# ❌ EXPENSIVE - Always-on, large GPU
config = ServerlessEndpoint(
    name="expensive",
    gpus=[GpuGroup.HOPPER_141],  # $40/hour
    workersMin=1,
)

# ✅ BETTER - Scale from zero
config = LiveServerless(
    name="cost_optimized",
    gpus=[GpuGroup.AMPERE_24],   # $0.25/hour spot
    workersMin=0,                # Scale from zero
    workersMax=3,
    idleTimeout=300,
)

# ✅ BEST - Right-sized GPU
config = LiveServerless(
    name="right_sized",
    gpus=[GpuGroup.AMPERE_24],   # Sufficient for your use case
    workersMin=0,
    idleTimeout=600,             # Longer timeout = less churn
)
```

**Tactics:**
- Use smaller GPUs if they fit your model
- Scale workersMin to 0 when possible
- Set appropriate idleTimeout (balance cost vs startup latency)
- Use spot pricing for dev (LiveServerless)
- Use load-balanced for continuous APIs
- Monitor actual GPU utilization

#### Performance Considerations

```python
# ❌ SLOW - Large serialization
@remote(resource_config=config)
async def process_dataset(data: list[dict]) -> dict:
    # Entire list serialized (could be MB)
    return process_data(data)

# ✅ FAST - Stream data
@remote(resource_config=config)
async def process_dataset(s3_path: str) -> dict:
    # Only S3 path serialized (string)
    import boto3
    s3 = boto3.client("s3")
    # Stream from S3, not network
    return process_from_s3(s3, s3_path)

# ✅ FAST - Batch operations
@remote(resource_config=config)
async def batch_inference(urls: list[str]) -> dict:
    import torch

    async def download_image(url):
        # Your image download logic here
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            return response.content

    # Load model inside function
    model = torch.load("model.pt")
    model.eval()

    # Process all in one call (less overhead)
    results = []
    for url in urls:
        image_data = await download_image(url)
        result = model.predict(image_data)
        results.append(result)
    return {"results": results}
```

#### Testing Strategy

```python
import os

# Test locally during development
LOCAL_TEST = os.getenv("LOCAL_TEST", "False") == "True"

config = LiveServerless(name="my_worker", gpus=[GpuGroup.ANY])

@remote(resource_config=config, local=LOCAL_TEST)
async def my_function(data: dict) -> dict:
    return {"status": "ok"}

# Run tests:
# LOCAL_TEST=True pytest tests/  # Local execution
# pytest tests/                  # Remote execution
```

#### Monitoring and Debugging

```python
import logging

logger = logging.getLogger(__name__)

@remote(resource_config=config)
async def observable_function(data: dict) -> dict:
    logger.info("Started processing", extra={"data_id": data.get("id")})

    try:
        result = await process(data)
        logger.info("Processing succeeded", extra={"result_size": len(str(result))})
        return result
    except Exception as e:
        logger.error(
            "Processing failed",
            exc_info=True,
            extra={"error_type": type(e).__name__}
        )
        raise

# View logs: flash logs {job_id}
```

### Common Gotchas

1. **Accessing external scope (MOST COMMON ERROR)**: Only local variables accessible
   ```python
   # ❌ Wrong - external imports and functions
   import torch

   model_config = {"size": "large"}

   @remote(resource_config=config)
   async def inference(data: dict) -> dict:
       model = load_model()  # ❌ Not accessible
       config = model_config  # ❌ Not accessible
       device = torch.device("cuda")  # ❌ torch not accessible

   # ✅ Correct - everything inside
   @remote(resource_config=config)
   async def inference(data: dict) -> dict:
       import torch  # Import inside function

       model_config = {"size": "large"}

       def load_model():
           return torch.load("model.pt")

       model = load_model()
       device = torch.device("cuda")
   ```

2. **Forgetting `await`**: All remote functions must be awaited
   ```python
   # ❌ Forgot await
   result = my_remote_function(data)  # Wrong!

   # ✅ Correct
   result = await my_remote_function(data)
   ```

3. **Modifying mutable defaults**: Avoid mutable default arguments
   ```python
   # ❌ Wrong
   @remote(resource_config=config)
   async def process(items: list = []):
       items.append("new")  # Shared state!
       return items

   # ✅ Correct
   @remote(resource_config=config)
   async def process(items: list = None):
       if items is None:
           items = []
       items.append("new")
       return items
   ```

4. **Assuming import availability**: Dependencies must be declared
   ```python
   # ❌ Won't work (numpy not declared)
   @remote(resource_config=config)
   async def my_function(data: dict) -> dict:
       import numpy as np  # NameError in worker!

   # ✅ Correct
   @remote(resource_config=config, dependencies=["numpy"])
   async def my_function(data: dict) -> dict:
       import numpy as np  # Available
   ```

5. **Queue vs Load-Balanced confusion**: Different error models
   ```python
   # Queue-based: check job_output.error
   config = LiveServerless(name="queue", gpus=[GpuGroup.ANY])
   @remote(resource_config=config)
   async def queue_job(data: dict) -> dict:
       return {"result": "ok"}

   job = await queue_job({"input": "value"})
   if job.error:  # Check error field!
       print(f"Failed: {job.error}")

   # Load-balanced: exceptions raised directly
   lb_config = LiveLoadBalancer(name="lb", gpus=[GpuGroup.ANY])
   @remote(resource_config=lb_config)
   async def lb_job(data: dict) -> dict:
       if not data.get("valid"):
           raise ValueError("Invalid input")
       return {"result": "ok"}

   try:
       result = await lb_job({"input": "value"})
   except ValueError as e:
       print(f"Failed: {e}")
   ```

6. **Network volume delays**: First access incurs latency
   ```python
   # First read: ~5-10 seconds (mount and download)
   # Subsequent reads: Fast (cached)
   # Account for this in your timeout settings

   config = LiveServerless(
       name="with_volume",
       networkVolumeId="...",
       # Increase timeout for first-time volume access
   )
   ```
