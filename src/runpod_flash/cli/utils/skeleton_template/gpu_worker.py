# gpu serverless worker -- detects available GPU hardware.
# run with: flash run
# test directly: python gpu_worker.py
from runpod_flash import Endpoint, GpuType

@Endpoint(name="gpu_worker", gpu=GpuType.ANY, dependencies=["torch"])
async def gpu_hello(input_data: dict) -> dict:
    """GPU worker that returns GPU hardware info."""
    import platform

    try:
        import torch

        gpu_available = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if gpu_available else "No GPU detected"
    except Exception as e:
        gpu_available = False
        gpu_name = f"Error: {e}"

    return {
        "message": input_data.get("message", "Hello from GPU worker!"),
        "gpu": {"available": gpu_available, "name": gpu_name},
        "python_version": platform.python_version(),
    }


if __name__ == "__main__":
    import asyncio

    test_payload = {"message": "Testing GPU worker"}
    print(f"Testing GPU worker with payload: {test_payload}")
    result = asyncio.run(gpu_hello(test_payload))
    print(f"Result: {result}")
