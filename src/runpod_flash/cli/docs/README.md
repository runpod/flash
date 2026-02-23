# Flash CLI Documentation

Command-line interface for Flash - distributed inference and serving framework.

## Quick Start

If you haven't already, install Flash:

```bash
pip install runpod-flash
```

Create a new project, navigate to it, and install dependencies:

```bash
flash init my-project
cd my-project
uv sync                          # or: pip install -r requirements.txt
```

Add your Runpod API key to `.env`:
```bash
echo "RUNPOD_API_KEY=your_api_key_here" > .env
```

Start the development server to test your `@remote` functions:

```bash
flash run
```

When you're ready to deploy your application to Runpod, use:

```bash
flash deploy
```


## Commands

### flash init

Create a new Flash project.

```bash
flash init [PROJECT_NAME] [OPTIONS]
```

**Options:**
- `--force, -f`: Overwrite existing files

**Examples:**
```bash
# Create new project
flash init my-project

# Initialize in current directory
flash init .

# Overwrite existing files
flash init my-project --force
```

[Full documentation](./flash-init.md)

---

### flash build

Build Flash application for deployment.

```bash
flash build [OPTIONS]
```

**Options:**
- `--no-deps`: Skip transitive dependencies during pip install
- `--keep-build`: Keep `.flash/.build` directory after creating archive
- `--output, -o`: Custom archive name (default: artifact.tar.gz)
- `--exclude`: Comma-separated packages to exclude (e.g., 'torch,torchvision')
- `--preview`: Launch local test environment after build

**Example:**
```bash
flash build
flash build --preview                                 # Build and test locally
flash build --keep-build --output deploy.tar.gz
flash build --exclude torch,torchvision,torchaudio   # Exclude large packages
```

[Full documentation](./flash-build.md)

---

### flash deploy

Build and deploy Flash applications to Runpod Serverless endpoints in one step.

```bash
flash deploy [OPTIONS]
```

**Options:**
- `--env, -e`: Target environment name
- `--app, -a`: Flash app name
- `--no-deps`: Skip transitive dependencies during pip install
- `--exclude`: Comma-separated packages to exclude (e.g., 'torch,torchvision')
- `--use-local-flash`: Bundle local runpod_flash source (for development)
- `--output, -o`: Custom archive name (default: artifact.tar.gz)
- `--preview`: Build and launch local preview instead of deploying

**Examples:**
```bash
# Build and deploy (auto-selects environment if only one exists)
flash deploy

# Deploy to specific environment
flash deploy --env staging

# Deploy with excluded packages
flash deploy --exclude torch,torchvision,torchaudio

# Build and test locally before deploying
flash deploy --preview
```

[Full documentation](./flash-deploy.md)

---

### flash run

Start a Flash development server for testing/debugging/development.

```bash
flash run [OPTIONS]
```

**Options:**
- `--host`: Host to bind to (default: localhost)
- `--port, -p`: Port to bind to (default: 8888)
- `--reload/--no-reload`: Enable auto-reload (default: enabled)
- `--auto-provision`: Auto-provision Serverless endpoints on startup (default: disabled)

**Example:**
```bash
flash run
flash run --port 3000
```

[Full documentation](./flash-run.md)

---

### flash env

Manage deployment environments for your Flash applications.

```bash
flash env <subcommand> [OPTIONS]
```

**Subcommands:**
- `list`: Show all available environments
- `create <name>`: Create a new environment
- `get <name>`: Get detailed environment information
- `delete <name>`: Delete an environment and its resources

**Options:**
- `--app, -a`: Flash app name (auto-detected if in project directory)

**Examples:**
```bash
# List all environments
flash env list

# Create new environment
flash env create staging

# Get environment details
flash env get production

# Delete environment
flash env delete dev
```

[Full documentation](./flash-env.md)

---

### flash app

Manage Flash apps (cloud-side organizational units that group deployment environments, build artifacts, and configuration).

```bash
flash app <subcommand> [OPTIONS]
```

**Subcommands:**
- `list`: Show all Flash apps
- `create <name>`: Create a new Flash app
- `get <name>`: Get detailed app information
- `delete`: Delete an app and all associated resources

**Options:**
- `--app, -a`: Flash app name (required for delete)

**Examples:**
```bash
# List all apps
flash app list

# Create new app
flash app create my-project

# Get app details
flash app get my-project

# Delete app
flash app delete --app my-project
```

[Full documentation](./flash-app.md)

---

### flash undeploy

Manage and delete Runpod serverless endpoints.

```bash
flash undeploy [NAME|list] [OPTIONS]
```

**Options:**
- `--all`: Undeploy all endpoints (requires confirmation)
- `--interactive, -i`: Interactive checkbox selection
- `--cleanup-stale`: Remove inactive endpoints from tracking

**Examples:**

```bash
# List all tracked endpoints
flash undeploy list

# Undeploy specific endpoint by name
flash undeploy my-api

# Undeploy all endpoints
flash undeploy --all

# Interactive selection
flash undeploy --interactive

# Clean up stale endpoint tracking
flash undeploy --cleanup-stale
```

**Status Indicators:**

- 🟢 **Active**: Endpoint is running and healthy
- 🔴 **Inactive**: Endpoint deleted externally (use --cleanup-stale to remove from tracking)
- ❓ **Unknown**: Health check failed

[Full documentation](./flash-undeploy.md)

---

## Features

### File-Based Logging

Flash automatically logs CLI activity to local files during development for debugging and auditing.

**Quick configuration:**

```bash
# Disable file logging
export FLASH_FILE_LOGGING_ENABLED=false

# Keep only 7 days of logs
export FLASH_LOG_RETENTION_DAYS=7

# Use custom log directory
export FLASH_LOG_DIR=/var/log/flash
```

Default location: `.flash/logs/activity.log`

[Full documentation](./flash-logging.md)

---

## Project Structure

```
my-project/
├── gpu_worker.py        # GPU worker with @remote function
├── cpu_worker.py        # CPU worker with @remote function
├── .env
├── pyproject.toml       # Python dependencies (uv/pip compatible)
└── README.md
```

## Environment Variables

Required in `.env`:
```bash
RUNPOD_API_KEY=your_api_key_here
```

## Testing Your Server

```bash
# Health check
curl http://localhost:8888/ping

# Call GPU worker
curl -X POST http://localhost:8888/gpu_worker/run_sync \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello GPU!"}'

# Call CPU worker
curl -X POST http://localhost:8888/cpu_worker/run_sync \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello CPU!"}'
```

## Getting Help

```bash
flash --help
flash init --help
flash run --help
```
