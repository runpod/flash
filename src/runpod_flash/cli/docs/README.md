# Flash CLI Documentation

Command-line interface for Flash - distributed inference and serving framework.

## Quick start

Install Flash:

```bash
pip install runpod-flash
```

Create a new project, navigate to it, and install dependencies:

```bash
flash init my-project
cd my-project
uv sync                          # or: pip install -r requirements.txt
```

Authenticate with RunPod (saves API key to `~/.runpod/config.toml`):
```bash
flash login
```

Alternatively, set your API key via environment variable or `.env` file:
```bash
export RUNPOD_API_KEY=your_api_key_here
# or add to .env file
```

Deploy your application to RunPod:

```bash
flash deploy
```

Run your script to call deployed endpoints:

```bash
python gpu_demo.py
```

For local development with hot-reload:

```bash
flash dev
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
flash init my-project
flash init .
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
flash build --preview
flash build --keep-build --output deploy.tar.gz
flash build --exclude torch,torchvision,torchaudio
```

[Full documentation](./flash-build.md)

---

### flash deploy

Build and deploy Flash applications to RunPod Serverless endpoints.

```bash
flash deploy [OPTIONS]
```

**Options:**
- `--env, -e`: Target environment name
- `--app, -a`: Flash app name
- `--no-deps`: Skip transitive dependencies during pip install
- `--exclude`: Comma-separated packages to exclude (e.g., 'torch,torchvision')
- `--output, -o`: Custom archive name (default: artifact.tar.gz)
- `--preview`: Build and launch local preview instead of deploying

**Examples:**
```bash
flash deploy
flash deploy --env staging
flash deploy --exclude torch,torchvision,torchaudio
flash deploy --preview
```

[Full documentation](./flash-deploy.md)

---

### flash dev

Start a Flash development server for testing, debugging, and local development.

`flash run` is a hidden alias for `flash dev`.

```bash
flash dev [OPTIONS]
```

**Options:**
- `--host`: Host to bind to (default: localhost)
- `--port, -p`: Port to bind to (default: 8888)
- `--reload/--no-reload`: Enable auto-reload (default: enabled)
- `--auto-provision`: Auto-provision Serverless endpoints on startup (default: disabled)

**Example:**
```bash
flash dev
flash dev --port 3000
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
flash env list
flash env create staging
flash env get production
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
flash app list
flash app create my-project
flash app get my-project
flash app delete --app my-project
```

[Full documentation](./flash-app.md)

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
flash undeploy list
flash undeploy my-api
flash undeploy --all
flash undeploy --interactive
flash undeploy --cleanup-stale
```

[Full documentation](./flash-undeploy.md)

---

## Features

### File-based logging

Flash automatically logs CLI activity to local files during development for debugging and auditing.

**Quick configuration:**

```bash
export FLASH_FILE_LOGGING_ENABLED=false   # disable file logging
export FLASH_LOG_RETENTION_DAYS=7         # keep only 7 days of logs
export FLASH_LOG_DIR=/var/log/flash       # custom log directory
```

Default location: `.flash/logs/activity.log`

[Full documentation](./flash-logging.md)

---

## Project structure

```
my-project/
├── gpu_worker.py        # GPU worker with @Endpoint function
├── cpu_worker.py        # CPU worker with @Endpoint function
├── lb_worker.py         # Load-balanced HTTP endpoint
├── .env
├── pyproject.toml       # Python dependencies (uv/pip compatible)
└── README.md
```

## Environment variables

Required in `.env`:
```bash
RUNPOD_API_KEY=your_api_key_here
```

Optional:
```bash
FLASH_APP=my-project            # defaults to current directory name
FLASH_ENV=staging               # defaults to "production"
FLASH_SENTINEL_TIMEOUT=120      # sentinel request timeout in seconds (default: 90)
```

## Testing your dev server

```bash
# health check
curl http://localhost:8888/ping

# QB endpoint
curl -X POST http://localhost:8888/gpu_worker/runsync \
  -H "Content-Type: application/json" \
  -d '{"input": {"message": "Hello GPU!"}}'

# LB endpoint
curl -X POST http://localhost:8888/lb_worker/process \
  -H "Content-Type: application/json" \
  -d '{"input": "test"}'
```

## Getting help

```bash
flash --help
flash init --help
flash dev --help
```
