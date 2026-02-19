from runpod_flash import GpuGroup, LiveServerless, remote

gpu_config = LiveServerless(
    name="gpu_worker",
    gpus=[GpuGroup.ANY],
    workersMin=0,
    workersMax=1,
    idleTimeout=60,
)


@remote(resource_config=gpu_config, dependencies=["torch"])
async def gpu_hello(input_data: dict) -> dict:
    """Simple GPU worker example with GPU detection."""
    import platform
    from datetime import datetime

    try:
        import torch

        gpu_available = torch.cuda.is_available()
        if gpu_available:
            gpu_name = torch.cuda.get_device_name(0)
            gpu_count = torch.cuda.device_count()
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        else:
            gpu_name = "No GPU detected"
            gpu_count = 0
            gpu_memory = 0
    except Exception as e:
        gpu_available = False
        gpu_name = f"Error detecting GPU: {str(e)}"
        gpu_count = 0
        gpu_memory = 0

    message = input_data.get("message", "Hello from GPU worker!")

    return {
        "status": "success",
        "message": message,
        "worker_type": "GPU",
        "gpu_info": {
            "available": gpu_available,
            "name": gpu_name,
            "count": gpu_count,
            "memory_gb": round(gpu_memory, 2) if gpu_memory else 0,
        },
        "timestamp": datetime.now().isoformat(),
        "platform": platform.system(),
        "python_version": platform.python_version(),
    }


# Test locally with: python -m workers.gpu.endpoint
if __name__ == "__main__":
    import asyncio

    test_payload = {"message": "Testing GPU worker"}
    print(f"Testing GPU worker with payload: {test_payload}")
    result = asyncio.run(gpu_hello(test_payload))
    print(f"Result: {result}")
