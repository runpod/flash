# flash deploy

Build and deploy your Flash application to Runpod Serverless endpoints in one step.

## Overview

The `flash deploy` command is the primary way to get your Flash application running in the cloud. It combines the build process with deployment, taking your local code and turning it into live serverless endpoints on Runpod.

**When to use this command:**
- Deploying your application for the first time
- Pushing code updates to an existing environment
- Setting up new environments (dev, staging, production)
- Testing your full distributed system with `--preview` before going live

**What happens during deployment:**
1. **Build:** Packages your code, dependencies, and manifest (same as `flash build`)
2. **Upload:** Sends the artifact to Runpod's storage
3. **Provision:** Creates or updates serverless endpoints based on your endpoint configs
4. **Configure:** Sets up environment variables, volumes, and service discovery
5. **Verify:** Confirms endpoints are healthy and displays access information

**Key features:**
- **One command:** No need to run build and deploy separately
- **Smart environment handling:** Auto-selects environment if only one exists, prompts if multiple
- **Incremental updates:** Only updates what changed, preserving endpoint URLs
- **Preview mode:** Test locally with Docker before deploying to production

## Architecture: Fully Deployed to Runpod

With `flash deploy`, your **entire application** runs on Runpod Serverless -- all endpoints deploy as peer serverless endpoints:

```
┌─────────────────────────────────────────────────────────────────┐
│  RUNPOD SERVERLESS                                              │
│                                                                 │
│  All endpoints deployed as peers, using manifest for discovery  │
│                                                                 │
│  ┌─────────────────────────┐  ┌─────────────────────────┐       │
│  │ gpu-worker              │  │ cpu-worker              │       │
│  │ (your Endpoint function)│  │ (your Endpoint function)│       │
│  └─────────────────────────┘  └─────────────────────────┘       │
│                                                                 │
│  ┌─────────────────────────┐                                    │
│  │ lb-worker               │                                    │
│  │ (load-balanced endpoint)│                                    │
│  └─────────────────────────┘                                    │
│                                                                 │
│  Service discovery: flash_manifest.json + State Manager GraphQL │
└─────────────────────────────────────────────────────────────────┘
          ▲
          │ HTTPS (authenticated)
          │
    ┌─────┴─────┐
    │   USERS   │
    └───────────┘
```

**Key points:**
- **All endpoints run on Runpod** as serverless endpoints
- **Users call endpoint URLs** directly (e.g., `https://{id}.api.runpod.ai/api/hello` for LB, `https://api.runpod.ai/v2/{id}/runsync` for QB)
- **No `live-` prefix** on endpoint names (these are production endpoints)
- **No hot reload:** code changes require a new deployment

This is different from `flash dev`, where your FastAPI app runs locally on your machine. See [flash dev](./flash-run.md) for the hybrid development architecture.

### flash dev vs flash deploy

| Aspect | `flash dev` | `flash deploy` |
|--------|-------------|----------------|
| **App runs on** | Your machine (localhost) | RunPod Serverless |
| **Endpoint functions run on** | RunPod Serverless | RunPod Serverless |
| **Endpoint naming** | `live-` prefix (e.g., `live-gpu-worker`) | No prefix (e.g., `gpu-worker`) |
| **Hot reload** | Yes | No |
| **Use case** | Development and testing | Production deployment |
| **Build artifact created** | No | Yes (tarball + manifest) |

## Usage

```bash
flash deploy [OPTIONS]
```

## Options

- `--env, -e`: Target environment name (auto-selected if only one exists)
- `--app, -a`: Flash app name (auto-detected from current directory)
- `--no-deps`: Skip transitive dependencies during pip install (default: false)
- `--exclude`: Comma-separated packages to exclude (e.g., 'torch,torchvision')
- `--output, -o`: Custom archive name (default: artifact.tar.gz)
- `--preview`: Build and launch local preview environment instead of deploying
- `--python-version`: Target Python version for worker images (`3.10`, `3.11`, or `3.12`). Overrides per-resource `python_version`.

## Examples

```bash
# Build and deploy (auto-selects environment if only one exists)
flash deploy

# Deploy to specific environment
flash deploy --env staging

# Deploy to specific app and environment
flash deploy --app my-project --env production

# Deploy with excluded packages (reduces deployment size)
flash deploy --exclude torch,torchvision,torchaudio

# Build and test locally before deploying
flash deploy --preview

# Combine options
flash deploy --env staging --exclude torch --no-deps
```

## What It Does

The deploy command combines building and deploying your Flash application in a single step:

1. **Build Phase**: Creates deployment artifact (see [flash build](./flash-build.md) for details)
   - Scans project for `Endpoint` definitions
   - Groups endpoints by resource configuration
   - Creates `flash_manifest.json` for service discovery
   - Generates handlers for each endpoint type
   - Installs dependencies with Linux x86_64 compatibility
   - Packages everything into `.flash/artifact.tar.gz`

