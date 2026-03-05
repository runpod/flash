# cpu load-balanced HTTP endpoint with custom routes.
# run with: flash run
from runpod_flash import Endpoint

api = Endpoint(name="lb_worker", cpu="cpu3c-1-2", workers=(1, 3))


@api.post("/process")
async def process(input_data: dict) -> dict:
    """Process input data on a load-balanced CPU endpoint."""
    from datetime import datetime

    return {
        "status": "success",
        "echo": input_data,
        "timestamp": datetime.now().isoformat(),
    }


@api.get("/health")
async def health() -> dict:
    """Health check for the load-balanced endpoint."""
    return {"status": "healthy"}
