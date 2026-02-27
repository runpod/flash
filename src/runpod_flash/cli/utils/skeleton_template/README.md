# {{project_name}}

Runpod Flash application with GPU and CPU workers on Runpod serverless infrastructure.

## Quick Start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended Python package manager):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Set up the project:

```bash
uv venv && source .venv/bin/activate
uv sync
cp .env.example .env   # Add your RUNPOD_API_KEY
flash run
```

Or with pip:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Add your RUNPOD_API_KEY
flash run
```

Server starts at **http://localhost:8888**. Visit **http://localhost:8888/docs** for interactive Swagger UI.

Use `flash run --auto-provision` to pre-deploy all endpoints on startup, eliminating cold-start delays on first request. Provisioned endpoints are cached and reused across restarts.

When you stop the server with Ctrl+C, all endpoints provisioned during the session are automatically cleaned up.

Get your API key from [Runpod Settings](https://www.runpod.io/console/user/settings).
Learn more about it from our [Documentation](https://docs.runpod.io/get-started/api-keys).

## Test the API

```bash
# Queue-based GPU worker
curl -X POST http://localhost:8888/gpu_worker/runsync \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello GPU!"}'

# Queue-based CPU worker
curl -X POST http://localhost:8888/cpu_worker/runsync \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello CPU!"}'

# Load-balanced HTTP endpoint
curl -X POST http://localhost:8888/lb_worker/process \
  -H "Content-Type: application/json" \
  -d '{"input": "test"}'

# Load-balanced health check
curl http://localhost:8888/lb_worker/health
```

## Project Structure

```
{{project_name}}/
├── gpu_worker.py      # GPU serverless worker (queue-based)
├── cpu_worker.py      # CPU serverless worker (queue-based)
├── lb_worker.py       # CPU load-balanced HTTP endpoint
├── .env.example       # Environment variable template
├── requirements.txt   # Python dependencies
└── README.md
```

## Worker Types

### Queue-Based (QB) Workers

QB workers process jobs from a queue. Each call to `/runsync` sends a job and waits
for the result. Use QB for compute-heavy tasks that may take seconds to minutes.

**gpu_worker.py** — GPU serverless function:

```python
from runpod_flash import GpuType, LiveServerless, remote

gpu_config = LiveServerless(
    name="gpu_worker",
    gpus=[GpuType.ANY],
)

@remote(resource_config=gpu_config, dependencies=["torch"])
async def gpu_hello(input_data: dict) -> dict:
    import torch
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else "No GPU detected"
    return {"message": gpu_name}
```

**cpu_worker.py** — CPU serverless function:

```python
from runpod_flash import CpuLiveServerless, remote

cpu_config = CpuLiveServerless(name="cpu_worker")

@remote(resource_config=cpu_config)
async def cpu_hello(input_data: dict = {}) -> dict:
    return {"message": "Hello from CPU!", **input_data}
```

### Load-Balanced (LB) Workers

LB workers expose standard HTTP endpoints (GET, POST, etc.) behind a load balancer.
Use LB for low-latency API endpoints that need horizontal scaling.

**lb_worker.py** — HTTP endpoints on a load-balanced container:

```python
from runpod_flash import CpuLiveLoadBalancer, remote

api_config = CpuLiveLoadBalancer(
    name="lb_worker",
    workersMin=1,
)

@remote(resource_config=api_config, method="POST", path="/process")
async def process(input_data: dict) -> dict:
    return {"status": "success", "echo": input_data}

@remote(resource_config=api_config, method="GET", path="/health")
async def health() -> dict:
    return {"status": "healthy"}
```

## Adding New Workers

Create a new `.py` file with a `@remote` function. `flash run` auto-discovers all
`@remote` functions in the project.

```python
# my_worker.py
from runpod_flash import LiveServerless, GpuType, remote

config = LiveServerless(name="my_worker", gpus=[GpuType.GEFORCE_RTX_4090])

@remote(resource_config=config, dependencies=["transformers"])
async def predict(input_data: dict) -> dict:
    from transformers import pipeline
    pipe = pipeline("sentiment-analysis")
    return pipe(input_data["text"])[0]
```

Then run `flash run` — the new worker appears automatically.

## GPU Types

| Config                            | Hardware          | VRAM   |
| --------------------------------- | ----------------- | ------ |
| `GpuType.ANY`                     | Any available GPU | varies |
| `GpuType.GEFORCE_RTX_4090`        | RTX 4090          | 24 GB  |
| `GpuType.GEFORCE_RTX_5090`        | RTX 5090          | 32 GB  |
| `GpuType.RTX_6000_ADA_GENERATION` | RTX 6000 Ada      | 48 GB  |
| `GpuType.L4`                      | L4                | 24 GB  |
| `GpuType.A100_80GB_PCIe`          | A100 PCIe         | 80 GB  |
| `GpuType.A100_SXM4_80GB`          | A100 SXM4         | 80 GB  |
| `GpuType.H100_80GB_HBM3`          | H100              | 80 GB  |
| `GpuType.H200`                    | H200              | 141 GB |

## CPU Types

| Config                       | vCPU | RAM   |
| ---------------------------- | ---- | ----- |
| `CpuInstanceType.CPU3G_2_8`  | 2    | 8 GB  |
| `CpuInstanceType.CPU3C_4_8`  | 4    | 8 GB  |
| `CpuInstanceType.CPU5G_4_16` | 4    | 16 GB |

## Environment Variables

```bash
# Required
RUNPOD_API_KEY=your_api_key

# Optional
FLASH_HOST=localhost   # Server host (default: localhost)
FLASH_PORT=8888        # Server port (default: 8888)
LOG_LEVEL=INFO         # Logging level (default: INFO)
```

## Deploy

```bash
flash deploy
```