2. **Environment Resolution**:
   - Auto-detects app name from current directory
   - If no app exists, creates it automatically
   - If `--env` specified, uses that environment (creates if missing)
   - If only one environment exists, uses it automatically
   - If multiple environments exist, prompts for selection

3. **Deployment Phase**:
   - Uploads the build artifact to Runpod storage
   - Provisions Serverless endpoints based on resource configs
   - Configures endpoints with environment variables and volumes
   - Sets up service discovery for cross-endpoint function calls
   - Registers endpoints in environment tracking

4. **Post-Deployment**:
    - Displays deployment URLs and available routes
    - Shows authentication and testing guidance
    - Cleans up temporary build directory

## Manifest and Credential Handling

During deploy, Flash updates manifest metadata with runtime endpoint details (for example `endpoint_id`, endpoint URLs, and `aiKey` when returned by the API).

- The manifest stored in State Manager keeps runtime metadata used for reconciliation.
- The local `.flash/flash_manifest.json` is sanitized before writing to disk and does not persist `aiKey`.
- `RUNPOD_API_KEY` continues to be resolved from credentials/env at runtime and is not stored in the local manifest.

## Build Options

The deploy command supports all build options from `flash build`:

### Skip Transitive Dependencies

```bash
flash deploy --no-deps
```

Only installs direct dependencies specified in `Endpoint` definitions. Useful when your base image already includes common packages.

### Exclude Packages

```bash
flash deploy --exclude torch,torchvision,torchaudio
```

Skips specified packages during dependency installation. Critical for staying under Runpod's 1.5GB deployment limit. See [flash build](./flash-build.md#managing-deployment-size) for base image package reference.

## Preview Mode

```bash
flash deploy --preview
```

Builds your project and launches a local Docker-based test environment instead of deploying to Runpod. This allows you to test your distributed system locally before production deployment.

**What happens:**
1. Builds your project (creates the archive and manifest)
2. Creates a Docker network for inter-container communication
3. Starts one Docker container per resource config
4. Exposes the application on `localhost:8000`
5. All containers communicate via Docker DNS
6. On shutdown (Ctrl+C), automatically stops and removes all containers

See [flash build](./flash-build.md#preview-environment) for more details on preview mode.

## Environment Management

### What Is an Environment?

An **environment** is an isolated deployment context within a Flash app. Each environment is a separate "stage" (like `dev`, `staging`, or `production`) that contains its own deployed endpoints, build versions, and deployment status.

For more details about environment management, see [flash env](./flash-env.md).

### Automatic Environment Creation

If the specified environment doesn't exist, `flash deploy` creates it automatically:

```bash
# Creates 'staging' if it doesn't exist
flash deploy --env staging
```

If no environment is specified and none exist, it creates a 'production' environment by default.

### Environment Auto-Selection

When you have only one environment, it's selected automatically:

```bash
# Auto-selects the only available environment
flash deploy
```

When multiple environments exist, you must specify which one:

```bash
# Error: Multiple environments found
flash deploy

# Solution: Specify environment
flash deploy --env staging
```

## Post-Deployment

After successful deployment, the command displays guidance for using your deployed application:

### 1. Authentication

All endpoints require authentication with your Runpod API key:

```bash
export RUNPOD_API_KEY="your_key_here"
```

### 2. Calling Your Endpoints

**QB endpoints:**
```bash
curl -X POST "https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"input": {"key": "value"}}'
```

**LB endpoints:**
```bash
curl -X POST "https://{ENDPOINT_ID}.api.runpod.ai/predict" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"key": "value"}'
```

### 3. Monitoring

```bash
# Check environment status
flash env get production

# View in Runpod Console
# https://console.runpod.io/serverless
```

### 4. Updates

```bash
# Deploy updated code to same environment
flash deploy --env production
```

## Troubleshooting

### Multiple Environments Error

**Problem**: `Error: Multiple environments found: dev, staging, production`

**Solution**: Specify the target environment:
```bash
flash deploy --env staging
```

### Build Fails

If the build phase fails, see [flash build troubleshooting](./flash-build.md#troubleshooting) for common build issues.

### Deployment Size Limit

**Problem**: Deployment exceeds Runpod's 1.5GB limit

**Solution**: Use `--exclude` to skip packages already in your base image:
```bash
flash deploy --exclude torch,torchvision,torchaudio
```

### Authentication Fails

**Problem**: `401 Unauthorized` when calling endpoints

**Solution**: Ensure your API key is set correctly:
```bash
echo $RUNPOD_API_KEY
flash login
```

## Related Commands

- [flash build](./flash-build.md) - Build without deploying
- [flash env](./flash-env.md) - Manage deployment environments
- [flash app](./flash-app.md) - Manage Flash applications
- [flash undeploy](./flash-undeploy.md) - Remove deployed endpoints
- [flash dev](./flash-run.md) - Local development server
