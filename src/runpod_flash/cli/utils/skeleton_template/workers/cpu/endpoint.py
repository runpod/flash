from runpod_flash import CpuLiveServerless, remote

cpu_config = CpuLiveServerless(
    name="cpu_worker",
    workersMin=0,
    workersMax=1,
    idleTimeout=5,
)


@remote(resource_config=cpu_config)
async def cpu_hello(input_data: dict) -> dict:
    """Simple CPU worker example."""
    import platform
    from datetime import datetime

    message = input_data.get("message", "Hello from CPU worker!")

    return {
        "status": "success",
        "message": message,
        "worker_type": "CPU",
        "timestamp": datetime.now().isoformat(),
        "platform": platform.system(),
        "python_version": platform.python_version(),
    }


# Test locally with: python -m workers.cpu.endpoint
if __name__ == "__main__":
    import asyncio

    test_payload = {"message": "Testing CPU worker"}
    print(f"Testing CPU worker with payload: {test_payload}")
    result = asyncio.run(cpu_hello(test_payload))
    print(f"Result: {result}")
