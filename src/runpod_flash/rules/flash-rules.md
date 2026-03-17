<!-- flash-rules-version: 1.9.1 -->

# Flash Rules for AI Coding Agents

## Identity

Flash is a Python SDK for deploying AI workloads to Runpod GPUs. You write decorated Python functions, Flash handles infrastructure, scaling, and deployment.

## Three Patterns

### Pattern A: Queue-based function endpoint

```python
from runpod_flash import Endpoint, GpuType

@Endpoint(
    name="my-gpu-worker",
    gpu=GpuType.NVIDIA_GEFORCE_RTX_4090,
    workers=(0, 3),
    dependencies=["torch"],
)
async def process(input_data: dict) -> dict:
    import torch
    return {"gpu": torch.cuda.get_device_name(0)}
```

### Pattern B: Load-balanced routes

```python
from runpod_flash import Endpoint

api = Endpoint(name="my-api", cpu="cpu3c-1-2", workers=(1, 3))

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/compute")
async def compute(numbers: list[float]) -> dict:
    return {"sum": sum(numbers)}
```

### Pattern C: Class-based worker (stateful)

```python
from runpod_flash import Endpoint, GpuType

@Endpoint(
    name="my-model",
    gpu=GpuType.NVIDIA_GEFORCE_RTX_4090,
    workers=(1, 3),
    dependencies=["torch", "transformers"],
)
class MyModel:
    def __init__(self):
        import torch
        from transformers import pipeline
        self.pipe = pipeline("text-generation", device="cuda")

    async def generate(self, prompt: str) -> dict:
        return {"text": self.pipe(prompt)[0]["generated_text"]}
```

## Rules That Break If Violated

- `import torch` and heavy libraries INSIDE the function body, never at module level
- Declare runtime dependencies in `@Endpoint(dependencies=[...])`, not in `pyproject.toml`
- Endpoint functions can be sync (`def`) or async (`async def`). Use async when awaiting other endpoints or async I/O
- `workers=N` for fixed count, `workers=(min, max)` for auto-scaling range
- Class workers: model loading in `__init__`, request handling in instance methods
- Cross-worker calls use `await` — call `@Endpoint`-decorated functions as if local; Flash handles remote dispatch
- System-level packages (ffmpeg, libgl1) go in `system_dependencies`, not `dependencies`
- `@Endpoint` is the canonical decorator. `@remote` is the legacy alias

## Configuration Reference

| GPU | VRAM | Use Case |
|-----|------|----------|
| `GpuType.NVIDIA_GEFORCE_RTX_4090` | 24GB | General inference |
| `GpuType.NVIDIA_RTX_6000_ADA_GENERATION` | 48GB | Large models |
| `GpuType.NVIDIA_A100_80GB_PCIe` | 80GB | Training/large batch |
| `GpuGroup.ADA_24` | 24GB | Any Ada 24GB GPU |

CPU types: `CpuInstanceType.CPU3C_1_2` (1 vCPU, 2GB), `CpuInstanceType.CPU3C_8_16` (8 vCPU, 16GB)

## CLI Cheatsheet

```
flash init <name>       # scaffold project
flash run               # local dev server at localhost:8888
flash build             # package for deployment
flash deploy            # build + deploy to Runpod
flash deploy --preview  # local multi-container test
flash rules             # regenerate agent context files
```

## Common Agent Mistakes

| Mistake | Fix |
|---------|-----|
| Writing raw FastAPI instead of `@Endpoint` | Use `@Endpoint` decorator, Flash generates FastAPI |
| `import torch` at top of file | Move inside function body |
| Adding deps to `pyproject.toml` only | Add to `@Endpoint(dependencies=[...])` |
| Forcing `async def` on all endpoints | Both sync and async are valid; use async only when awaiting |
| Creating `main.py` or `app.py` | Not needed — Flash auto-discovers decorated functions |
| Using `docker-compose` manually | Use `flash deploy --preview` for local container testing |
