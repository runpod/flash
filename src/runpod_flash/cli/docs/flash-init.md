# flash init

Create a new Flash project with a ready-to-use template structure.

## Overview

The `flash init` command scaffolds a new Flash project with everything you need to get started: a main server (mothership), example GPU and CPU workers, and the directory structure that Flash expects. It's the fastest way to go from zero to a working distributed application.

> **Note:** This command only creates **local files**. It doesn't interact with Runpod or create any cloud resources. Cloud resources (apps, environments, endpoints) are created later when you run `flash deploy`.

### When to use this command
- Starting a new Flash project from scratch
- Learning how Flash projects are structured
- Creating a boilerplate to customize for your use case

**After initialization:**
1. Copy `.env.example` to `.env` and add your `RUNPOD_API_KEY`
2. Run `flash run` to start the local development server
3. Customize the workers for your use case
4. Deploy with `flash deploy` when ready

## Usage

```bash
flash init [PROJECT_NAME] [OPTIONS]
```

## Arguments

- `PROJECT_NAME` (optional): Name of the project directory to create
  - If omitted or `.`, initializes in current directory

## Options

- `--force, -f`: Overwrite existing files

## Examples

```bash
# Create new project directory
flash init my-project

# Initialize in current directory
flash init .

# Overwrite existing files
flash init my-project --force
```

## What It Creates

```
my-project/
├── main.py              # Flash Server (FastAPI)
├── workers/
│   ├── gpu/             # GPU worker example
│   │   ├── __init__.py
│   │   └── endpoint.py
│   └── cpu/             # CPU worker example
│       ├── __init__.py
│       └── endpoint.py
├── .env
├── requirements.txt
└── README.md
```

## Next Steps

```bash
cd my-project
pip install -r requirements.txt  # or use your preferred environment manager
# Add RUNPOD_API_KEY to .env
flash run
```

Visit http://localhost:8888/docs for interactive API documentation.
