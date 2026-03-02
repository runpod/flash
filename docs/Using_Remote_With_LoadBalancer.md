# Load-Balanced Endpoints

## Introduction

Flash supports two execution models for serverless endpoints: queue-based (QB) and load-balanced (LB). This guide covers creating load-balanced endpoints using the `Endpoint` class for HTTP-based function execution.

### Queue-Based vs Load-Balanced

**Queue-Based** (`@Endpoint(...)` on a function)
- Requests queued and processed sequentially
- Automatic retry logic on failure
- Higher latency (queuing + processing)
- One function per endpoint

**Load-Balanced** (`ep = Endpoint(...)` + `@ep.post("/path")`)
- Requests routed directly to available workers
- Direct HTTP execution, no queue
- Lower latency (direct HTTP)
- Multiple routes on a single endpoint

### When to Use Each

Use **Load-Balanced** when you need:
- Low latency API endpoints
- Custom HTTP routing (GET, POST, PUT, DELETE, PATCH)
- Multiple routes sharing the same workers
- REST API semantics

Use **Queue-Based** when you need:
- Automatic retry logic
- Sequential, fault-tolerant processing
- Simple request/response pattern

## Quick Start

```python
from runpod_flash import Endpoint, GpuGroup

# create a load-balanced endpoint
api = Endpoint(name="example-api", gpu=GpuGroup.ADA_24, workers=(1, 3))

@api.post("/greet")
async def greet_user(name: str):
    return {"message": f"Hello, {name}!"}

@api.get("/health")
async def health():
    return {"status": "ok"}
```

Key points:
- Create an `Endpoint` instance with a name and compute config
- Use `.get()`, `.post()`, `.put()`, `.delete()`, `.patch()` to register routes
- All routes on the same `Endpoint` share the same workers
- Paths must start with `/`

## HTTP Routing

### Single Endpoint, Multiple Routes

```python
from runpod_flash import Endpoint

api = Endpoint(name="user-service", cpu="cpu3c-1-2", workers=(1, 5))

@api.get("/users")
def list_users():
    return {"users": []}

@api.post("/users")
async def create_user(name: str, email: str):
    return {"id": 1, "name": name, "email": email}

@api.get("/users/{user_id}")
def get_user(user_id: int):
    return {"id": user_id, "name": "Alice"}

@api.delete("/users/{user_id}")
async def delete_user(user_id: int):
    return {"deleted": True}
```

When deployed, a single endpoint is created with all four HTTP routes registered. FastAPI handles routing to the correct function.

### Reserved Paths

The following paths are reserved and cannot be used:
- `/ping` -- health check endpoint
- `/execute` -- framework endpoint for internal function execution

### GPU Load-Balanced Endpoint

```python
from runpod_flash import Endpoint, GpuGroup

api = Endpoint(name="inference-api", gpu=GpuGroup.ADA_24, workers=(1, 5))

@api.post("/predict")
async def predict(data: dict) -> dict:
    import torch
    model = torch.load("/models/model.pt")
    return {"prediction": model.predict(data)}

@api.get("/health")
async def health():
    return {"status": "ok", "gpu": "available"}
```

### CPU Load-Balanced Endpoint

```python
from runpod_flash import Endpoint

api = Endpoint(name="data-api", cpu="cpu3c-1-2", workers=(1, 3))

@api.post("/process")
async def process(data: dict) -> dict:
    return {"echo": data}

@api.get("/health")
async def health():
    return {"status": "healthy"}
```

## Local Development

Run locally with `flash run`:

```bash
flash run
# Starts a local dev server at http://localhost:8888
# All routes are auto-discovered and registered
```

The dev server exposes your routes at `http://localhost:8888/{endpoint_name}/{path}`.

### Testing

```python
import pytest
from runpod_flash import Endpoint

api = Endpoint(name="test-api", cpu="cpu3c-1-2")

@api.post("/calculate")
async def calculate(operation: str, a: int, b: int):
    if operation == "add":
        return a + b
    elif operation == "multiply":
        return a * b
    raise ValueError(f"Unknown operation: {operation}")

@pytest.mark.asyncio
async def test_calculate_add():
    result = await calculate("add", 5, 3)
    assert result == 8
```

## Building and Deploying

### Build Process

`flash build` scans your code for `Endpoint` patterns:
1. Finds `Endpoint(...)` variable assignments (LB endpoints)
2. Finds `@Endpoint(...)` decorator usage (QB endpoints)
3. Extracts HTTP routing metadata (method, path) for LB routes
4. Creates manifest with route registry
5. Validates for conflicts and reserved paths
6. Packages everything for deployment

### Deployment

```bash
# build the project
flash build

# deploy to an environment
flash deploy --env production
```

### Verifying Deployment

```bash
# health check
curl https://<endpoint-url>/ping

# call a route
curl -X POST https://<endpoint-url>/users \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice", "email": "alice@example.com"}'
```

## Troubleshooting

### Validation Errors

**"path must start with '/'"**
- Use absolute paths: `/api/endpoint` not `api/endpoint`

**"Duplicate route"**
- Two functions with same method and path on same endpoint
- Change path or method to make each route unique

### Runtime Errors

**"HTTP error from endpoint: 500"**
- Function raised an error during execution. Check endpoint logs.

**"Connection refused"**
- Container not running or uvicorn failed to start. Check container logs.

## Best Practices

1. **Group related routes** on the same `Endpoint` instance
2. **Use descriptive paths** like `/api/users/{user_id}` not `/api/u`
3. **Test locally with `flash run`** before deploying
4. **Handle errors gracefully** with meaningful error messages
5. **Use CPU endpoints for I/O-bound work** to save costs
6. **Set appropriate `workers` scaling** based on expected traffic

## Related Documentation

- [Flash SDK Reference](Flash_SDK_Reference.md) -- complete API reference
- [Load Balancer Endpoints](Load_Balancer_Endpoints.md) -- internal architecture
- [LoadBalancer Runtime Architecture](LoadBalancer_Runtime_Architecture.md) -- runtime execution details
