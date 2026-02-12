# Flash CLI Documentation

Command-line interface for Flash - distributed inference and serving framework.

## Quick Start

```bash
# Create new project
flash init my-project

# Navigate to project
cd my-project

# Install dependencies
pip install -r requirements.txt

# Add your Runpod API key to .env
# RUNPOD_API_KEY=your_key_here

# Run development server
flash run
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

### flash run

Run Flash development server.

```bash
flash run [OPTIONS]
```

**Options:**
- `--host`: Host to bind to (default: localhost)
- `--port, -p`: Port to bind to (default: 8888)
- `--reload/--no-reload`: Enable auto-reload (default: enabled)
- `--auto-provision`: Auto-provision serverless endpoints on startup (default: disabled)

**Example:**
```bash
flash run
flash run --port 3000
```

[Full documentation](./flash-run.md)

---

### flash undeploy

Manage and delete RunPod serverless endpoints.

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
├── main.py              # Flash Server (FastAPI)
├── workers/
│   ├── gpu/             # GPU worker
│   │   ├── __init__.py
│   │   └── endpoint.py
│   └── cpu/             # CPU worker
│       ├── __init__.py
│       └── endpoint.py
├── .env
├── requirements.txt
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
curl -X POST http://localhost:8888/gpu/hello \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello GPU!"}'

# Call CPU worker
curl -X POST http://localhost:8888/cpu/hello \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello CPU!"}'
```

## Getting Help

```bash
flash --help
flash init --help
flash run --help
```
