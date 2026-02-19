from runpod_flash import CpuLiveLoadBalancer, remote

api_config = CpuLiveLoadBalancer(
    name="lb_worker",
    workersMin=1,
)


@remote(resource_config=api_config, method="POST", path="/process")
async def process(input_data: dict) -> dict:
    """Process input data on a load-balanced CPU endpoint."""
    from datetime import datetime

    return {
        "status": "success",
        "echo": input_data,
        "timestamp": datetime.now().isoformat(),
    }


@remote(resource_config=api_config, method="GET", path="/health")
async def health() -> dict:
    """Health check for the load-balanced endpoint."""
    return {"status": "healthy"}
