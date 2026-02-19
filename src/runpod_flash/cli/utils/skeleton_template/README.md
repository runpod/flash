# {{project_name}}

Flash application demonstrating distributed GPU and CPU computing on Runpod's serverless infrastructure.

## About This Template

This project was generated using `flash init`. The `{{project_name}}` placeholder is automatically replaced with your actual project name during initialization.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create `.env` file:

```bash
RUNPOD_API_KEY=your_api_key_here
```

Get your API key from [Runpod Settings](https://www.runpod.io/console/user/settings).

### 3. Run Locally

```bash
# Standard run
flash run

# Faster development: pre-provision endpoints (eliminates cold-start delays)
flash run --auto-provision
```

Server starts at **http://localhost:8000**

With `--auto-provision`, all serverless endpoints deploy before testing begins. This is much faster for development because endpoints are cached and reused across server restarts. Subsequent runs skip deployment and start immediately.

### 4. Test the API

```bash
# Health check
curl http://localhost:8000/ping

# GPU worker
curl -X POST http://localhost:8000/gpu/hello \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello GPU!"}'

# CPU worker
curl -X POST http://localhost:8000/cpu/hello \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello CPU!"}'
```

Visit **http://localhost:8000/docs** for interactive API documentation.

## What This Demonstrates

### GPU Worker (`workers/gpu/`)
Simple GPU-based serverless function:
- Remote execution with `@remote` decorator
- GPU resource configuration
- Automatic scaling (0-3 workers)
- No external dependencies required

```python
@remote(
    resource_config=LiveServerless(
        name="gpu_worker",
        gpus=[GpuGroup.ADA_24],  # RTX 4090
        workersMin=0,
        workersMax=3,
    )
)
async def gpu_hello(input_data: dict) -> dict:
    # Your GPU code here
    return {"status": "success", "message": "Hello from GPU!"}
```

### CPU Worker (`workers/cpu/`)
Simple CPU-based serverless function:
- CPU-only execution (no GPU overhead)
- CpuLiveServerless configuration
- Efficient for API endpoints
- Automatic scaling (0-5 workers)

```python
@remote(
    resource_config=CpuLiveServerless(
        name="cpu_worker",
        instanceIds=[CpuInstanceType.CPU3G_2_8],  # 2 vCPU, 8GB RAM
        workersMin=0,
        workersMax=5,
    )
)
async def cpu_hello(input_data: dict) -> dict:
    # Your CPU code here
    return {"status": "success", "message": "Hello from CPU!"}
```

## Project Structure

```
{{project_name}}/
├── main.py                    # FastAPI application
├── workers/
│   ├── gpu/                  # GPU worker
│   │   ├── __init__.py       # FastAPI router
│   │   └── endpoint.py       # @remote decorated function
│   └── cpu/                  # CPU worker
│       ├── __init__.py       # FastAPI router
│       └── endpoint.py       # @remote decorated function
├── .env                      # Environment variables
├── requirements.txt          # Dependencies
└── README.md                 # This file
```

## Key Concepts

### Remote Execution
The `@remote` decorator transparently executes functions on serverless infrastructure:
- Code runs locally during development
- Automatically deploys to Runpod when configured
- Handles serialization, dependencies, and resource management

### Resource Scaling
Both workers scale to zero when idle to minimize costs:
- **idleTimeout**: Seconds before scaling down (default: 60)
- **workersMin**: 0 = completely scales to zero
- **workersMax**: Maximum concurrent workers

### GPU Types
Available GPU options for `LiveServerless`:
- `GpuGroup.ADA_24` - RTX 4090 (24GB)
- `GpuGroup.ADA_48_PRO` - RTX 6000 Ada, L40 (48GB)
- `GpuGroup.AMPERE_80` - A100 (80GB)
- `GpuGroup.ANY` - Any available GPU

### CPU Types
Available CPU options for `CpuLiveServerless`:
- `CpuInstanceType.CPU3G_2_8` - 2 vCPU, 8GB RAM (General Purpose)
- `CpuInstanceType.CPU3C_4_8` - 4 vCPU, 8GB RAM (Compute Optimized)
- `CpuInstanceType.CPU5G_4_16` - 4 vCPU, 16GB RAM (Latest Gen)
- `CpuInstanceType.ANY` - Any available GPU

## Development Workflow

### Test Workers Locally
```bash
# Test GPU worker
python -m workers.gpu.endpoint

# Test CPU worker
python -m workers.cpu.endpoint
```

### Run the Application
```bash
flash run
```

### Deploy to Production
```bash
# Build and deploy in one step
flash deploy

# Or deploy to a specific environment
flash deploy --env production
```

## Adding New Workers

### Add a GPU Worker

1. Create `workers/my_worker/endpoint.py`:
```python
from runpod_flash import remote, LiveServerless

config = LiveServerless(name="my_worker")

@remote(resource_config=config, dependencies=["torch"])
async def my_function(data: dict) -> dict:
    import torch
    # Your code here
    return {"result": "success"}
```

2. Create `workers/my_worker/__init__.py`:
```python
from fastapi import APIRouter
from .endpoint import my_function

router = APIRouter()

@router.post("/process")
async def handler(data: dict):
    return await my_function(data)
```

3. Add to `main.py`:
```python
from workers.my_worker import router as my_router
app.include_router(my_router, prefix="/my_worker")
```

### Add a CPU Worker

Same pattern but use `CpuLiveServerless`:
```python
from runpod_flash import remote, CpuLiveServerless, CpuInstanceType

config = CpuLiveServerless(
    name="my_cpu_worker",
    instanceIds=[CpuInstanceType.CPU3G_2_8]
)

@remote(resource_config=config, dependencies=["requests"])
async def fetch_data(url: str) -> dict:
    import requests
    return requests.get(url).json()
```

## Adding Dependencies

Specify dependencies in the `@remote` decorator:
```python
@remote(
    resource_config=config,
    dependencies=["torch>=2.0.0", "transformers"],  # Python packages
    system_dependencies=["ffmpeg"]  # System packages
)
async def my_function(data: dict) -> dict:
    # Dependencies are automatically installed
    import torch
    import transformers
```

## Environment Variables

```bash
# Required
RUNPOD_API_KEY=your_api_key

# Optional
FLASH_HOST=localhost  # Host to bind the server to (default: localhost)
FLASH_PORT=8888       # Port to bind the server to (default: 8888)
LOG_LEVEL=INFO        # Logging level (default: INFO)
```

## Next Steps

- Add your ML models or processing logic
- Configure GPU/CPU resources based on your needs
- Add authentication to your endpoints
- Implement error handling and retries
- Add monitoring and logging
- Deploy to production with `flash deploy`
