# flash run

Start the Flash development server for testing/debugging/development.

## Overview

The `flash run` command starts a local development server that auto-discovers your `Endpoint` definitions and serves them on your machine while deploying workers to Runpod Serverless. This hybrid architecture lets you rapidly iterate on your application with hot-reload while testing real GPU/CPU workloads in the cloud.

Use `flash run` when you want to skip the build step and test/develop/debug your endpoints rapidly before deploying your full application with `flash deploy`. (See [Flash Deploy](./flash-deploy.md) for details.)

## Architecture: Local App + Remote Workers

With `flash run`, your system runs in a **hybrid architecture**:

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
- **`flash run` auto-discovers `Endpoint` definitions** and generates `.flash/server.py`
- **Queue-based (QB) routes execute locally** at `/{file_prefix}/runsync`
- **Load-balanced (LB) routes are served locally** at `/{endpoint_name}/{path}`
- **Endpoint functions run on Runpod** as serverless endpoints
- **Hot reload** watches for `.py` file changes via watchfiles
- **Endpoints are prefixed with `live-`** to distinguish development endpoints from production (e.g., `gpu-worker` becomes `live-gpu-worker`)

This is different from `flash deploy`, where **everything** (including your FastAPI app) runs on Runpod. See [flash deploy](./flash-deploy.md) for the fully-deployed architecture.

## Usage

```bash
flash run [OPTIONS]
```

## Options

- `--host`: Host to bind to (default: localhost)
- `--port, -p`: Port to bind to (default: 8888)
- `--reload/--no-reload`: Enable auto-reload (default: enabled)
- `--auto-provision`: Auto-provision Serverless endpoints on startup (default: disabled)

## Examples

```bash
# Start server with defaults
flash run

# Custom port
flash run --port 3000

# Disable auto-reload
flash run --no-reload

# Custom host and port
flash run --host 0.0.0.0 --port 8000
```

## What It Does

1. Scans project files for `Endpoint` definitions (both QB and LB patterns)
2. Generates `.flash/server.py` with QB routes and LB routes
3. Starts uvicorn server with hot-reload via watchfiles
4. Workers use live provisioned endpoints (no packaging needed)

### How It Works

When you call an `Endpoint` function using `flash run`, Flash deploys a **Serverless endpoint** to Runpod. (These are actual cloud resources that incur costs.)

```
flash run
    │
    ├── Scans project for Endpoint definitions
    ├── Generates .flash/server.py
    ├── Starts local server (e.g. localhost:8888)
    │   ├── QB routes: /{file_prefix}/runsync (local execution)
    │   └── LB routes: /{endpoint_name}/{path} (served locally)
    │
    └── On Endpoint function call:
        └── Deploys a Serverless endpoint (if not cached)
            └── Executes on the Runpod cloud
```

### Provisioning Modes

| Mode | When endpoints are deployed |
|------|----------------------------|
| Default | Lazily, on first function call |
| `--auto-provision` | Eagerly, at server startup |


## Auto-Provisioning

Auto-provisioning discovers and deploys Serverless endpoints before the Flash development server starts, eliminating the cold-start delay on first request.

### How It Works

1. **Resource Discovery**: Scans project files for `Endpoint` definitions
2. **Parallel Deployment**: Deploys resources concurrently (up to 3 at a time)
3. **Confirmation**: Asks for confirmation if deploying more than 5 endpoints
4. **Caching**: Stores deployed resources in `.runpod/resources.pkl` for reuse across runs
5. **Smart Updates**: Recognizes when endpoints already exist and updates them if configuration changed

### Using Auto-Provisioning

Enable it with the `--auto-provision` flag:

```bash
flash run --auto-provision
```

Example with custom host and port:

```bash
flash run --auto-provision --host 0.0.0.0 --port 8000
```

### Benefits

- **Zero Cold Start**: All endpoints ready before you test them
- **Faster Development**: No waiting for deployment on first HTTP call
- **Resource Reuse**: Cached endpoints are reused across server restarts
- **Automatic Cleanup**: Orphaned endpoints are detected and removed

### When to Use

- **Local Development**: Always use this when testing multiple endpoints
- **Testing Workflows**: Ensures endpoints are ready for integration tests
- **Debugging**: Separates deployment issues from handler logic

### Resource Caching

Resources are cached by name and automatically reused:

```bash
# First run: deploys endpoints
flash run --auto-provision

# Subsequent runs: reuses cached endpoints (faster)
flash run --auto-provision
```

Resources persist in `.runpod/resources.pkl` and survive server restarts. Configuration changes are detected automatically and trigger re-deployment only when needed.

## Testing

```bash
# Health check
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
