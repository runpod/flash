from runpod_flash import CpuLiveServerless, remote

cpu_config = CpuLiveServerless(name="cpu_worker")


@remote(resource_config=cpu_config)
async def cpu_hello(input_data: dict) -> dict:
    """CPU worker — lightweight processing without GPU."""
    import platform
    from datetime import datetime

    return {
        "message": input_data.get("message", "Hello from CPU worker!"),
        "timestamp": datetime.now().isoformat(),
        "platform": platform.system(),
        "python_version": platform.python_version(),
    }
