# cpu serverless worker -- lightweight processing without GPU.
# run with: flash run
# test directly: python cpu_worker.py
from runpod_flash import Endpoint


@Endpoint(name="cpu_worker", cpu="cpu3c-1-2")
async def cpu_hello(input_data: dict) -> dict:
    """CPU worker that returns a greeting."""
    import platform
    from datetime import datetime

    return {
        "message": input_data.get("message", "Hello from CPU worker!"),
        "timestamp": datetime.now().isoformat(),
        "platform": platform.system(),
        "python_version": platform.python_version(),
    }


if __name__ == "__main__":
    import asyncio

    test_payload = {"message": "Testing CPU worker"}
    print(f"Testing CPU worker with payload: {test_payload}")
    result = asyncio.run(cpu_hello(test_payload))
    print(f"Result: {result}")
