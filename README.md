# Flash: Serverless computing for AI workloads

Runpod Flash is a Python SDK that streamlines the development and deployment of AI workflows on Runpod's [Serverless infrastructure](http://docs.runpod.io/serverless/overview). Write Python functions locally, and Flash handles the infrastructure, provisioning GPUs and CPUs, managing dependencies, and transferring data, allowing you to focus on building AI applications.

You can find a repository of prebuilt Flash examples at [runpod/flash-examples](https://github.com/runpod/flash-examples).

> [!Note]
> **New feature - Consolidated template management:** `PodTemplate` overrides now seamlessly integrate with `ServerlessResource` defaults, providing more consistent resource configuration and reducing deployment complexity.

## Table of contents

- [Overview](#overview)
- [Get started](#get-started)
- [Create Flash API endpoints](#create-flash-api-endpoints)
- [CLI Reference](#cli-reference)
- [Key concepts](#key-concepts)
- [How it works](#how-it-works)
- [Advanced features](#advanced-features)
- [Configuration](#configuration)
- [Workflow examples](#workflow-examples)
- [Use cases](#use-cases)
- [Limitations](#limitations)
- [Contributing](#contributing)
- [Troubleshooting](#troubleshooting)

## Overview

There are two basic modes for using Flash. You can:

- Build and run standalone Python scripts using the `@remote` decorator.
- Create Flash API endpoints with FastAPI (using the same script syntax).

Follow the steps in the next section to install Flash and create your first script before learning how to [create Flash API endpoints](#create-flash-api-endpoints).

To learn more about how Flash works, see [Key concepts](#key-concepts).

## Get started

Before you can use Flash, you'll need:

- Python 3.9 (or higher) installed on your local machine.
- A Runpod account with API key ([sign up here](https://runpod.io/console)).
- Basic knowledge of Python and async programming.

### Step 1: Install Flash

```bash
pip install runpod-flash
```

### Step 2: Set your API key

Generate an API key from the [Runpod account settings](https://docs.runpod.io/get-started/api-keys) page and set it as an environment variable:

```bash
export RUNPOD_API_KEY=[YOUR_API_KEY]
```

Or save it in a `.env` file in your project directory:

```bash
echo "RUNPOD_API_KEY=[YOUR_API_KEY]" > .env
```

### Step 3: Create your first Flash function

Add the following code to a new Python file:

```python
import asyncio
from runpod_flash import remote, LiveServerless
from dotenv import load_dotenv

# Uncomment if using a .env file
# load_dotenv()

# Configure GPU resources
gpu_config = LiveServerless(name="flash-quickstart")

@remote(
    resource_config=gpu_config,
    dependencies=["torch", "numpy"]
)
def gpu_compute(data):
    import torch
    import numpy as np
    
    # This runs on a GPU in Runpod's cloud
    tensor = torch.tensor(data, device="cuda")
    result = tensor.sum().item()
    
    return {
        "result": result,
        "device": torch.cuda.get_device_name(0)
    }

async def main():
    # This runs locally
    result = await gpu_compute([1, 2, 3, 4, 5])
    print(f"Sum: {result['result']}")
    print(f"Computed on: {result['device']}")

if __name__ == "__main__":
    asyncio.run(main())
```

Run the example:

```bash
python your_script.py
```

The first time you run the script, it will take significantly longer to process than successive runs (about one minute for first run vs. one second for future runs), as your endpoint must be initialized.

When it's finished, you should see output similar to this:

```bash
2025-11-19 12:35:15,109 | INFO  | Created endpoint: rb50waqznmn2kg - flash-quickstart-fb
2025-11-19 12:35:15,112 | INFO  | URL: https://console.runpod.io/serverless/user/endpoint/rb50waqznmn2kg
2025-11-19 12:35:15,114 | INFO  | LiveServerless:rb50waqznmn2kg | API /run
2025-11-19 12:35:15,655 | INFO  | LiveServerless:rb50waqznmn2kg | Started Job:b0b341e7-e460-4305-9acd-fc2dfd1bd65c-u2
2025-11-19 12:35:15,762 | INFO  | Job:b0b341e7-e460-4305-9acd-fc2dfd1bd65c-u2 | Status: IN_QUEUE
2025-11-19 12:35:16,301 | INFO  | Job:b0b341e7-e460-4305-9acd-fc2dfd1bd65c-u2 | .
2025-11-19 12:35:17,756 | INFO  | Job:b0b341e7-e460-4305-9acd-fc2dfd1bd65c-u2 | ..
2025-11-19 12:35:22,610 | INFO  | Job:b0b341e7-e460-4305-9acd-fc2dfd1bd65c-u2 | ...
2025-11-19 12:35:37,163 | INFO  | Job:b0b341e7-e460-4305-9acd-fc2dfd1bd65c-u2 | ....
2025-11-19 12:35:59,248 | INFO  | Job:b0b341e7-e460-4305-9acd-fc2dfd1bd65c-u2 | .....
2025-11-19 12:36:09,983 | INFO  | Job:b0b341e7-e460-4305-9acd-fc2dfd1bd65c-u2 | Status: COMPLETED
2025-11-19 12:36:10,068 | INFO  | Worker:icmkdgnrmdf8gz | Delay Time: 51842 ms
2025-11-19 12:36:10,068 | INFO  | Worker:icmkdgnrmdf8gz | Execution Time: 1533 ms
2025-11-19 17:36:07,485 | INFO  | Installing Python dependencies: ['torch', 'numpy']
Sum: 15
Computed on: NVIDIA GeForce RTX 4090
```

## Create Flash API endpoints

You can use Flash to deploy and serve API endpoints that compute responses using GPU and CPU Serverless workers. Use `flash run` for local development of `@remote` functions, then `flash deploy` to deploy your full application to Runpod Serverless for production.

These endpoints use the same Python `@remote` decorators [demonstrated above](#get-started)

### Step 1: Initialize a new project

Use the `flash init` command to generate a structured project template with a preconfigured FastAPI application entry point.

Run this command to initialize a new project directory:

```bash
flash init my_project
```

You can also initialize your current directory:
```
flash init
```

For complete CLI documentation, see the [Flash CLI Reference](src/runpod_flash/cli/docs/README.md).

### Step 2: Explore the project template

This is the structure of the project template created by `flash init`:

```txt
my_project/
├── main.py                    # FastAPI application entry point
├── workers/
│   ├── gpu/                   # GPU worker example
│   │   ├── __init__.py        # FastAPI router
│   │   └── endpoint.py        # GPU script @remote decorated function
│   └── cpu/                   # CPU worker example
│       ├── __init__.py        # FastAPI router
│       └── endpoint.py        # CPU script with @remote decorated function
├── .env               # Environment variable template
├── .gitignore                 # Git ignore patterns
├── .flashignore               # Flash deployment ignore patterns
├── requirements.txt           # Python dependencies
└── README.md                  # Project documentation
```

This template includes:

- A FastAPI application entry point and routers.
- Templates for Python dependencies, `.env`, `.gitignore`, etc.
- Flash scripts (`endpoint.py`) for both GPU and CPU workers, which include:
    - Pre-configured worker scaling limits using the `LiveServerless()` object.
    - A `@remote` decorated function that returns a response from a worker.

When you start the FastAPI server, it creates API endpoints at `/gpu/hello` and `/cpu/hello`, which call the remote function described in their respective `endpoint.py` files.

### Step 3: Install Python dependencies

After initializing the project, navigate into the project directory:

```bash
cd my_project
```

Install required dependencies:

```bash
pip install -r requirements.txt
```

### Step 4: Configure your API key

Open the `.env` template file in a text editor and add your [Runpod API key](https://docs.runpod.io/get-started/api-keys):

```bash
# Use your text editor of choice, e.g.
cursor .env
```

Remove the `#` symbol from the beginning of the `RUNPOD_API_KEY` line and replace `your_api_key_here` with your actual Runpod API key:

```txt
RUNPOD_API_KEY=your_api_key_here
# FLASH_HOST=localhost
# FLASH_PORT=8888
# LOG_LEVEL=INFO
```

Save the file and close it.

### Step 5: Start the local API server

Use `flash run` to start the API server:

```bash
flash run
```

Open a new terminal tab or window and test your GPU API using cURL:

```bash
curl -X POST http://localhost:8888/gpu/hello \
    -H "Content-Type: application/json" \
    -d '{"message": "Hello from the GPU!"}'
```

If you switch back to the terminal tab where you used `flash run`, you'll see the details of the job's progress.

For more `flash run` options and configuration, see the [flash run documentation](src/runpod_flash/cli/docs/flash-run.md).

### Faster testing with auto-provisioning

For development with multiple endpoints, use `--auto-provision` to deploy all resources before testing:

```bash
flash run --auto-provision
```

This eliminates cold-start delays by provisioning all serverless endpoints upfront. Endpoints are cached and reused across server restarts, making subsequent runs much faster. Resources are identified by name, so the same endpoint won't be re-deployed if configuration hasn't changed.

### Step 6: Open the API explorer

Besides starting the API server, `flash run` also starts an interactive API explorer. Point your web browser at [http://localhost:8888/docs](http://localhost:8888/docs) to explore the API.

To run remote functions in the explorer:

1. Expand one of the functions under **GPU Workers** or **CPU Workers**.
2. Click **Try it out** and then **Execute**

You'll get a response from your workers right in the explorer.

### Step 7: Customize your API

To customize your API endpoint and functionality:

1. Add/edit remote functions in your `endpoint.py` files.
2. Test the scripts individually by running `python endpoint.py`.
3. Configure your FastAPI routers by editing the `__init__.py` files.
4. Add any new endpoints to your `main.py` file.

## CLI Reference

Flash provides a command-line interface for project management, development, and deployment:

### Main Commands

- **`flash init`** - Initialize a new Flash project with template structure
- **`flash run`** - Start local development server to test your `@remote` functions with auto-reload
- **`flash build`** - Build deployment artifact with all dependencies
- **`flash deploy`** - Build and deploy your application to Runpod Serverless in one step

### Management Commands

- **`flash env`** - Manage deployment environments (dev, staging, production)
  - `list`, `create`, `get`, `delete` subcommands
- **`flash app`** - Manage Flash applications (top-level organization)
  - `list`, `create`, `get`, `delete` subcommands
- **`flash undeploy`** - Manage and remove deployed endpoints

### Quick Examples

```bash
# Initialize and run locally
flash init my-project
cd my-project
flash run --auto-provision

# Build and deploy to production
flash build
flash deploy --env production

# Manage environments
flash env create staging
flash env list
flash deploy --env staging

# Clean up
flash undeploy --interactive
flash env delete staging
```

### Complete Documentation

For complete CLI documentation including all options, examples, and troubleshooting:

**[Flash CLI Documentation](src/runpod_flash/cli/docs/README.md)**

Individual command references:
- [flash init](src/runpod_flash/cli/docs/flash-init.md) - Project initialization
- [flash run](src/runpod_flash/cli/docs/flash-run.md) - Development server
- [flash build](src/runpod_flash/cli/docs/flash-build.md) - Build artifacts
- [flash deploy](src/runpod_flash/cli/docs/flash-deploy.md) - Deployment
- [flash env](src/runpod_flash/cli/docs/flash-env.md) - Environment management
- [flash app](src/runpod_flash/cli/docs/flash-app.md) - App management
- [flash undeploy](src/runpod_flash/cli/docs/flash-undeploy.md) - Endpoint removal

## Key concepts

### Remote functions

The Flash `@remote` decorator marks functions for execution on Runpod's infrastructure. Everything inside the decorated function runs remotely, while code outside runs locally.

```python
@remote(resource_config=config, dependencies=["pandas"])
def process_data(data):
    # This code runs remotely
    import pandas as pd
    df = pd.DataFrame(data)
    return df.describe().to_dict()

async def main():
    # This code runs locally
    result = await process_data(my_data)
```

### Resource configuration

Flash provides fine-grained control over hardware allocation through configuration objects:

```python
from runpod_flash import LiveServerless, GpuGroup, CpuInstanceType, PodTemplate

# GPU configuration
gpu_config = LiveServerless(
    name="ml-inference",
    gpus=[GpuGroup.AMPERE_80],  # A100 80GB
    workersMax=5,
    template=PodTemplate(containerDiskInGb=100)  # Extra disk space
)

# CPU configuration
cpu_config = LiveServerless(
    name="data-processor",
    instanceIds=[CpuInstanceType.CPU5C_4_16],  # 4 vCPU, 16GB RAM
    workersMax=3
)
```

### Dependency management

Specify Python packages in the decorator, and Flash installs them automatically:

```python
@remote(
    resource_config=gpu_config,
    dependencies=["transformers==4.36.0", "torch", "pillow"]
)
def generate_image(prompt):
    # Import inside the function
    from transformers import pipeline
    import torch
    from PIL import Image
    
    # Your code here
```

### Parallel execution

Run multiple remote functions concurrently using Python's async capabilities:

```python
# Process multiple items in parallel
results = await asyncio.gather(
    process_item(item1),
    process_item(item2),
    process_item(item3)
)
```

### Load-Balanced Endpoints with HTTP Routing

For API endpoints requiring low-latency HTTP access with direct routing, use load-balanced endpoints:

```python
from runpod_flash import LiveLoadBalancer, remote

api = LiveLoadBalancer(name="api-service")

@remote(api, method="POST", path="/api/process")
async def process_data(x: int, y: int):
    return {"result": x + y}

@remote(api, method="GET", path="/api/health")
def health_check():
    return {"status": "ok"}

# Call functions directly
result = await process_data(5, 3)  # → {"result": 8}
```

**Key differences from queue-based endpoints:**
- **Direct HTTP routing** - Requests routed directly to workers, no queue
- **Lower latency** - No queuing overhead
- **Custom HTTP methods** - GET, POST, PUT, DELETE, PATCH support
- **No automatic retries** - Users handle errors directly

Load-balanced endpoints are ideal for REST APIs, webhooks, and real-time services. Queue-based endpoints are better for batch processing and fault-tolerant workflows.

For detailed information:
- **User guide:** [Using @remote with Load-Balanced Endpoints](docs/Using_Remote_With_LoadBalancer.md)
- **Runtime architecture:** [LoadBalancer Runtime Architecture](docs/LoadBalancer_Runtime_Architecture.md) - details on deployment, request flows, and execution

## How it works

Flash orchestrates workflow execution through a sophisticated multi-step process:

1. **Function identification**: The `@remote` decorator marks functions for remote execution, enabling Flash to distinguish between local and remote operations.
2. **Dependency analysis**: Flash automatically analyzes function dependencies to construct an optimal execution order, ensuring data flows correctly between sequential and parallel operations.
3. **Resource provisioning and execution**: For each remote function, Flash:
   - Dynamically provisions endpoint and worker resources on Runpod's infrastructure.
   - Serializes and securely transfers input data to the remote worker.
   - Executes the function on the remote infrastructure with the specified GPU or CPU resources.
   - Returns results to your local environment for further processing.
4. **Data orchestration**: Results flow seamlessly between functions according to your local Python code structure, maintaining the same programming model whether functions run locally or remotely.


## Advanced features

### Custom Docker images

`LiveServerless` resources use a fixed Docker image that's optimized for Flash runtime, and supports full remote code execution. For specialized environments that require a custom Docker image, use `ServerlessEndpoint` or `CpuServerlessEndpoint`:

```python
from runpod_flash import ServerlessEndpoint

custom_gpu = ServerlessEndpoint(
    name="custom-ml-env",
    imageName="pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime",
    gpus=[GpuGroup.AMPERE_80]
)
```

Unlike `LiveServerless`, these endpoints only support dictionary payloads in the form of `{"input": {...}}` (similar to a traditional [Serverless endpoint request](https://docs.runpod.io/serverless/endpoints/send-requests)), and cannot execute arbitrary Python functions remotely.

### Persistent storage with network volumes

Attach [network volumes](https://docs.runpod.io/storage/network-volumes) for persistent storage across workers and endpoints:

```python
config = LiveServerless(
    name="model-server",
    networkVolumeId="vol_abc123",  # Your volume ID
    template=PodTemplate(containerDiskInGb=100)
)
```

### Environment variables

Pass configuration to remote functions:

```python
config = LiveServerless(
    name="api-worker",
    env={"HF_TOKEN": "your_token", "MODEL_ID": "gpt2"}
)
```

Environment variables are excluded from configuration hashing, which means changing environment values won't trigger endpoint recreation. This allows different processes to load environment variables from `.env` files without causing false drift detection. Only structural changes (like GPU type, image, or template modifications) trigger endpoint updates.

### Build Process

Flash uses a sophisticated build process to package your application for deployment.

#### How Flash Builds Your Application

When you run `flash build`, the following happens:

1. **Discovery**: Flash scans your code for `@remote` decorated functions
2. **Grouping**: Functions are grouped by their `resource_config`
3. **Manifest Creation**: A `flash_manifest.json` file maps functions to their endpoints
4. **Dependency Installation**: Python packages are installed with Linux x86_64 compatibility
5. **Packaging**: Everything is bundled into `artifact.tar.gz` for deployment

#### Cross-Platform Builds

Flash automatically handles cross-platform builds, ensuring your deployments work correctly regardless of your development platform:

- **Automatic Platform Targeting**: Dependencies are installed for Linux x86_64 (Runpod's serverless platform), even when building on macOS or Windows
- **Python Version Matching**: The build uses your current Python version to ensure package compatibility
- **Binary Wheel Enforcement**: Only pre-built binary wheels are used, preventing platform-specific compilation issues

This means you can build on macOS ARM64, Windows, or any other platform, and the resulting package will run correctly on Runpod serverless.

#### Cross-Endpoint Function Calls

Flash enables functions on different endpoints to call each other. The runtime automatically discovers endpoints using the manifest and routes calls appropriately:

```python
# CPU endpoint function
@remote(resource_config=cpu_config)
def preprocess(data):
    return clean_data

# GPU endpoint function
@remote(resource_config=gpu_config)
async def inference(data):
    # Can call CPU endpoint function
    clean = preprocess(data)
    return result
```

The runtime wrapper handles service discovery and routing automatically.

#### Build Artifacts

After `flash build` completes:
- `.flash/.build/`: Temporary build directory (removed unless `--keep-build`)
- `.flash/artifact.tar.gz`: Deployment package
- `.flash/flash_manifest.json`: Service discovery configuration

For information on load-balanced endpoints (required for Mothership and HTTP services), see [docs/Load_Balancer_Endpoints.md](docs/Load_Balancer_Endpoints.md).

#### Troubleshooting Build Issues

**No @remote functions found:**
- Ensure your functions are decorated with `@remote(resource_config)`
- Check that Python files are not excluded by `.gitignore` or `.flashignore`
- Verify function decorators have valid syntax

**Build succeeded but deployment failed:**
- Verify all function imports work in the deployment environment
- Check that environment variables required by your functions are available
- Review the generated `flash_manifest.json` for correct function mappings

**Dependency installation failed:**
- If a package doesn't have pre-built Linux x86_64 wheels, the build will fail with an error
- For newer Python versions (3.13+), some packages may require manylinux_2_27 or higher
- Ensure you have standard pip installed (`python -m ensurepip --upgrade`) for best compatibility
- uv pip has known issues with newer manylinux tags - standard pip is recommended
- Check PyPI to verify the package supports your Python version on Linux

#### Managing Bundle Size

Runpod serverless has a **500MB deployment limit**. Exceeding this limit will cause deployment failures.

Use `--exclude` to skip packages already in your worker-flash Docker image:

```bash
# For GPU deployments (PyTorch pre-installed)
flash build --exclude torch,torchvision,torchaudio

# Check your resource config to determine which base image you're using
```

**Which packages to exclude depends on your resource config:**
- **GPU resources** → PyTorch images have torch/torchvision/torchaudio pre-installed
- **CPU resources** → Python slim images have NO ML frameworks pre-installed
- **Load-balanced** → Same as above, depends on GPU vs CPU variant

See [worker-flash](https://github.com/runpod-workers/worker-flash) for base image details.

## Configuration

### GPU configuration parameters

The following parameters can be used with `LiveServerless` (full remote code execution) and `ServerlessEndpoint` (dictionary payload only) to configure your Runpod GPU endpoints:

| Parameter          | Description                                     | Default       | Example Values                      |
|--------------------|-------------------------------------------------|---------------|-------------------------------------|
| `name`             | (Required) Name for your endpoint               | `""`          | `"stable-diffusion-server"`         |
| `gpus`             | GPU pool IDs that can be used by workers        | `[GpuGroup.ANY]` | `[GpuGroup.ADA_24]` for RTX 4090 |
| `gpuCount`         | Number of GPUs per worker                       | 1             | 1, 2, 4                             |
| `workersMin`       | Minimum number of workers                       | 0             | Set to 1 for persistence            |
| `workersMax`       | Maximum number of workers                       | 3             | Higher for more concurrency         |
| `idleTimeout`      | Seconds before scaling down                     | 5             | 10, 30, 60                          |
| `env`              | Environment variables                           | `None`        | `{"HF_TOKEN": "xyz"}`               |
| `networkVolumeId`  | Persistent storage ID                           | `None`        | `"vol_abc123"`                      |
| `executionTimeoutMs`| Max execution time (ms)                        | 0 (no limit)  | 600000 (10 min)                     |
| `scalerType`       | Scaling strategy                                | `QUEUE_DELAY` | `REQUEST_COUNT`                     |
| `scalerValue`      | Scaling parameter value                         | 4             | 1-10 range typical                  |
| `locations`        | Preferred datacenter locations                  | `None`        | `"us-east,eu-central"`              |
| `imageName`        | Custom Docker image (`ServerlessEndpoint` only)   | Fixed for LiveServerless | `"pytorch/pytorch:latest"`, `"my-registry/custom:v1.0"` |

### CPU configuration parameters

The same GPU configuration parameters above apply to `LiveServerless` (full remote code execution) and `CpuServerlessEndpoint` (dictionary payload only), with these additional CPU-specific parameters:

| Parameter          | Description                                     | Default       | Example Values                      |
|--------------------|-------------------------------------------------|---------------|-------------------------------------|
| `instanceIds`      | CPU Instance Types (forces a CPU endpoint type) | `None`        | `[CpuInstanceType.CPU5C_2_4]`       |
| `imageName`        | Custom Docker image (`CpuServerlessEndpoint` only) | Fixed for `LiveServerless` | `"python:3.11-slim"`, `"my-registry/custom:v1.0"` |

### Resource class comparison

| Feature | LiveServerless | ServerlessEndpoint | CpuServerlessEndpoint |
|---------|----------------|-------------------|----------------------|
| **Remote code execution** | ✅ Full Python function execution | ❌ Dictionary payload only | ❌ Dictionary payload only |
| **Custom Docker images** | ❌ Fixed optimized images | ✅ Any Docker image | ✅ Any Docker image |
| **Use case** | Dynamic remote functions | Traditional API endpoints | Traditional CPU endpoints |
| **Function returns** | Any Python object | Dictionary only | Dictionary only |
| **@remote decorator** | Full functionality | Limited to payload passing | Limited to payload passing |

### Available GPU types

Some common GPU groups available through `GpuGroup`:

- `GpuGroup.ANY` - Any available GPU (default)
- `GpuGroup.ADA_24` - NVIDIA GeForce RTX 4090
- `GpuGroup.AMPERE_80` - NVIDIA A100 80GB
- `GpuGroup.AMPERE_48` - NVIDIA A40, RTX A6000
- `GpuGroup.AMPERE_24` - NVIDIA RTX A5000, L4, RTX 3090


### Available CPU instance types

- `CpuInstanceType.CPU3G_1_4` - (cpu3g-1-4) 3rd gen general purpose, 1 vCPU, 4GB RAM
- `CpuInstanceType.CPU3G_2_8` - (cpu3g-2-8) 3rd gen general purpose, 2 vCPU, 8GB RAM
- `CpuInstanceType.CPU3G_4_16` - (cpu3g-4-16) 3rd gen general purpose, 4 vCPU, 16GB RAM
- `CpuInstanceType.CPU3G_8_32` - (cpu3g-8-32) 3rd gen general purpose, 8 vCPU, 32GB RAM
- `CpuInstanceType.CPU3C_1_2` - (cpu3c-1-2) 3rd gen compute-optimized, 1 vCPU, 2GB RAM
- `CpuInstanceType.CPU3C_2_4` - (cpu3c-2-4) 3rd gen compute-optimized, 2 vCPU, 4GB RAM
- `CpuInstanceType.CPU3C_4_8` - (cpu3c-4-8) 3rd gen compute-optimized, 4 vCPU, 8GB RAM
- `CpuInstanceType.CPU3C_8_16` - (cpu3c-8-16) 3rd gen compute-optimized, 8 vCPU, 16GB RAM
- `CpuInstanceType.CPU5C_1_2` - (cpu5c-1-2) 5th gen compute-optimized, 1 vCPU, 2GB RAM
- `CpuInstanceType.CPU5C_2_4` - (cpu5c-2-4) 5th gen compute-optimized, 2 vCPU, 4GB RAM
- `CpuInstanceType.CPU5C_4_8` - (cpu5c-4-8) 5th gen compute-optimized, 4 vCPU, 8GB RAM
- `CpuInstanceType.CPU5C_8_16` - (cpu5c-8-16) 5th gen compute-optimized, 8 vCPU, 16GB RAM

### Logging

Flash automatically logs CLI activity to local files during development. Logs are written to `.flash/logs/activity.log` with daily rotation and 30-day retention by default.

**Configuration via environment variables:**

```bash
# Disable file logging (CLI continues with stdout-only)
export FLASH_FILE_LOGGING_ENABLED=false

# Keep only 7 days of logs
export FLASH_LOG_RETENTION_DAYS=7

# Use custom log directory
export FLASH_LOG_DIR=/var/log/flash
```

File logging is automatically disabled in deployed containers. See [flash-logging.md](src/runpod_flash/cli/docs/flash-logging.md) for complete documentation.

## Workflow examples

### Basic GPU workflow

```python
import asyncio
from runpod_flash import remote, LiveServerless

# Simple GPU configuration
gpu_config = LiveServerless(name="example-gpu-server")

@remote(
    resource_config=gpu_config,
    dependencies=["torch", "numpy"]
)
def gpu_compute(data):
    import torch
    import numpy as np
    
    # Convert to tensor and perform computation on GPU
    tensor = torch.tensor(data, device="cuda")
    result = tensor.sum().item()
    
    # Get GPU info
    gpu_info = torch.cuda.get_device_properties(0)
    
    return {
        "result": result,
        "gpu_name": gpu_info.name,
        "cuda_version": torch.version.cuda
    }

async def main():
    result = await gpu_compute([1, 2, 3, 4, 5])
    print(f"Result: {result['result']}")
    print(f"Computed on: {result['gpu_name']} with CUDA {result['cuda_version']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Advanced GPU workflow with template configuration

```python
import asyncio
from runpod_flash import remote, LiveServerless, GpuGroup, PodTemplate
import base64

# Advanced GPU configuration with consolidated template overrides
sd_config = LiveServerless(
    gpus=[GpuGroup.AMPERE_80],  # A100 80GB GPUs
    name="example_image_gen_server",
    template=PodTemplate(containerDiskInGb=100),  # Large disk for models
    workersMax=3,
    idleTimeout=10
)

@remote(
    resource_config=sd_config,
    dependencies=["diffusers", "transformers", "torch", "accelerate", "safetensors"]
)
def generate_image(prompt, width=512, height=512):
    import torch
    from diffusers import StableDiffusionPipeline
    import io
    import base64
    
    # Load pipeline (benefits from large container disk)
    pipeline = StableDiffusionPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        torch_dtype=torch.float16
    )
    pipeline = pipeline.to("cuda")
    
    # Generate image
    image = pipeline(prompt=prompt, width=width, height=height).images[0]
    
    # Convert to base64 for return
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return {"image": img_str, "prompt": prompt}

async def main():
    result = await generate_image("A serene mountain landscape at sunset")
    print(f"Generated image for: {result['prompt']}")
    # Save image locally if needed
    # img_data = base64.b64decode(result["image"])
    # with open("output.png", "wb") as f:
    #     f.write(img_data)

if __name__ == "__main__":
    asyncio.run(main())
```

### Basic CPU workflow

```python
import asyncio
from runpod_flash import remote, LiveServerless, CpuInstanceType

# Simple CPU configuration
cpu_config = LiveServerless(
    name="example-cpu-server",
    instanceIds=[CpuInstanceType.CPU5G_2_8],  # 2 vCPU, 8GB RAM
)

@remote(
    resource_config=cpu_config,
    dependencies=["pandas", "numpy"]
)
def cpu_data_processing(data):
    import pandas as pd
    import numpy as np
    import platform
    
    # Process data using CPU
    df = pd.DataFrame(data)
    
    return {
        "row_count": len(df),
        "column_count": len(df.columns) if not df.empty else 0,
        "mean_values": df.select_dtypes(include=[np.number]).mean().to_dict(),
        "system_info": platform.processor(),
        "platform": platform.platform()
    }

async def main():
    sample_data = [
        {"name": "Alice", "age": 30, "score": 85},
        {"name": "Bob", "age": 25, "score": 92},
        {"name": "Charlie", "age": 35, "score": 78}
    ]
    
    result = await cpu_data_processing(sample_data)
    print(f"Processed {result['row_count']} rows on {result['platform']}")
    print(f"Mean values: {result['mean_values']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Advanced CPU workflow with template configuration

```python
import asyncio
import base64
from runpod_flash import remote, LiveServerless, CpuInstanceType, PodTemplate

# Advanced CPU configuration with template overrides
data_processing_config = LiveServerless(
    name="advanced-cpu-processor",
    instanceIds=[CpuInstanceType.CPU5C_4_16, CpuInstanceType.CPU3C_4_8],  # Fallback options
    template=PodTemplate(
        containerDiskInGb=20,  # Extra disk space for data processing
        env=[{"key": "PYTHONPATH", "value": "/workspace"}]  # Custom environment
    ),
    workersMax=5,
    idleTimeout=15,
    env={"PROCESSING_MODE": "batch", "DEBUG": "false"}  # Additional env vars
)

@remote(
    resource_config=data_processing_config,
    dependencies=["pandas", "numpy", "scipy", "scikit-learn"]
)
def advanced_data_analysis(dataset, analysis_type="full"):
    import pandas as pd
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA
    import platform
    
    # Create DataFrame
    df = pd.DataFrame(dataset)
    
    # Perform analysis based on type
    results = {
        "platform": platform.platform(),
        "dataset_shape": df.shape,
        "memory_usage": df.memory_usage(deep=True).sum()
    }
    
    if analysis_type == "full":
        # Advanced statistical analysis
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            # Standardize data
            scaler = StandardScaler()
            scaled_data = scaler.fit_transform(df[numeric_cols])
            
            # PCA analysis
            pca = PCA(n_components=min(len(numeric_cols), 3))
            pca_result = pca.fit_transform(scaled_data)
            
            results.update({
                "correlation_matrix": df[numeric_cols].corr().to_dict(),
                "pca_explained_variance": pca.explained_variance_ratio_.tolist(),
                "pca_shape": pca_result.shape
            })
    
    return results

async def main():
    # Generate sample dataset
    sample_data = [
        {"feature1": np.random.randn(), "feature2": np.random.randn(), 
         "feature3": np.random.randn(), "category": f"cat_{i%3}"}
        for i in range(1000)
    ]
    
    result = await advanced_data_analysis(sample_data, "full")
    print(f"Processed dataset with shape: {result['dataset_shape']}")
    print(f"Memory usage: {result['memory_usage']} bytes")
    print(f"PCA explained variance: {result.get('pca_explained_variance', 'N/A')}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Hybrid GPU/CPU workflow

```python
import asyncio
from runpod_flash import remote, LiveServerless, GpuGroup, CpuInstanceType, PodTemplate

# GPU configuration for model inference
gpu_config = LiveServerless(
    name="ml-inference-gpu",
    gpus=[GpuGroup.AMPERE_24],  # RTX 3090/A5000
    template=PodTemplate(containerDiskInGb=50),  # Space for models
    workersMax=2
)

# CPU configuration for data preprocessing
cpu_config = LiveServerless(
    name="data-preprocessor",
    instanceIds=[CpuInstanceType.CPU5C_4_16],  # 4 vCPU, 16GB RAM
    template=PodTemplate(
        containerDiskInGb=30,
        env=[{"key": "NUMPY_NUM_THREADS", "value": "4"}]
    ),
    workersMax=3
)

@remote(
    resource_config=cpu_config,
    dependencies=["pandas", "numpy", "scikit-learn"]
)
def preprocess_data(raw_data):
    import pandas as pd
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    
    # Data cleaning and preprocessing
    df = pd.DataFrame(raw_data)
    
    # Handle missing values
    df = df.fillna(df.mean(numeric_only=True))
    
    # Normalize numeric features
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        scaler = StandardScaler()
        df[numeric_cols] = scaler.fit_transform(df[numeric_cols])
    
    return {
        "processed_data": df.to_dict('records'),
        "shape": df.shape,
        "columns": list(df.columns)
    }

@remote(
    resource_config=gpu_config,
    dependencies=["torch", "transformers", "numpy"]
)
def run_inference(processed_data):
    import torch
    import numpy as np
    
    # Simulate ML model inference on GPU
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # Convert to tensor
    data_array = np.array([list(item.values()) for item in processed_data["processed_data"]])
    tensor = torch.tensor(data_array, dtype=torch.float32).to(device)
    
    # Simple neural network simulation
    with torch.no_grad():
        # Simulate model computation
        result = torch.nn.functional.softmax(tensor.mean(dim=1), dim=0)
        predictions = result.cpu().numpy().tolist()
    
    return {
        "predictions": predictions,
        "device_used": str(device),
        "input_shape": tensor.shape
    }

async def ml_pipeline(raw_dataset):
    """Complete ML pipeline: CPU preprocessing -> GPU inference"""
    print("Step 1: Preprocessing data on CPU...")
    preprocessed = await preprocess_data(raw_dataset)
    print(f"Preprocessed data shape: {preprocessed['shape']}")
    
    print("Step 2: Running inference on GPU...")
    results = await run_inference(preprocessed)
    print(f"Inference completed on: {results['device_used']}")
    
    return {
        "preprocessing": preprocessed,
        "inference": results
    }

async def main():
    # Sample dataset
    raw_data = [
        {"feature1": np.random.randn(), "feature2": np.random.randn(), 
         "feature3": np.random.randn(), "label": i % 2}
        for i in range(100)
    ]
    
    # Run the complete pipeline
    results = await ml_pipeline(raw_data)
    
    print("\nPipeline Results:")
    print(f"Data processed: {results['preprocessing']['shape']}")
    print(f"Predictions generated: {len(results['inference']['predictions'])}")
    print(f"GPU device: {results['inference']['device_used']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Multi-stage ML pipeline example

```python
import os
import asyncio
from runpod_flash import remote, LiveServerless

# Configure Runpod resources
runpod_config = LiveServerless(name="multi-stage-pipeline-server")

# Feature extraction on GPU
@remote(
    resource_config=runpod_config,
    dependencies=["torch", "transformers"]
)
def extract_features(texts):
    import torch
    from transformers import AutoTokenizer, AutoModel
    
    tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")
    model = AutoModel.from_pretrained("bert-base-uncased")
    model.to("cuda")
    
    features = []
    for text in texts:
        inputs = tokenizer(text, return_tensors="pt").to("cuda")
        with torch.no_grad():
            outputs = model(**inputs)
        features.append(outputs.last_hidden_state[:, 0].cpu().numpy().tolist()[0])
    
    return features

# Classification on GPU
@remote(
    resource_config=runpod_config,
    dependencies=["torch", "sklearn"]
)
def classify(features, labels=None):
    import torch
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    
    features_np = np.array(features[1:] if labels is None and isinstance(features, list) and len(features)>0 and isinstance(features[0], dict) else features)
    
    if labels is not None:
        labels_np = np.array(labels)
        classifier = LogisticRegression()
        classifier.fit(features_np, labels_np)
        
        coefficients = {
            "coef": classifier.coef_.tolist(),
            "intercept": classifier.intercept_.tolist(),
            "classes": classifier.classes_.tolist()
        }
        return coefficients
    else:
        coefficients = features[0]
        
        classifier = LogisticRegression()
        classifier.coef_ = np.array(coefficients["coef"])
        classifier.intercept_ = np.array(coefficients["intercept"])
        classifier.classes_ = np.array(coefficients["classes"])
        
        # Predict
        predictions = classifier.predict(features_np)
        probabilities = classifier.predict_proba(features_np)
        
        return {
            "predictions": predictions.tolist(),
            "probabilities": probabilities.tolist()
        }

# Complete pipeline
async def text_classification_pipeline(train_texts, train_labels, test_texts):
    train_features = await extract_features(train_texts)
    test_features = await extract_features(test_texts)
    
    model_coeffs = await classify(train_features, train_labels)
    
    # For inference, pass model coefficients along with test features
    # The classify function expects a list where the first element is the model (coeffs)
    # and subsequent elements are features for prediction.
    predictions = await classify([model_coeffs] + test_features)
    
    return predictions
```

### More examples

You can find many more examples in the [flash-examples repository](https://github.com/runpod/flash-examples).

## Use cases

Flash is well-suited for a diverse range of AI and data processing workloads:

- **Multi-modal AI pipelines**: Orchestrate unified workflows combining text, image, and audio models with GPU acceleration.
- **Distributed model training**: Scale training operations across multiple GPU workers for faster model development.
- **AI research experimentation**: Rapidly prototype and test complex model combinations without infrastructure overhead.
- **Production inference systems**: Deploy sophisticated multi-stage inference pipelines for real-world applications.
- **Data processing workflows**: Efficiently process large datasets using CPU workers for general computation and GPU workers for accelerated tasks.
- **Hybrid GPU/CPU workflows**: Optimize cost and performance by combining CPU preprocessing with GPU inference.

## Limitations

- Serverless deployments using Flash are currently restricted to the `EU-RO-1` datacenter.
- Flash is designed primarily for local development and live-testing workflows.
- While Flash supports provisioning traditional Serverless endpoints (non-Live endpoints), the interface for interacting with these resources will change in upcoming releases. For now, focus on using `LiveServerless` for the most stable development experience, as it provides full remote code execution without requiring custom Docker images.
- As you work through the Flash examples repository, you'll accumulate multiple endpoints in your Runpod account. These endpoints persist until manually deleted through the Runpod console. A `flash undeploy` command is in development to streamline cleanup, but for now, regular manual deletion of unused endpoints is recommended to avoid unnecessary charges.
- Finally, be aware of your account's maximum worker capacity limits. Flash can rapidly scale workers across multiple endpoints, and you may hit capacity constraints faster than with traditional deployment patterns. If you find yourself consistently reaching worker limits, contact Runpod support to increase your account's capacity allocation.

## Contributing

We welcome contributions to Flash! Whether you're fixing bugs, adding features, or improving documentation, your help makes this project better.

### Development setup

1. Fork and clone the repository.
2. Set up your development environment following the project guidelines.
3. Make your changes following our coding standards.
4. Test your changes thoroughly.
5. Submit a pull request.

### Release process

This project uses an automated release system built on Release Please. For detailed information about how releases work, including conventional commits, versioning, and the CI/CD pipeline, see our [Release System Documentation](RELEASE_SYSTEM.md).

**Quick reference for contributors:**
- Use conventional commits: `feat:`, `fix:`, `docs:`, etc.
- CI automatically runs quality checks on all PRs.
- Release PRs are created automatically when changes are merged to main.
- Releases are published to PyPI automatically when release PRs are merged.

## Troubleshooting

### Authentication errors

Verify your API key is set correctly:

```bash
echo $RUNPOD_API_KEY  # Should show your key
```

### Import errors in remote functions

Remember to import packages inside remote functions:

```python
@remote(dependencies=["requests"])
def fetch_data(url):
    import requests  # Import here, not at top of file
    return requests.get(url).json()
```

### Performance optimization

- Set `workersMin=1` to keep workers warm and avoid cold starts.
- Use `idleTimeout` to balance cost and responsiveness.
- Choose appropriate GPU types for your workload.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

<p align="center">
  <a href="https://github.com/runpod/runpod-flash">Flash</a> •
  <a href="https://runpod.io">Runpod</a>
</p>
