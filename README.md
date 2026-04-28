# Flash

Flash is a Python SDK for developing cloud-native AI apps where you define everything -- hardware, remote functions, and dependencies -- using local code.

```python
import asyncio
from runpod_flash import Endpoint, GpuType

@Endpoint(name="hello-gpu", gpu=GpuType.NVIDIA_GEFORCE_RTX_4090, dependencies=["torch"])
async def hello():
    import torch
    gpu_name = torch.cuda.get_device_name(0)
    print(f"Hello from your GPU! ({gpu_name})")
    return {"gpu": gpu_name}

asyncio.run(hello())
print("Done!")
```

Write `@Endpoint` decorated Python functions on your local machine. Deploy them with `flash deploy`, then call them by running the same script. Flash handles GPU/CPU provisioning and worker scaling on [RunPod Serverless](https://docs.runpod.io/serverless/overview).

## Setup

### Install Flash

```bash
pip install runpod-flash
# or
uv add runpod-flash
```

Flash requires [Python 3.10+](https://www.python.org/downloads/) on macOS or Linux. Windows support is in development.

### Authentication

```bash
flash login
```

This saves your API key and allows you to use the Flash CLI and call `@Endpoint` functions.

### Coding agent integration (optional)

```bash
npx skills add runpod/skills
```

You can review the `SKILL.md` file in the [runpod/skills repository](https://github.com/runpod/skills/blob/main/flash/SKILL.md).

## Quickstart

Create `gpu_demo.py`:

```python
import asyncio
from runpod_flash import Endpoint, GpuType

@Endpoint(
    name="flash-quickstart",
    gpu=GpuType.NVIDIA_GEFORCE_RTX_4090,
    workers=3,
    dependencies=["numpy", "torch"]
)
def gpu_matrix_multiply(size):
    import numpy as np
    import torch

    device_name = torch.cuda.get_device_name(0)
    A = np.random.rand(size, size)
    B = np.random.rand(size, size)
    C = np.dot(A, B)

    return {
        "matrix_size": size,
        "result_mean": float(np.mean(C)),
        "gpu": device_name
    }

async def main():
    print("Running matrix multiplication on RunPod GPU...")
    result = await gpu_matrix_multiply(1000)
    print(f"Matrix size: {result['matrix_size']}x{result['matrix_size']}")
    print(f"Result mean: {result['result_mean']:.4f}")
    print(f"GPU used: {result['gpu']}")

if __name__ == "__main__":
    asyncio.run(main())
```

Deploy, then run:

```bash
flash deploy
python gpu_demo.py
```

## How it works

Flash has two modes: **deploy** and **dev**.

### Deploy and run (`flash deploy` + `python script.py`)

Deploy packages your code and provisions endpoints on RunPod. After deploying, run your script directly and Flash routes calls to your deployed endpoints via implicit resolution:

```bash
flash deploy                 # build, upload, provision endpoints
python gpu_demo.py           # calls deployed endpoints automatically
```

Flash resolves endpoints by matching the app name (defaults to the current directory name) and environment (defaults to `production`). Configure with env vars or `.env`:

```bash
FLASH_APP=my-project         # defaults to current directory name
FLASH_ENV=staging            # defaults to "production"
```

### Dev mode (`flash dev`)

For local development and testing, `flash dev` starts a hybrid dev server that runs your FastAPI app locally while provisioning live ephemeral workers on RunPod:

```bash
flash dev                    # starts local server + provisions workers
flash dev --port 3000        # custom port
flash dev --auto-provision   # provision all endpoints at startup
```

## What Flash does

- **Remote execution**: `@Endpoint` functions run on RunPod Serverless GPUs/CPUs
- **Implicit endpoint resolution**: `python script.py` routes to deployed endpoints automatically
- **Auto-scaling**: workers scale from 0 to N based on demand
- **Dependency management**: packages install automatically on remote workers
- **Two patterns**: queue-based (`@Endpoint`) for batch work, load-balanced (`Endpoint()` + routes) for REST APIs
- **Concurrency control**: `max_concurrency` lets each worker process multiple jobs simultaneously

## Documentation

Full documentation: **[docs.runpod.io/flash](https://docs.runpod.io/flash)**

- [Quickstart](https://docs.runpod.io/flash/quickstart) - First GPU workload in 5 minutes
- [Create endpoints](https://docs.runpod.io/flash/endpoint-functions) - Queue-based, load-balancing, and custom Docker endpoints
- [CLI reference](https://docs.runpod.io/flash/cli/overview) - `flash dev`, `flash deploy`, `flash build`
- [Configuration](https://docs.runpod.io/flash/configuration/parameters) - All endpoint parameters

## Flash apps

When you're ready to move beyond scripts and build a production-ready API, you can create a [Flash app](https://docs.runpod.io/flash/apps/overview) (a collection of interconnected endpoints with diverse hardware configurations) and deploy it to RunPod.

[Follow this tutorial to build your first Flash app](https://docs.runpod.io/flash/apps/build-app).

## Flash CLI

```bash
flash --help
```

[Learn more about the Flash CLI](https://docs.runpod.io/flash/cli/overview).

## Examples

Browse working examples: **[github.com/runpod/flash-examples](https://github.com/runpod/flash-examples)**

## Requirements

- Python 3.10-3.12
- macOS or Linux (Windows support in development)
- A [RunPod account](https://runpod.io/console) (email must be verified) with an API key

## Contributing

We welcome contributions! See [RELEASE_SYSTEM.md](RELEASE_SYSTEM.md) for development workflow.

```bash
git clone https://github.com/runpod/flash.git
cd flash
pip install -e ".[dev]"

# use conventional commits
git commit -m "feat: add new feature"
git commit -m "fix: resolve issue"
```

## Support

- [Discord](https://discord.gg/cUpRmau42V) - Community support
- [GitHub Issues](https://github.com/runpod/flash/issues) - Bug reports

## License

MIT License - see [LICENSE](LICENSE) for details.
