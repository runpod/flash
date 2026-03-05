# Flash

Flash is a Python SDK for developing cloud-native AI apps where you define everything—hardware, remote functions, and dependencies—using local code.

```python
import asyncio
from runpod_flash import Endpoint, GpuType

# Mark the function below for remote execution
@Endpoint(name="hello-gpu", gpu=GpuType.NVIDIA_GEFORCE_RTX_4090, dependencies=["torch"]) 
async def hello(): # This function runs on Runpod
    import torch
    gpu_name = torch.cuda.get_device_name(0)
    print(f"Hello from your GPU! ({gpu_name})")
    return {"gpu": gpu_name}

asyncio.run(hello())
print("Done!") # This runs locally
```

Write `@Endpoint` decorated Python functions on your local machine. Run them, and Flash automatically handles GPU/CPU provisioning and worker scaling on [Runpod Serverless](https://docs.runpod.io/serverless/overview).

## Setup

### Install Flash

Install Flash using `pip` or `uv`:

```bash
# Install with pip
pip install runpod-flash

# Or uv
uv add runpod-flash
```

Flash requires [Python 3.10+](https://www.python.org/downloads/), and is currently available for macOS and Linux. Windows support is in development.

### Authentication

Before you can use Flash, you need to authenticate with your Runpod account:

```bash
flash login
```

This saves your API key securely and allows you to use the Flash CLI and run `@Endpoint` functions.

### Coding agent integration (optional)

Install the Flash skill package for AI coding agents like Claude Code, Cline, and Cursor:

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
    # IMPORTANT: Import packages INSIDE the function
    import numpy as np
    import torch

    # Get GPU name
    device_name = torch.cuda.get_device_name(0)

    # Create random matrices
    A = np.random.rand(size, size)
    B = np.random.rand(size, size)

    # Multiply matrices
    C = np.dot(A, B)

    return {
        "matrix_size": size,
        "result_mean": float(np.mean(C)),
        "gpu": device_name
    }

# Call the function
async def main():
    print("Running matrix multiplication on Runpod GPU...")
    result = await gpu_matrix_multiply(1000)

    print(f"\n✓ Matrix size: {result['matrix_size']}x{result['matrix_size']}")
    print(f"✓ Result mean: {result['result_mean']:.4f}")
    print(f"✓ GPU used: {result['gpu']}")

if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python gpu_demo.py
```

First run takes 30-60 seconds (provisioning). Subsequent runs take 2-3 seconds.

## What Flash does

- **Remote execution**: `@Endpoint` functions run on Runpod Serverless GPUs/CPUs
- **Auto-scaling**: Workers scale from 0 to N based on demand
- **Dependency management**: Packages install automatically on remote workers
- **Two patterns**: Queue-based (`@Endpoint`) for batch work, load-balanced (`Endpoint()` + routes) for REST APIs

## Documentation

Full documentation: **[docs.runpod.io/flash](https://docs.runpod.io/flash)**

- [Quickstart](https://docs.runpod.io/flash/quickstart) - First GPU workload in 5 minutes
- [Create endpoints](https://docs.runpod.io/flash/endpoint-functions) - Queue-based, load-balancing, and custom Docker endpoints
- [CLI reference](https://docs.runpod.io/flash/cli/overview) - `flash run`, `flash deploy`, `flash build`
- [Configuration](https://docs.runpod.io/flash/configuration/parameters) - All endpoint parameters

## Examples

Browse working examples: **[github.com/runpod/flash-examples](https://github.com/runpod/flash-examples)**

## Requirements

- Python 3.10+
- macOS or Linux (Windows support in development)
- [Runpod account](https://runpod.io/console) with API key

## Contributing

We welcome contributions! See [RELEASE_SYSTEM.md](RELEASE_SYSTEM.md) for development workflow.

```bash
# Clone and install
git clone https://github.com/runpod/flash.git
cd flash
pip install -e ".[dev]"

# Use conventional commits
git commit -m "feat: add new feature"
git commit -m "fix: resolve issue"
```

## Support

- [Discord](https://discord.gg/cUpRmau42V) - Community support
- [GitHub Issues](https://github.com/runpod/flash/issues) - Bug reports

## License

MIT License - see [LICENSE](LICENSE) for details.
