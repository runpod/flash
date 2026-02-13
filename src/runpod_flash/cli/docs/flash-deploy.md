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
3. **Provision:** Creates or updates serverless endpoints based on your resource configs
4. **Configure:** Sets up environment variables, volumes, and service discovery
5. **Verify:** Confirms endpoints are healthy and displays access information

**Key features:**
- **One command:** No need to run build and deploy separately
- **Smart environment handling:** Auto-selects environment if only one exists, prompts if multiple
- **Incremental updates:** Only updates what changed, preserving endpoint URLs
- **Preview mode:** Test locally with Docker before deploying to production

## Architecture: Fully Deployed to Runpod

With `flash deploy`, your **entire application** runs on Runpod Serverless—both your FastAPI app (the "orchestrator") and all `@remote` worker functions:

```
┌─────────────────────────────────────────────────────────────────┐
│  RUNPOD SERVERLESS                                              │
│                                                                 │
│  ┌─────────────────────────────────────┐                        │
│  │  MOTHERSHIP ENDPOINT                │                        │
│  │  (your FastAPI app from main.py)    │                        │
│  │  - Your HTTP routes                 │                        │
│  │  - Orchestrates @remote calls       │───────────┐            │
│  │  - Public URL for users             │           │            │
│  └─────────────────────────────────────┘           │            │
│                                                    │ internal   │
│                                                    ▼            │
│  ┌─────────────────────────┐  ┌─────────────────────────┐       │
│  │ gpu-worker              │  │ cpu-worker              │       │
│  │ (your @remote function) │  │ (your @remote function) │       │
│  └─────────────────────────┘  └─────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
          ▲
          │ HTTPS (authenticated)
          │
    ┌─────┴─────┐
    │   USERS   │
    └───────────┘
```

**Key points:**
- **Your FastAPI app runs on Runpod** as the "mothership" endpoint
- **`@remote` functions run on Runpod** as separate worker endpoints
- **Users call the mothership URL** directly (e.g., `https://xyz123.api.runpod.ai/api/hello`)
- **No `live-` prefix** on endpoint names (these are production endpoints)
- **No hot reload:** code changes require a new deployment

This is different from `flash run`, where your FastAPI app runs locally on your machine. See [flash run](./flash-run.md) for the hybrid development architecture.

### flash run vs flash deploy

| Aspect | `flash run` | `flash deploy` |
|--------|-------------|----------------|
| **FastAPI app runs on** | Your machine (localhost) | Runpod Serverless (mothership) |
| **`@remote` functions run on** | Runpod Serverless | Runpod Serverless |
| **Endpoint naming** | `live-` prefix (e.g., `live-gpu-worker`) | No prefix (e.g., `gpu-worker`) |
| **Hot reload** | Yes | No |
| **Use case** | Development & testing | Production deployment |
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
- `--use-local-flash`: Bundle local runpod_flash source instead of PyPI version (for development/testing)
- `--output, -o`: Custom archive name (default: artifact.tar.gz)
- `--preview`: Build and launch local preview environment instead of deploying

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
   - Scans project for `@remote` decorated functions
   - Groups functions by resource configuration
   - Creates `flash_manifest.json` for service discovery
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

## Build Options

The deploy command supports all build options from `flash build`:

### Skip Transitive Dependencies

```bash
flash deploy --no-deps
```

Only installs direct dependencies specified in `@remote` decorators. Useful when your base image already includes common packages.

### Exclude Packages

```bash
flash deploy --exclude torch,torchvision,torchaudio
```

Skips specified packages during dependency installation. Critical for staying under Runpod's 500MB deployment limit. See [flash build](./flash-build.md#managing-deployment-size) for base image package reference.

### Local Flash Development

```bash
flash deploy --use-local-flash
```

Bundles your local `runpod_flash` source instead of the PyPI version. Only use this for development and testing.

## Preview Mode

```bash
flash deploy --preview
```

Builds your project and launches a local Docker-based test environment instead of deploying to Runpod. This allows you to test your distributed system locally before production deployment.

**What happens:**
1. Builds your project (creates the archive and manifest)
2. Creates a Docker network for inter-container communication
3. Starts one Docker container per resource config:
   - Mothership container (orchestrator)
   - All worker containers (GPU, CPU, etc.)
4. Exposes the mothership on `localhost:8000`
5. All containers communicate via Docker DNS
6. On shutdown (Ctrl+C), automatically stops and removes all containers

**Use this when:**
- Testing deployment before production
- Validating manifest structure
- Debugging resource provisioning
- Verifying endpoint auto-discovery
- Testing distributed function calls

