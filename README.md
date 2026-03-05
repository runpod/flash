# Flash: Serverless computing for AI workloads

Runpod Flash is a Python SDK that streamlines the development and deployment of AI workflows on Runpod's [Serverless infrastructure](http://docs.runpod.io/serverless/overview). Write Python functions locally, and Flash handles the infrastructure, provisioning GPUs and CPUs, managing dependencies, and transferring data, allowing you to focus on building AI applications.

You can find a repository of prebuilt Flash examples at [runpod/flash-examples](https://github.com/runpod/flash-examples).

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

- Build and run standalone Python scripts using the `@Endpoint(...)` decorator.
- Create Flash API endpoints with HTTP routing (using the same `Endpoint` class).

Follow the steps in the next section to install Flash and create your first script before learning how to [create Flash API endpoints](#create-flash-api-endpoints).

To learn more about how Flash works, see [Key concepts](#key-concepts).

## Get started

Before you can use Flash, you'll need:

- Python 3.10 (or higher) installed on your local machine.
- A Runpod account with API key ([sign up here](https://runpod.io/console)).
- Basic knowledge of Python and async programming.

### Step 1: Install Flash

```bash
pip install runpod-flash
```

### Step 2: Authenticate

The easiest way to authenticate is with `flash login`, which opens the Runpod console in your browser and stores the API key automatically:

```bash
flash login
```

Alternatively, you can set an API key manually. Generate one from the [Runpod account settings](https://docs.runpod.io/get-started/api-keys) page and either export it as an environment variable:

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
from runpod_flash import Endpoint, GpuGroup

@Endpoint(
    name="flash-quickstart",
    gpu=GpuGroup.ANY,
    dependencies=["torch", "numpy"],
)
def gpu_compute(data):
    import torch
    import numpy as np

    # this runs on a GPU in Runpod's cloud
    tensor = torch.tensor(data, device="cuda")
    result = tensor.sum().item()

    return {
        "result": result,
        "device": torch.cuda.get_device_name(0),
    }

async def main():
    # this runs locally
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
Sum: 15
Computed on: NVIDIA GeForce RTX 4090
```

## Create Flash API endpoints

You can use Flash to deploy and serve API endpoints that compute responses using GPU and CPU Serverless workers. Use `flash run` for local development, then `flash deploy` to deploy your full application to Runpod Serverless for production.

### Step 1: Initialize a new project

Use the `flash init` command to generate a project template with example worker files.

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
├── gpu_worker.py              # GPU worker with @Endpoint function
├── cpu_worker.py              # CPU worker with @Endpoint function
├── lb_worker.py               # Load-balanced HTTP endpoint
├── .env                       # Environment variable template
├── .gitignore                 # Git ignore patterns
├── .flashignore               # Flash deployment ignore patterns
├── pyproject.toml             # Python dependencies (uv/pip compatible)
└── README.md                  # Project documentation
```

This template includes:

- Example worker files using the `Endpoint` class.
- Templates for Python dependencies, `.env`, `.gitignore`, etc.
- Worker files demonstrate both queue-based (QB) and load-balanced (LB) patterns.

When you run `flash run`, it auto-discovers all `Endpoint` definitions and generates a local development server. Queue-based workers are exposed at `/{file_prefix}/runsync` (e.g., `/gpu_worker/runsync`). Load-balanced routes are exposed at `/{endpoint_name}/{path}` (e.g., `/lb_worker/process`).

### Step 3: Install Python dependencies

After initializing the project, navigate into the project directory:

```bash
cd my_project
```

Install required dependencies using uv (recommended) or pip:

```bash
uv sync        # recommended
# or
pip install -r requirements.txt
```

### Step 4: Set your API key

Add your [Runpod API key](https://docs.runpod.io/get-started/api-keys) to the `.env` file.

Uncomment the `RUNPOD_API_KEY` line and set it to your actual API key:

```env
RUNPOD_API_KEY=your_api_key_here
# FLASH_HOST=localhost
# FLASH_PORT=8888
# LOG_LEVEL=INFO
```


### Step 5: Start the local API server

Use `flash run` to start the API server:

```bash
flash run
```

Open a new terminal tab or window and test your GPU API using cURL:

```bash
curl -X POST http://localhost:8888/gpu_worker/runsync \
    -H "Content-Type: application/json" \
    -d '{"input": {"message": "Hello from the GPU!"}}'
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

1. Expand one of the available endpoints (e.g., `/gpu_worker/runsync`).
2. Click **Try it out** and then **Execute**.

You'll get a response from your workers right in the explorer.

### Step 7: Customize your API

To customize your API:

1. Create new `.py` files with `Endpoint` definitions.
2. Test the scripts individually by running `python your_worker.py`.
3. Run `flash run` to auto-discover all endpoints and serve them.

## CLI Reference

Flash provides a command-line interface for project management, development, and deployment:

### Main Commands

- **`flash login`** - Authenticate via the Runpod console and store credentials locally
- **`flash init`** - Initialize a new Flash project with template structure
- **`flash run`** - Start local development server to test your endpoints with auto-reload
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

### The Endpoint class

The `Endpoint` class is the single entry point for all Flash functionality. It supports four usage patterns:

**Queue-based (QB)** -- one function per endpoint, processed sequentially:

```python
@Endpoint(name="my-worker", gpu=GpuGroup.ADA_24, workers=(0, 3))
async def process(data: dict) -> dict:
    return {"result": data}
```

**Load-balanced (LB)** -- multiple HTTP routes sharing workers:

```python
api = Endpoint(name="my-api", gpu=GpuGroup.ADA_24, workers=(1, 5))

@api.post("/compute")
async def compute(request: dict) -> dict:
    return {"result": request}

@api.get("/health")
async def health():
    return {"status": "ok"}
```

**External image** -- deploy a pre-built Docker image and call it:

```python
vllm = Endpoint(name="vllm", image="vllm/vllm-openai:latest", gpu=GpuGroup.ADA_24)
result = await vllm.post("/v1/completions", {"prompt": "hello"})
```

**Existing endpoint** -- connect to an already-deployed endpoint by ID:

```python
ep = Endpoint(id="abc123")
job = await ep.run({"prompt": "hello"})
await job.wait()
print(job.output)
```

### GPU vs CPU

```python
from runpod_flash import Endpoint, GpuGroup, GpuType

# GPU endpoint (GpuGroup for architecture-level, GpuType for specific models)
@Endpoint(name="ml-inference", gpu=GpuGroup.AMPERE_80)
async def infer(data: dict) -> dict: ...

@Endpoint(name="rtx-worker", gpu=GpuType.NVIDIA_GEFORCE_RTX_4090)
async def render(data: dict) -> dict: ...

# CPU endpoint (string shorthand or CpuInstanceType enum)
@Endpoint(name="data-processor", cpu="cpu5c-4-8")
async def process(data: dict) -> dict: ...
```

GPU and CPU are mutually exclusive. If neither is specified, GPU defaults to `GpuGroup.ANY`.

### Worker scaling

Control how many workers run for your endpoint:

```python
# just a max: workers scale from 0 to 5
@Endpoint(name="elastic", gpu=GpuGroup.ANY, workers=5)

# min and max: always keep 2 warm, scale up to 10
@Endpoint(name="always-on", gpu=GpuGroup.ANY, workers=(2, 10))

# default: (0, 3)
@Endpoint(name="default-scaling", gpu=GpuGroup.ANY)
```

### Dependency management

Specify Python packages in the decorator, and Flash installs them automatically:

```python
@Endpoint(
    name="text-gen",
    gpu=GpuGroup.AMPERE_80,
    dependencies=["transformers==4.36.0", "torch", "pillow"],
)
def generate_image(prompt):
    # import inside the function
    from transformers import pipeline
    import torch
    from PIL import Image

    # your code here
```

### Parallel execution

Run multiple remote functions concurrently using Python's async capabilities:

```python
# process multiple items in parallel
results = await asyncio.gather(
    process_item(item1),
    process_item(item2),
    process_item(item3),
)
```

### Load-balanced endpoints with HTTP routing

For API endpoints requiring low-latency HTTP access with direct routing:

```python
from runpod_flash import Endpoint, GpuGroup

api = Endpoint(name="api-service", gpu=GpuGroup.ADA_24, workers=(1, 5))

@api.post("/api/process")
async def process_data(x: int, y: int):
    return {"result": x + y}

@api.get("/api/health")
def health_check():
    return {"status": "ok"}
```

**Key differences from queue-based endpoints:**
- **Direct HTTP routing** -- requests routed directly to workers, no queue
- **Lower latency** -- no queuing overhead
- **Custom HTTP methods** -- GET, POST, PUT, DELETE, PATCH support
- **No automatic retries** -- users handle errors directly

Load-balanced endpoints are ideal for REST APIs, webhooks, and real-time services. Queue-based endpoints are better for batch processing and fault-tolerant workflows.

For detailed information:
- **User guide:** [Load-Balanced Endpoints](docs/Using_Remote_With_LoadBalancer.md)
- **Runtime architecture:** [LoadBalancer Runtime Architecture](docs/LoadBalancer_Runtime_Architecture.md)

## How it works

Flash orchestrates workflow execution through a multi-step process:

1. **Function identification**: The `Endpoint` class marks functions for remote execution, enabling Flash to distinguish between local and remote operations.
2. **Dependency analysis**: Flash automatically analyzes function dependencies to construct an optimal execution order, ensuring data flows correctly between sequential and parallel operations.
3. **Resource provisioning and execution**: For each endpoint, Flash:
   - Dynamically provisions endpoint and worker resources on Runpod's infrastructure.
   - Serializes and securely transfers input data to the remote worker.
   - Executes the function on the remote infrastructure with the specified GPU or CPU resources.
   - Returns results to your local environment for further processing.
4. **Data orchestration**: Results flow seamlessly between functions according to your local Python code structure, maintaining the same programming model whether functions run locally or remotely.


## Advanced features

### Custom Docker images

Use `image=` to deploy a custom Docker image:

```python
from runpod_flash import Endpoint, GpuGroup

vllm = Endpoint(
    name="vllm-server",
    image="vllm/vllm-openai:latest",
    gpu=GpuGroup.AMPERE_80,
)
```

Image-mode endpoints are called using client methods (`.post()`, `.get()`, `.run()`, `.runsync()`). They send raw JSON payloads directly to the deployed image's HTTP API.

### Connecting to existing endpoints

Use `id=` to connect to an already-deployed Runpod endpoint:

```python
from runpod_flash import Endpoint

ep = Endpoint(id="abc123")

# queue-based calls
job = await ep.run({"prompt": "hello"})
await job.wait()
print(job.output)

# load-balanced calls
result = await ep.post("/v1/completions", {"prompt": "hello"})
```

### Persistent storage with network volumes

Attach [network volumes](https://docs.runpod.io/storage/network-volumes) for persistent storage across workers and endpoints:

```python
from runpod_flash import Endpoint, GpuGroup, NetworkVolume

vol = NetworkVolume(id="vol_abc123")

@Endpoint(name="model-server", gpu=GpuGroup.ANY, volume=vol)
async def serve(data: dict) -> dict:
    ...
```

### Environment variables

Pass configuration to remote functions:

```python
@Endpoint(
    name="api-worker",
    gpu=GpuGroup.ANY,
    env={"HF_TOKEN": "your_token", "MODEL_ID": "gpt2"},
)
async def worker(data: dict) -> dict:
    ...
```

Environment variables are excluded from configuration hashing, which means changing environment values won't trigger endpoint recreation. Only structural changes (like GPU type, image, or worker counts) trigger endpoint updates.

### Build process

Flash uses a build process to package your application for deployment.

#### How Flash builds your application

When you run `flash build`, the following happens:

1. **Discovery**: Flash scans your code for `Endpoint` definitions (both `@Endpoint(...)` decorators and `Endpoint(...)` variable assignments with route registrations)
2. **Grouping**: Endpoints are grouped by their resource configuration
3. **Manifest creation**: A `flash_manifest.json` file maps functions to their endpoints
4. **Handler generation**: Appropriate handler code is generated for each endpoint (function handlers for QB, class handlers for class-based QB)
5. **Dependency installation**: Python packages are installed with Linux x86_64 compatibility
6. **Packaging**: Everything is bundled into `artifact.tar.gz` for deployment

#### Cross-platform builds

Flash automatically handles cross-platform builds, ensuring your deployments work correctly regardless of your development platform:

- **Automatic platform targeting**: Dependencies are installed for Linux x86_64 (Runpod's serverless platform), even when building on macOS or Windows
- **Python version matching**: The build uses your current Python version to ensure package compatibility
- **Binary wheel enforcement**: Only pre-built binary wheels are used, preventing platform-specific compilation issues

This means you can build on macOS ARM64, Windows, or any other platform, and the resulting package will run correctly on Runpod serverless.

#### Cross-endpoint function calls

Flash enables functions on different endpoints to call each other. The runtime automatically discovers endpoints using the manifest and routes calls appropriately:

```python
@Endpoint(name="cpu-preprocess", cpu="cpu3c-4-8")
def preprocess(data):
    return clean_data

@Endpoint(name="gpu-inference", gpu=GpuGroup.AMPERE_80)
async def inference(data):
    # calls the CPU endpoint function
    clean = preprocess(data)
    return result
```

The runtime wrapper handles service discovery and routing automatically.

#### Build artifacts

After `flash build` completes:
- `.flash/.build/`: Temporary build directory (removed unless `--keep-build`)
- `.flash/artifact.tar.gz`: Deployment package
- `.flash/flash_manifest.json`: Service discovery configuration

#### Troubleshooting build issues

**No endpoints found:**
- Ensure your functions are decorated with `@Endpoint(...)` or that you have `Endpoint(...)` instances with registered routes
- Check that Python files are not excluded by `.gitignore` or `.flashignore`
- Verify decorator/assignment syntax

**Build succeeded but deployment failed:**
- Verify all function imports work in the deployment environment
- Check that environment variables required by your functions are available
- Review the generated `flash_manifest.json` for correct function mappings

**Dependency installation failed:**
- If a package doesn't have pre-built Linux x86_64 wheels, the build will fail with an error
- For newer Python versions (3.13+), some packages may require manylinux_2_27 or higher
- Ensure you have standard pip installed (`python -m ensurepip --upgrade`) for best compatibility
- Check PyPI to verify the package supports your Python version on Linux

#### Managing bundle size

Runpod serverless has a **500MB deployment limit**. Exceeding this limit will cause deployment failures.

Use `--exclude` to skip packages already in your worker-flash Docker image:

```bash
# for GPU deployments (PyTorch pre-installed)
flash build --exclude torch,torchvision,torchaudio
```

**Which packages to exclude depends on your endpoint config:**
- **GPU endpoints** -- PyTorch images have torch/torchvision/torchaudio pre-installed
- **CPU endpoints** -- Python slim images have NO ML frameworks pre-installed
- **Load-balanced** -- same as above, depends on GPU vs CPU variant

See [worker-flash](https://github.com/runpod-workers/worker-flash) for base image details.

## Configuration

### Endpoint parameters

All configuration is passed as parameters to the `Endpoint` class:

| Parameter | Description | Default | Example |
|-----------|-------------|---------|---------|
| `name` | Endpoint name (required unless `id=` is used) | -- | `"my-worker"` |
| `id` | Connect to existing endpoint by ID | `None` | `"abc123"` |
| `gpu` | GPU type(s) for the endpoint | `GpuGroup.ANY` | `GpuGroup.ADA_24`, `GpuType.NVIDIA_H100_80GB_HBM3` |
| `cpu` | CPU instance type (mutually exclusive with `gpu`) | `None` | `"cpu3c-4-8"`, `CpuInstanceType.CPU5C_4_16` |
| `workers` | Worker scaling: `max` or `(min, max)` | `(0, 3)` | `5`, `(1, 10)` |
| `idle_timeout` | Seconds before scaling down idle workers | `60` | `300` |
| `dependencies` | Python packages to install | `None` | `["torch", "numpy"]` |
| `system_dependencies` | System packages to install | `None` | `["ffmpeg"]` |
| `volume` | Network volume for persistent storage | `None` | `NetworkVolume(id="vol_abc")` |
| `datacenter` | Preferred datacenter | `EU_RO_1` | `DataCenter.US_TX_3` |
| `env` | Environment variables | `None` | `{"HF_TOKEN": "xyz"}` |
| `gpu_count` | GPUs per worker | `1` | `2`, `4` |
| `execution_timeout_ms` | Max execution time (ms) | `0` (no limit) | `600000` |
| `flashboot` | Enable Flashboot fast startup | `True` | `False` |
| `image` | Custom Docker image to deploy | `None` | `"vllm/vllm-openai:latest"` |
| `scaler_type` | Scaling strategy | auto | `ServerlessScalerType.QUEUE_DELAY` |
| `scaler_value` | Scaling threshold | `4` | `10` |
| `template` | Pod template overrides | `None` | `PodTemplate(containerDiskInGb=100)` |

### Available GPU types

GPU can be specified using `GpuGroup` (architecture-level) or `GpuType` (specific model):

**GpuGroup** (architecture-level, selects any GPU in the tier):
- `GpuGroup.ANY` -- any available GPU (default)
- `GpuGroup.ADA_24` -- 24GB Ada (RTX 4090)
- `GpuGroup.ADA_32_PRO` -- 32GB Ada (RTX 5090)
- `GpuGroup.ADA_48_PRO` -- 48GB Ada (L40S, L40, RTX 6000 Ada)
- `GpuGroup.ADA_80_PRO` -- 80GB Ada (RTX Pro 6000)
- `GpuGroup.AMPERE_16` -- 16GB Ampere (A4000, A4500, RTX 4000 Ada, RTX 2000 Ada)
- `GpuGroup.AMPERE_24` -- 24GB Ampere (RTX A5000, L4, RTX 3090)
- `GpuGroup.AMPERE_48` -- 48GB Ampere (A40, RTX A6000)
- `GpuGroup.AMPERE_80` -- 80GB Ampere (A100 80GB)
- `GpuGroup.HOPPER_141` -- 141GB Hopper (H200)

**GpuType** (specific models):
- `GpuType.ANY` -- any available GPU
- `GpuType.NVIDIA_RTX_A4000` -- RTX A4000 (16 GB)
- `GpuType.NVIDIA_RTX_A4500` -- RTX A4500 (16 GB)
- `GpuType.NVIDIA_RTX_2000_ADA_GENERATION` -- RTX 2000 Ada (16 GB)
- `GpuType.NVIDIA_RTX_4000_ADA_GENERATION` -- RTX 4000 Ada (16 GB)
- `GpuType.NVIDIA_GEFORCE_RTX_3090` -- RTX 3090 (24 GB)
- `GpuType.NVIDIA_GEFORCE_RTX_4090` -- RTX 4090 (24 GB)
- `GpuType.NVIDIA_L4` -- L4 (24 GB)
- `GpuType.NVIDIA_RTX_A5000` -- RTX A5000 (24 GB)
- `GpuType.NVIDIA_GEFORCE_RTX_5090` -- RTX 5090 (32 GB)
- `GpuType.NVIDIA_A40` -- A40 (48 GB)
- `GpuType.NVIDIA_RTX_A6000` -- RTX A6000 (48 GB)
- `GpuType.NVIDIA_RTX_6000_ADA_GENERATION` -- RTX 6000 Ada (48 GB)
- `GpuType.NVIDIA_A100_80GB_PCIe` -- A100 PCIe (80 GB)
- `GpuType.NVIDIA_A100_SXM4_80GB` -- A100 SXM (80 GB)
- `GpuType.NVIDIA_H100_80GB_HBM3` -- H100 (80 GB)
- `GpuType.NVIDIA_H200` -- H200 (141 GB)

### Available CPU instance types

- `"cpu3g-1-4"` -- 3rd gen general purpose, 1 vCPU, 4GB RAM
- `"cpu3g-2-8"` -- 3rd gen general purpose, 2 vCPU, 8GB RAM
- `"cpu3g-4-16"` -- 3rd gen general purpose, 4 vCPU, 16GB RAM
- `"cpu3g-8-32"` -- 3rd gen general purpose, 8 vCPU, 32GB RAM
- `"cpu3c-1-2"` -- 3rd gen compute-optimized, 1 vCPU, 2GB RAM
- `"cpu3c-2-4"` -- 3rd gen compute-optimized, 2 vCPU, 4GB RAM
- `"cpu3c-4-8"` -- 3rd gen compute-optimized, 4 vCPU, 8GB RAM
- `"cpu3c-8-16"` -- 3rd gen compute-optimized, 8 vCPU, 16GB RAM
- `"cpu5c-1-2"` -- 5th gen compute-optimized, 1 vCPU, 2GB RAM
- `"cpu5c-2-4"` -- 5th gen compute-optimized, 2 vCPU, 4GB RAM
- `"cpu5c-4-8"` -- 5th gen compute-optimized, 4 vCPU, 8GB RAM
- `"cpu5c-8-16"` -- 5th gen compute-optimized, 8 vCPU, 16GB RAM

You can also use `CpuInstanceType` enum values (e.g., `CpuInstanceType.CPU3C_4_8`).

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

### Environment variables

Flash uses the following environment variables. Values are resolved in the listed precedence order where applicable.

#### Authentication

| Variable | Description |
|----------|-------------|
| `RUNPOD_API_KEY` | Runpod API key. Takes precedence over stored credentials. |
| `RUNPOD_CREDENTIALS_FILE` | Path to a TOML credentials file. Defaults to `~/.config/runpod/credentials.toml` (or `$XDG_CONFIG_HOME/runpod/credentials.toml`). |

**Credential precedence:** `RUNPOD_API_KEY` env var > credentials file (`flash login` stores the key here) > none (error).

#### API and runtime

| Variable | Description |
|----------|-------------|
| `RUNPOD_API_BASE_URL` | Base URL for the Runpod API. |
| `RUNPOD_REST_API_URL` | Base URL for the Runpod REST API. |
| `RUNPOD_ENDPOINT_ID` | Set automatically inside deployed workers. |
| `RUNPOD_POD_ID` | Set automatically inside deployed pods. |
| `CONSOLE_BASE_URL` | Base URL for the Runpod console UI. |

#### Flash configuration

| Variable | Description |
|----------|-------------|
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Default `INFO`. |
| `FLASH_HOST` | Host for the local dev server. Default `localhost`. |
| `FLASH_PORT` | Port for the local dev server. Default `8888`. |
| `FLASH_FILE_LOGGING_ENABLED` | Enable or disable file logging (`true`/`false`). |
| `FLASH_LOG_RETENTION_DAYS` | Number of days to retain log files. Default `30`. |
| `FLASH_LOG_DIR` | Custom directory for log files. |

#### Deployment and build

| Variable | Description |
|----------|-------------|
| `FLASH_RESOURCE_NAME` | Set on deployed workers to identify the resource. |
| `FLASH_ENVIRONMENT_ID` | Flash environment ID for the current deployment. |
| `FLASH_IMAGE_TAG` | Docker image tag for deployment. |
| `FLASH_GPU_IMAGE` | Docker image for GPU workers. |
| `FLASH_CPU_IMAGE` | Docker image for CPU workers. |
| `FLASH_LB_IMAGE` | Docker image for GPU load-balanced endpoints. |
| `FLASH_CPU_LB_IMAGE` | Docker image for CPU load-balanced endpoints. |

#### Runtime features

| Variable | Description |
|----------|-------------|
| `FLASH_CIRCUIT_BREAKER_ENABLED` | Enable circuit breaker for remote calls. |
| `FLASH_LB_STRATEGY` | Load balancer routing strategy. |
| `FLASH_RETRY_ENABLED` | Enable automatic retries for failed remote calls. |

## Workflow examples

### Basic GPU workflow

```python
import asyncio
from runpod_flash import Endpoint, GpuGroup

@Endpoint(
    name="example-gpu-server",
    gpu=GpuGroup.ANY,
    dependencies=["torch", "numpy"],
)
def gpu_compute(data):
    import torch
    import numpy as np

    tensor = torch.tensor(data, device="cuda")
    result = tensor.sum().item()

    gpu_info = torch.cuda.get_device_properties(0)

    return {
        "result": result,
        "gpu_name": gpu_info.name,
        "cuda_version": torch.version.cuda,
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
from runpod_flash import Endpoint, GpuGroup, PodTemplate

@Endpoint(
    name="example_image_gen_server",
    gpu=GpuGroup.AMPERE_80,
    workers=(0, 3),
    idle_timeout=10,
    template=PodTemplate(containerDiskInGb=100),
    dependencies=["diffusers", "transformers", "torch", "accelerate", "safetensors"],
)
def generate_image(prompt, width=512, height=512):
    import torch
    from diffusers import StableDiffusionPipeline
    import io
    import base64

    pipeline = StableDiffusionPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        torch_dtype=torch.float16,
    )
    pipeline = pipeline.to("cuda")

    image = pipeline(prompt=prompt, width=width, height=height).images[0]

    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()

    return {"image": img_str, "prompt": prompt}

async def main():
    result = await generate_image("A serene mountain landscape at sunset")
    print(f"Generated image for: {result['prompt']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Basic CPU workflow

```python
import asyncio
from runpod_flash import Endpoint

@Endpoint(
    name="example-cpu-server",
    cpu="cpu5c-2-4",
    dependencies=["pandas", "numpy"],
)
def cpu_data_processing(data):
    import pandas as pd
    import numpy as np
    import platform

    df = pd.DataFrame(data)

    return {
        "row_count": len(df),
        "column_count": len(df.columns) if not df.empty else 0,
        "mean_values": df.select_dtypes(include=[np.number]).mean().to_dict(),
        "platform": platform.platform(),
    }

async def main():
    sample_data = [
        {"name": "Alice", "age": 30, "score": 85},
        {"name": "Bob", "age": 25, "score": 92},
        {"name": "Charlie", "age": 35, "score": 78},
    ]

    result = await cpu_data_processing(sample_data)
    print(f"Processed {result['row_count']} rows on {result['platform']}")
    print(f"Mean values: {result['mean_values']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Hybrid GPU/CPU workflow

```python
import asyncio
from runpod_flash import Endpoint, GpuGroup, PodTemplate

@Endpoint(
    name="data-preprocessor",
    cpu="cpu5c-4-8",
    workers=(0, 3),
    dependencies=["pandas", "numpy", "scikit-learn"],
)
def preprocess_data(raw_data):
    import pandas as pd
    import numpy as np
    from sklearn.preprocessing import StandardScaler

    df = pd.DataFrame(raw_data)
    df = df.fillna(df.mean(numeric_only=True))

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        scaler = StandardScaler()
        df[numeric_cols] = scaler.fit_transform(df[numeric_cols])

    return {
        "processed_data": df.to_dict("records"),
        "shape": df.shape,
        "columns": list(df.columns),
    }

@Endpoint(
    name="ml-inference-gpu",
    gpu=GpuGroup.AMPERE_24,
    workers=(0, 2),
    template=PodTemplate(containerDiskInGb=50),
    dependencies=["torch", "numpy"],
)
def run_inference(processed_data):
    import torch
    import numpy as np

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    data_array = np.array(
        [list(item.values()) for item in processed_data["processed_data"]]
    )
    tensor = torch.tensor(data_array, dtype=torch.float32).to(device)

    with torch.no_grad():
        result = torch.nn.functional.softmax(tensor.mean(dim=1), dim=0)
        predictions = result.cpu().numpy().tolist()

    return {
        "predictions": predictions,
        "device_used": str(device),
        "input_shape": list(tensor.shape),
    }

async def ml_pipeline(raw_dataset):
    """complete ML pipeline: CPU preprocessing -> GPU inference"""
    print("Step 1: Preprocessing data on CPU...")
    preprocessed = await preprocess_data(raw_dataset)
    print(f"Preprocessed data shape: {preprocessed['shape']}")

    print("Step 2: Running inference on GPU...")
    results = await run_inference(preprocessed)
    print(f"Inference completed on: {results['device_used']}")

    return {
        "preprocessing": preprocessed,
        "inference": results,
    }

async def main():
    import numpy as np

    raw_data = [
        {
            "feature1": np.random.randn(),
            "feature2": np.random.randn(),
            "feature3": np.random.randn(),
            "label": i % 2,
        }
        for i in range(100)
    ]

    results = await ml_pipeline(raw_data)

    print(f"\nPipeline Results:")
    print(f"Data processed: {results['preprocessing']['shape']}")
    print(f"Predictions generated: {len(results['inference']['predictions'])}")
    print(f"GPU device: {results['inference']['device_used']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Load-balanced API endpoint

```python
from runpod_flash import Endpoint, GpuGroup

api = Endpoint(name="inference-api", gpu=GpuGroup.ADA_24, workers=(1, 5))

@api.post("/predict")
async def predict(data: dict) -> dict:
    import torch

    model = torch.load("/models/model.pt")
    return {"prediction": model.predict(data)}

@api.get("/health")
async def health():
    return {"status": "ok", "gpu": "available"}
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
- **REST APIs and microservices**: Deploy low-latency HTTP APIs with load-balanced endpoints.

## Limitations

- Serverless deployments using Flash are currently restricted to the `EU-RO-1` datacenter.
- Flash requires Python 3.10 or higher.
- While Flash supports deploying custom Docker images via `image=`, these endpoints receive raw JSON payloads and do not support Flash's remote code execution protocol.
- As you work through the Flash examples repository, you'll accumulate multiple endpoints in your Runpod account. These endpoints persist until manually deleted through the Runpod console or via `flash undeploy`. Regular cleanup of unused endpoints is recommended to avoid unnecessary charges.
- Be aware of your account's maximum worker capacity limits. Flash can rapidly scale workers across multiple endpoints, and you may hit capacity constraints faster than with traditional deployment patterns. If you find yourself consistently reaching worker limits, contact Runpod support to increase your account's capacity allocation.

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

Or use `flash login` to store credentials:

```bash
flash login
```

### Import errors in remote functions

Remember to import packages inside remote functions:

```python
@Endpoint(name="fetcher", cpu="cpu3c-1-2", dependencies=["requests"])
def fetch_data(url):
    import requests  # import here, not at top of file
    return requests.get(url).json()
```

### Performance optimization

- Set `workers=(1, N)` to keep workers warm and avoid cold starts.
- Use `idle_timeout` to balance cost and responsiveness.
- Choose appropriate GPU types for your workload.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

<p align="center">
  <a href="https://github.com/runpod/runpod-flash">Flash</a> •
  <a href="https://runpod.io">Runpod</a>
</p>
