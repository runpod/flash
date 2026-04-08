# Flash Deploy Guide

## Overview

This guide walks through deploying a Flash application from local development to production. It covers the full lifecycle: project setup, local testing, building, deploying, and managing endpoints.

## Prerequisites

- Python 3.10+
- `pip install runpod-flash`
- A Runpod account with API key ([get one here](https://docs.runpod.io/get-started/api-keys))

## Quick Start

```bash
# create project
flash init my-project
cd my-project

# authenticate
flash login

# test locally
flash run

# deploy
flash deploy --env production
```

## Step-by-Step Walkthrough

### 1. Create Your Endpoints

**Queue-based (QB)** -- one function per endpoint:

```python
# gpu_worker.py
from runpod_flash import Endpoint, GpuGroup

@Endpoint(
    name="gpu-worker",
    gpu=GpuGroup.AMPERE_80,
    workers=(0, 5),
    dependencies=["torch", "transformers"],
)
async def predict(data: dict) -> dict:
    import torch
    from transformers import pipeline
    pipe = pipeline("text-generation", device="cuda")
    return pipe(data["prompt"])[0]
```

**Class-based QB** -- singleton instance, multiple methods:

```python
# model_server.py
from runpod_flash import Endpoint, GpuGroup

@Endpoint(
    name="model-server",
    gpu=GpuGroup.AMPERE_80,
    dependencies=["torch", "transformers"],
)
class ModelServer:
    def __init__(self):
        import torch
        from transformers import pipeline
        self.pipe = pipeline("text-generation", device="cuda")

    def predict(self, prompt: str) -> dict:
        return self.pipe(prompt)[0]

    def embed(self, text: str) -> dict:
        # embedding logic
        return {"embedding": [0.1, 0.2, 0.3]}
```

For single-method classes, input is passed directly to the method. For multi-method classes, include a `"method"` key in the input to select which method to call:

```json
{"input": {"method": "predict", "prompt": "Hello world"}}
{"input": {"method": "embed", "text": "Hello world"}}
```

**Load-balanced (LB)** -- multiple HTTP routes, shared workers:

```python
# api.py
from runpod_flash import Endpoint, GpuGroup

api = Endpoint(name="api-gateway", cpu="cpu3c-4-8", workers=(1, 5))

@api.post("/predict")
async def predict(data: dict) -> dict:
    return {"result": data}

@api.get("/health")
async def health():
    return {"status": "ok"}
```

**CPU endpoint**:

```python
# data_worker.py
from runpod_flash import Endpoint

@Endpoint(name="data-worker", cpu="cpu3c-4-8", dependencies=["pandas"])
async def process(data: dict) -> dict:
    import pandas as pd
    df = pd.DataFrame(data["records"])
    return {"summary": df.describe().to_dict()}
```

### 2. Test Locally

```bash
flash run
```

This starts a local dev server at `http://localhost:8888` with auto-reload:

- QB endpoints are available at `/{file_prefix}/runsync`
- LB routes are available at `/{endpoint_name}/{path}`

Test with curl:

```bash
# QB endpoint
curl -X POST http://localhost:8888/gpu_worker/runsync \
    -H "Content-Type: application/json" \
    -d '{"input": {"prompt": "Hello world"}}'

# LB endpoint
curl -X POST http://localhost:8888/api-gateway/predict \
    -H "Content-Type: application/json" \
    -d '{"data": {"key": "value"}}'

# LB health check
curl http://localhost:8888/api-gateway/health
```

Visit `http://localhost:8888/docs` for the interactive Swagger UI.

### 3. Build

```bash
flash build
```

This creates `.flash/artifact.tar.gz` with your code, dependencies, manifest, and generated handlers.

**Reduce bundle size** by excluding packages already in the base image:

```bash
# GPU endpoints have PyTorch pre-installed
flash build --exclude torch,torchvision,torchaudio
```

**Inspect the build** to verify:

```bash
flash build --keep-build
cat .flash/flash_manifest.json | python -m json.tool
ls .flash/.build/
```

### 4. Deploy

```bash
# deploy to production (creates environment if needed)
flash deploy --env production

# deploy to staging
flash deploy --env staging
```

`flash deploy` runs the build, uploads the artifact, and provisions all endpoints.

### 5. Call Your Endpoints

**QB endpoints** (via Runpod API):

```bash
curl -X POST "https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"input": {"prompt": "Hello world"}}'
```

**LB endpoints** (direct HTTP):

```bash
curl -X POST "https://{ENDPOINT_ID}.api.runpod.ai/predict" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"data": {"key": "value"}}'
```

**Using Endpoint(id=...)** as a client:

```python
from runpod_flash import Endpoint

# QB client
ep = Endpoint(id="your-endpoint-id")
job = await ep.run({"prompt": "hello"})
await job.wait()
print(job.output)

# LB client
ep = Endpoint(id="your-lb-endpoint-id")
result = await ep.post("/predict", {"data": {"key": "value"}})
```

### 6. Manage Endpoints

```bash
# list environments
flash env list

# check environment status
flash env get production

# undeploy specific endpoint
flash undeploy gpu-worker

# undeploy all endpoints (interactive)
flash undeploy --interactive

# delete entire environment
flash env delete staging
```

## Deployment Patterns

### Multi-Environment Workflow

```bash
# development
flash deploy --env dev

# staging (after testing)
flash deploy --env staging

# production (after QA)
flash deploy --env production
```

### GPU + CPU Pipeline

```python
# cpu_preprocess.py
from runpod_flash import Endpoint

@Endpoint(name="preprocess", cpu="cpu3c-4-8")
def preprocess(data: dict) -> dict:
    return {"cleaned": data}

# gpu_inference.py
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="inference", gpu=GpuGroup.AMPERE_80, dependencies=["torch"])
async def infer(data: dict) -> dict:
    # cross-endpoint call: routes to preprocess endpoint automatically
    clean = preprocess(data)
    return {"prediction": 42}
```

See [Cross-Endpoint Routing](Cross_Endpoint_Routing.md) for details on how cross-endpoint calls work.

### Custom Docker Image

```python
from runpod_flash import Endpoint, GpuGroup

# deploy a pre-built image
vllm = Endpoint(
    name="vllm-server",
    image="vllm/vllm-openai:latest",
    gpu=GpuGroup.AMPERE_80,
    workers=(1, 3),
)

# call it as a client
result = await vllm.post("/v1/completions", {"prompt": "hello"})
```

### Persistent Storage

```python
from runpod_flash import Endpoint, GpuGroup, DataCenter, NetworkVolume, PodTemplate

vol = NetworkVolume(name="model-cache", size=100, datacenter=DataCenter.US_GA_1)

@Endpoint(
    name="model-server",
    gpu=GpuGroup.AMPERE_80,
    datacenter=DataCenter.US_GA_2,
    volume=vol,
    template=PodTemplate(containerDiskInGb=100),
)
async def serve(data: dict) -> dict:
    # models cached on network volume survive worker restarts
    ...
```

Multiple volumes across datacenters:

```python
volumes = [
    NetworkVolume(name="models-us", size=100, datacenter=DataCenter.US_GA_1),
    NetworkVolume(name="models-eu", size=100, datacenter=DataCenter.EU_RO_1),
]

@Endpoint(
    name="global-server",
    gpu=GpuGroup.AMPERE_80,
    datacenter=[DataCenter.US_GA_1, DataCenter.EU_RO_1],
    volume=volumes,
)
async def serve(data: dict) -> dict:
    ...
```

Network volume lifecycle:
- If `id` is provided, deploy attaches that existing volume.
- If `name` is provided, deploy reuses an existing `(name, dataCenterId)` volume or creates one.
- Volumes persist independently; deletion is manual (`NetworkVolume.undeploy()` is not supported).

## Troubleshooting

### Build Issues

**"No endpoints found"**
- Ensure your files have `@Endpoint(...)` decorators or `Endpoint(...)` variable assignments with routes
- Check `.flashignore` and `.gitignore` aren't excluding your files

**"Dependency installation failed"**
- Some packages don't have Linux x86_64 wheels. Check PyPI for wheel availability.
- Use `--exclude` for packages in the base image

**"Archive too large (>500MB)"**
- Use `--exclude` to skip packages in the base image: `flash build --exclude torch,torchvision,torchaudio`

### Deployment Issues

**"Endpoint not ready"**
- Workers take 30-60s to cold start. Set `workers=(1, N)` to keep workers warm.
- Check endpoint logs in the Runpod console.

**"401 Unauthorized"**
- Verify API key: `flash login` or check `echo $RUNPOD_API_KEY`

**"Config drift detected"**
- This is normal. Flash auto-updates endpoints when configuration changes.
- See [Resource Config Drift Detection](Resource_Config_Drift_Detection.md).

### Runtime Issues

**"Function not found in manifest"**
- The called function must be in a file scanned by `flash build`
- Check the manifest: `cat .flash/flash_manifest.json`

**"Timeout"**
- Increase `execution_timeout_ms` on the endpoint
- Check for cold start delays

## Related Documentation

- [Flash SDK Reference](Flash_SDK_Reference.md) -- complete API reference
- [Deployment Architecture](Deployment_Architecture.md) -- build and deploy internals
- [Cross-Endpoint Routing](Cross_Endpoint_Routing.md) -- how endpoints call each other
- [Resource Config Drift Detection](Resource_Config_Drift_Detection.md) -- drift detection
- [Load-Balanced Endpoints](Using_Remote_With_LoadBalancer.md) -- LB endpoint guide
- [LoadBalancer Runtime Architecture](LoadBalancer_Runtime_Architecture.md) -- LB runtime details
