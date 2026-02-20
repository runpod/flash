# flash dev

Start the Flash development server for testing/debugging/development.

## Overview

The `flash dev` command starts a local development server that auto-discovers your `@remote` functions and serves them on your machine while deploying them to Runpod Serverless. This hybrid architecture lets you rapidly iterate on your application with hot-reload while testing real GPU/CPU workloads in the cloud.

Use `flash dev` when you want to skip the build step and test/develop/debug your remote functions rapidly before deploying your full application with `flash deploy`. (See [Flash Deploy](./flash-deploy.md) for details.)

## Architecture: Local App + Remote Workers

With `flash dev`, your system runs in a **hybrid architecture**:

```
┌─────────────────────────────────────────────────────────────────┐
│  YOUR MACHINE (localhost:8888)                                  │
│  ┌─────────────────────────────────────┐                        │
│  │  Programmatic FastAPI server        │                        │
│  │  (built in-memory, no codegen)      │                        │
│  │  - Discovers @remote functions      │─────────┐              │
│  │  - Hot-reload via uvicorn           │         │              │
│  └─────────────────────────────────────┘         │              │
└──────────────────────────────────────────────────│──────────────┘
                                                   │ HTTPS
                                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  RUNPOD SERVERLESS                                              │
│  ┌─────────────────────────┐  ┌─────────────────────────┐       │
│  │ live-gpu-worker         │  │ live-cpu-worker         │       │
│  │ (your @remote function) │  │ (your @remote function) │       │
│  └─────────────────────────┘  └─────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

**Key points:**
- **`flash dev` auto-discovers `@remote` functions** and builds routes programmatically
- **Queue-based (QB) routes execute locally** at `/{file_prefix}/run_sync`
- **Load-balanced (LB) routes dispatch remotely** via `LoadBalancerSlsStub`
- **`@remote` functions run on Runpod** as serverless endpoints
- **Hot reload** watches your project directory via uvicorn's built-in reloader
- **Endpoints are prefixed with `live-`** to distinguish development endpoints from production (e.g., `gpu-worker` becomes `live-gpu-worker`)
- **No codegen** - tracebacks point directly to your source files

This is different from `flash deploy`, where **everything** (including your FastAPI app) runs on Runpod. See [flash deploy](./flash-deploy.md) for the fully-deployed architecture.

## Usage

```bash
flash dev [OPTIONS]
```

## Options

- `--host`: Host to bind to (default: localhost, env: FLASH_HOST)
- `--port, -p`: Port to bind to (default: 8888, env: FLASH_PORT)
- `--reload/--no-reload`: Enable auto-reload (default: enabled)
- `--auto-provision`: Auto-provision Serverless endpoints on startup (default: disabled)

## Examples

```bash
# Start server with defaults
flash dev

# Custom port
flash dev --port 3000

# Disable auto-reload
flash dev --no-reload

# Custom host and port
flash dev --host 0.0.0.0 --port 8000
```

## What It Does

1. Scans project files for `@remote` decorated functions
2. Builds FastAPI routes programmatically (no `.flash/server.py` artifact)
3. Starts uvicorn server with hot-reload watching your project directory
4. GPU workers use LiveServerless (no packaging needed)

### How It Works

When you call a `@remote` function using `flash dev`, Flash deploys a **Serverless endpoint** to Runpod. (These are actual cloud resources that incur costs.)

```
flash dev
    │
    ├── Scans project for @remote functions
    ├── Builds FastAPI app in-memory
    ├── Starts local server (e.g. localhost:8888)
    │   ├── QB routes: /{file_prefix}/run_sync (local execution)
    │   └── LB routes: /{file_prefix}/{path} (remote dispatch)
    │
    └── On @remote function call:
        └── Deploys a Serverless endpoint (if not cached)
            └── Executes on the Runpod cloud
```

### Provisioning Modes

| Mode | When endpoints are deployed |
|------|----------------------------|
| Default | Lazily, on first `@remote` function call |
| `--auto-provision` | Eagerly, at server startup |


## Auto-Provisioning

Auto-provisioning discovers and deploys Serverless endpoints before the Flash development server starts, eliminating the cold-start delay on first request.

### How It Works

1. **Resource Discovery**: Scans project files for `@remote` decorated functions
2. **Parallel Deployment**: Deploys resources concurrently (up to 3 at a time)
3. **Confirmation**: Asks for confirmation if deploying more than 5 endpoints
4. **Caching**: Stores deployed resources in `.runpod/resources.pkl` for reuse across runs
5. **Smart Updates**: Recognizes when endpoints already exist and updates them if configuration changed

### Using Auto-Provisioning

Enable it with the `--auto-provision` flag:

```bash
flash dev --auto-provision
```

Example with custom host and port:

```bash
flash dev --auto-provision --host 0.0.0.0 --port 8000
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
flash dev --auto-provision

# Subsequent runs: reuses cached endpoints (faster)
flash dev --auto-provision
```

Resources persist in `.runpod/resources.pkl` and survive server restarts. Configuration changes are detected automatically and trigger re-deployment only when needed.

## Testing

```bash
# Health check
curl http://localhost:8888/

# Process endpoint (calls GPU worker)
curl -X POST http://localhost:8888/process \
  -H "Content-Type: application/json" \
  -d '{"data": "test input"}'
```

## Requirements

- `RUNPOD_API_KEY` in `.env` file
