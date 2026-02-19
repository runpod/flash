from runpod_flash import GpuType, LiveServerless, remote

gpu_config = LiveServerless(
    name="gpu_worker",
    gpus=[GpuType.ANY],
)


@remote(resource_config=gpu_config, dependencies=["torch"])
async def gpu_hello(input_data: dict) -> dict:
    """GPU worker — detects available GPU hardware."""
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
