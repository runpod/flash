# flash dev

Start the Flash development server for testing, debugging, and local development.

`flash run` is a hidden alias for `flash dev`.

## Overview

`flash dev` starts a local development server that auto-discovers your `Endpoint` definitions and serves them on your machine while deploying live ephemeral workers to RunPod Serverless. This hybrid architecture lets you rapidly iterate on your application with hot-reload while testing real GPU/CPU workloads in the cloud.

Use `flash dev` for local development and testing. When ready for production, use `flash deploy` to package and deploy everything to RunPod. See [flash deploy](./flash-deploy.md) for details.

## Architecture: local app + remote workers

```
┌─────────────────────────────────────────────────────────────────┐
│  YOUR MACHINE (localhost:8888)                                  │
│  ┌─────────────────────────────────────┐                        │
│  │  Auto-generated server              │                        │
│  │  (.flash/server.py)                 │                        │
│  │  - Discovers Endpoint definitions   │─────────┐              │
│  │  - Hot-reload via watchfiles        │         │              │
│  └─────────────────────────────────────┘         │              │
└──────────────────────────────────────────────────│──────────────┘
                                                   │ HTTPS
                                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  RUNPOD SERVERLESS                                              │
│  ┌─────────────────────────┐  ┌─────────────────────────┐       │
│  │ live-gpu-worker         │  │ live-cpu-worker         │       │
│  │ (your Endpoint function)│  │ (your Endpoint function)│       │
│  └─────────────────────────┘  └─────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

**Key points:**
- **`flash dev` auto-discovers `Endpoint` definitions** and generates `.flash/server.py`
- **Queue-based (QB) routes execute locally** at `/{file_prefix}/runsync`
- **Load-balanced (LB) routes are served locally** at `/{endpoint_name}/{path}`
- **Endpoint functions run on RunPod** as serverless endpoints
- **Hot reload** watches for `.py` file changes via watchfiles
- **Endpoints are prefixed with `live-`** to distinguish development endpoints from production (e.g., `gpu-worker` becomes `live-gpu-worker`)

This is different from `flash deploy`, where **everything** (including your FastAPI app) runs on RunPod. See [flash deploy](./flash-deploy.md) for the fully-deployed architecture.

## Usage

```bash
flash dev [OPTIONS]
```

## Options

- `--host`: Host to bind to (default: localhost)
- `--port, -p`: Port to bind to (default: 8888)
- `--reload/--no-reload`: Enable auto-reload (default: enabled)
- `--auto-provision`: Auto-provision Serverless endpoints on startup (default: disabled)

## Examples

```bash
# start server with defaults
flash dev

# custom port
flash dev --port 3000

# disable auto-reload
flash dev --no-reload

# custom host and port
flash dev --host 0.0.0.0 --port 8000
```

## What it does

1. Scans project files for `Endpoint` definitions (both QB and LB patterns)
2. Generates `.flash/server.py` with QB routes and LB routes
3. Starts uvicorn server with hot-reload via watchfiles
4. Workers use live provisioned endpoints (no packaging needed)

### How it works

When you call an `Endpoint` function via `flash dev`, Flash deploys a live ephemeral Serverless endpoint to RunPod. These are actual cloud resources that incur costs.

```
flash dev
    │
    ├── Scans project for Endpoint definitions
    ├── Generates .flash/server.py
    ├── Starts local server (e.g. localhost:8888)
    │   ├── QB routes: /{file_prefix}/runsync (local execution)
    │   └── LB routes: /{endpoint_name}/{path} (served locally)
    │
    └── On Endpoint function call:
        └── Deploys a Serverless endpoint (if not cached)
            └── Executes on the RunPod cloud
```

### Provisioning modes

| Mode | When endpoints are deployed |
|------|----------------------------|
| Default | Lazily, on first function call |
| `--auto-provision` | Eagerly, at server startup |


## Auto-provisioning

Auto-provisioning discovers and deploys Serverless endpoints before the Flash development server starts, eliminating the cold-start delay on first request.

### How it works

1. **Resource Discovery**: Scans project files for `Endpoint` definitions
2. **Parallel Deployment**: Deploys resources concurrently (up to 3 at a time)
3. **Confirmation**: Asks for confirmation if deploying more than 5 endpoints
4. **Caching**: Stores deployed resources in `.flash/resources.pkl` for reuse across runs
5. **Smart Updates**: Recognizes when endpoints already exist and updates them if configuration changed

### Using auto-provisioning

```bash
flash dev --auto-provision
```

### Benefits

- **Zero cold start**: All endpoints ready before you test them
- **Faster development**: No waiting for deployment on first HTTP call
- **Resource reuse**: Cached endpoints are reused across server restarts
- **Automatic cleanup**: Orphaned endpoints are detected and removed

### Resource caching

Resources are cached by name and automatically reused:

```bash
# first run: deploys endpoints
flash dev --auto-provision

# subsequent runs: reuses cached endpoints (faster)
flash dev --auto-provision
```

Resources persist in `.flash/resources.pkl` and survive server restarts. Configuration changes are detected automatically and trigger re-deployment only when needed.

## Testing

```bash
# health check
curl http://localhost:8888/

# QB endpoint (calls GPU worker)
curl -X POST http://localhost:8888/gpu_worker/runsync \
  -H "Content-Type: application/json" \
  -d '{"input": {"message": "Hello GPU!"}}'

# LB endpoint
curl -X POST http://localhost:8888/lb_worker/process \
  -H "Content-Type: application/json" \
  -d '{"input": "test data"}'
```

## Requirements

- `RUNPOD_API_KEY` in `.env` file or via `flash login`