See [flash build](./flash-build.md#preview-environment) for more details on preview mode.

## Environment Management

### What Is an Environment?

An **environment** is an isolated deployment context within a Flash app. Each environment is a separate "stage" (like `dev`, `staging`, or `production`) that contains its own deployed endpoints, build versions, network volumes (if used) and deployment status.

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

### Managing Environments

Use `flash env` commands to manage environments:

```bash
# List all environments
flash env list

# Create new environment
flash env create staging

# View environment details
flash env get production

# Delete environment
flash env delete dev
```

## Post-Deployment

After successful deployment, the command displays guidance for using your deployed application:

### 1. Authentication

All endpoints require authentication with your Runpod API key:

```bash
# Set API key as environment variable (recommended)
export RUNPOD_API_KEY="your_key_here"

# Or use a .env file
echo "RUNPOD_API_KEY=your_key_here" >> .env
```

### 2. Calling Your Functions

Using HTTP/curl:

```bash
curl -X POST https://YOUR_ENDPOINT_URL/YOUR_PATH \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"param1": "value1"}'
```

### 3. Available Routes

The deployment output shows all available routes registered from your `@remote` decorators:

```
POST   /api/process
GET    /api/status
POST   /gpu/inference
```

### 4. Monitoring

View deployment status and logs:

```bash
# Check environment status
flash env get production

# View in Runpod Console
# https://console.runpod.io/serverless
```

### 5. Updates

To update your deployment with new code:

```bash
# Deploy updated code to same environment
flash deploy --env production
```

This creates a new build and updates all endpoints in the environment.

## Output

Successful deployment displays:

```
╭───────────────────────── Flash Build Configuration ──────────────────────────╮
│ Project: my-project                                                          │
│ Directory: /path/to/project                                                  │
│ Archive: .flash/artifact.tar.gz                                              │
│ Skip transitive deps: False                                                  │
│ Keep build dir: False                                                        │
╰──────────────────────────────────────────────────────────────────────────────╯
⠙ ✓ Loaded ignore patterns
⠙ ✓ Found 42 files to package
⠙ ✓ Created .flash/.build/my-project/
⠙ ✓ Copied 42 files
⠙ ✓ Created manifest and registered 3 resources
⠙ ✓ Installed 5 packages
⠙ ✓ Created artifact.tar.gz (45.2 MB)
⠙ ✓ Removed .build directory

Deploying to 'production'...

⠙ Uploading build artifact...
⠙ Provisioning serverless endpoints...
⠙ Configuring endpoints...

✓ Deployment Complete

Next Steps:

1. Authentication Required
   All endpoints require authentication. Set your API key as an environment
   variable...

2. Call Your Functions
   Your mothership is deployed at:
   https://api-xxxxx.runpod.net

3. Available Routes
   POST   /api/hello
   POST   /gpu/process

4. Monitor & Debug
   flash env get production  - View environment status
   Runpod Console  - View logs at https://console.runpod.io/serverless

5. Update or Remove Deployment
   flash deploy --env production  - Update deployment
   flash env delete production  - Remove deployment
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

**Problem**: Deployment exceeds Runpod's 500MB limit

**Solution**: Use `--exclude` to skip packages already in your base image:

```bash
# Exclude PyTorch packages (pre-installed in GPU images)
flash deploy --exclude torch,torchvision,torchaudio
```

See [flash build - Managing Deployment Size](./flash-build.md#managing-deployment-size) for details on base image packages.

### Authentication Fails

**Problem**: `401 Unauthorized` when calling endpoints

**Solution**: Ensure your API key is set correctly:

```bash
# Check if API key is set
echo $RUNPOD_API_KEY

# Set API key
export RUNPOD_API_KEY="your_key_here"

# Or load from .env file
source .env
```

### Environment Not Found After Creation

If you just created an environment but it can't be found, wait a few seconds for the API to sync, then retry.

## Performance Considerations

### Build Time

The build phase can take several minutes depending on:
- The number of dependencies that must be installed
- Project size and file count
- Whether dependencies need cross-platform compilation

### Deployment Time

Endpoint provisioning typically takes 2-5 minutes:
- Container image pull and initialization
- Endpoint health checks and registration
- Service discovery configuration

### Optimization Tips

1. **Use `--no-deps`** if base image has dependencies
2. **Use `--exclude`** for packages in base image
3. **Cache builds** by deploying to same environment
4. **Test with `--preview`** before deploying to production

## Next Steps

After deploying:

1. **Test Your Endpoints**: Call your functions to verify deployment
2. **Monitor Performance**: Check logs and metrics in Runpod Console
3. **Set Up CI/CD**: Automate deployments with GitHub Actions
4. **Scale Resources**: Adjust resource configs for production load
5. **Manage Environments**: Use `flash env` commands for environment lifecycle

## Related Commands

- [flash build](./flash-build.md) - Build without deploying
- [flash env](./flash-env.md) - Manage deployment environments
- [flash app](./flash-app.md) - Manage Flash applications
- [flash undeploy](./flash-undeploy.md) - Remove deployed endpoints
- [flash run](./flash-run.md) - Local development server
