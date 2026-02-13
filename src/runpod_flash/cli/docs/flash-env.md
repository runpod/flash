# flash env

Manage deployment environments for Flash applications.

## Overview

Environments are isolated deployment contexts within a Flash app. Each environment has its own:
- Deployed endpoints and resources
- Active build version
- Configuration and state
- Network volumes (if configured)

Common use cases:
- **Development**: Test features before production
- **Staging**: Pre-production validation environment
- **Production**: Live user-facing deployment
- **Testing**: Automated testing and CI/CD integration

## Subcommands

### flash env list

Show all available environments for an app.

```bash
flash env list [OPTIONS]
```

**Options:**
- `--app, -a`: Flash app name (auto-detected from current directory)

**Example:**
```bash
# List environments for current app
flash env list

# List environments for specific app
flash env list --app my-project
```

**Output:**
```
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Name       ┃ ID                  ┃ Active Build      ┃ Created At       ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ dev        │ env_abc123          │ build_xyz789      │ 2024-01-15 10:30 │
│ staging    │ env_def456          │ build_uvw456      │ 2024-01-16 14:20 │
│ production │ env_ghi789          │ build_rst123      │ 2024-01-20 09:15 │
└────────────┴─────────────────────┴───────────────────┴──────────────────┘
```

---

### flash env create

Create a new deployment environment.

```bash
flash env create <name> [OPTIONS]
```

**Arguments:**
- `name`: Name for the new environment (e.g., staging, dev, prod)

**Options:**
- `--app, -a`: Flash app name (auto-detected from current directory)

**Example:**
```bash
# Create staging environment
flash env create staging

# Create environment in specific app
flash env create production --app my-project
```

**Output:**
```
╭───────────────────────────────────────────────╮
│ Environment Created                           │
├───────────────────────────────────────────────┤
│ Environment 'staging' created successfully    │
│                                               │
│ App: my-project                               │
│ Environment ID: env_abc123                    │
│ Status: PENDING                               │
╰───────────────────────────────────────────────╯
```

**Notes:**
- If the app doesn't exist, it's created automatically
- Environment names must be unique within an app
- Newly created environments have no active build until first deployment

---

### flash env get

Show detailed information about a deployment environment.

```bash
flash env get <name> [OPTIONS]
```

**Arguments:**
- `name`: Name of the environment to inspect

**Options:**
- `--app, -a`: Flash app name (auto-detected from current directory)

**Example:**
```bash
# Get details for production environment
flash env get production

# Get details for specific app's environment
flash env get staging --app my-project
```

**Output:**
```
╭────────────────────────────────────╮
│ Environment: production            │
├────────────────────────────────────┤
│ ID: env_ghi789                     │
│ State: DEPLOYED                    │
│ Active Build: build_rst123         │
│ Created: 2024-01-20 09:15:00       │
╰────────────────────────────────────╯

           Associated Endpoints
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Name           ┃ ID                 ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ my-gpu         │ ep_abc123          │
│ my-cpu         │ ep_def456          │
└────────────────┴────────────────────┘

       Associated Network Volumes
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Name           ┃ ID                 ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ model-cache    │ nv_xyz789          │
└────────────────┴────────────────────┘
```

---

### flash env delete

Delete a deployment environment and all its associated resources.

```bash
flash env delete <name> [OPTIONS]
```

**Arguments:**
- `name`: Name of the environment to delete

**Options:**
- `--app, -a`: Flash app name (auto-detected from current directory)

**Example:**
```bash
# Delete development environment
flash env delete dev

# Delete environment in specific app
flash env delete staging --app my-project
```

**Process:**
1. Shows environment details and resources to be deleted
2. Prompts for confirmation (required)
3. Undeploys all associated endpoints
4. Removes all associated network volumes
5. Deletes the environment from the app

**Output:**
```
╭───────────────────────────────────╮
│ Delete Confirmation               │
├───────────────────────────────────┤
│ Environment 'dev' will be deleted │
│                                   │
│ Environment ID: env_abc123        │
│ App: my-project                   │
│ Active Build: build_xyz789        │
╰───────────────────────────────────╯

? Are you sure you want to delete environment 'dev'?
  This will delete all resources associated with this environment! (Y/n)

Undeploying resources for 'dev'...
Undeployed 2 resource(s) for 'dev'
Deleting environment 'dev'...
Environment 'dev' deleted successfully
```

**Warning:** This operation is irreversible. All endpoints, volumes, and configuration associated with the environment will be permanently deleted.

## Common Workflows

### Creating Your First Environment

When starting a new project:

```bash
# Create project with flash init
flash init my-project
cd my-project

# First deployment automatically creates app and environment
flash deploy
# Creates app 'my-project' and environment 'production' if they don't exist

# Or create environment explicitly
flash env create dev
```

### Managing Multiple Environments (Dev/Staging/Prod)

```bash
# Create all environments
flash env create dev
flash env create staging
flash env create production

# Deploy to specific environments
flash deploy --env dev          # Deploy to development
flash deploy --env staging      # Deploy to staging
flash deploy --env production   # Deploy to production

# Check status of each
flash env get dev
flash env get staging
flash env get production

# List all environments
flash env list
```

### Switching Between Environments

```bash
# Deploy different code versions to different environments
git checkout main
flash deploy --env production    # Production gets main branch

git checkout feature-branch
flash deploy --env dev           # Dev gets feature branch

# Update production with new changes
git checkout main
git pull
flash deploy --env production
```

### Cleaning Up Environments

```bash
# List all environments
flash env list

# Delete old development environment
flash env delete old-dev

# Delete staging after testing completes
flash env delete staging
```

## Environment Concepts

### What is a Flash Environment?

An environment is a logical deployment context that groups:
- **Endpoints**: Serverless endpoints provisioned from your `@remote` functions
- **Network Volumes**: Persistent storage for models, cache, etc.
- **Build Version**: The active build artifact deployed to the environment
- **State**: Current deployment status (PENDING, DEPLOYED, FAILED, etc.)

### Relationship to Apps and Builds

```
Flash App (my-project)
├── Environment: dev
│   ├── Build: build_v1
│   ├── Endpoints: [ep1, ep2]
│   └── Volumes: [vol1]
├── Environment: staging
│   ├── Build: build_v2
│   ├── Endpoints: [ep1, ep2]
│   └── Volumes: [vol1]
└── Environment: production
    ├── Build: build_v2
    ├── Endpoints: [ep1, ep2]
    └── Volumes: [vol1]
```

Each environment can run a different build version, allowing you to test changes in dev before promoting to production.

### Environment Lifecycle

1. **Creation**: `flash env create staging`
   - State: PENDING
   - No active build
   - No endpoints provisioned

2. **First Deployment**: `flash deploy --env staging`
   - State: DEPLOYING
   - Provisions endpoints
   - Registers build as active
   - State: DEPLOYED

3. **Updates**: `flash deploy --env staging`
   - Creates new build
   - Updates endpoints with new code
   - Updates active build reference

4. **Deletion**: `flash env delete staging`
   - Undeploys all endpoints
   - Removes all volumes
   - Deletes environment record

### Environment States

- **PENDING**: Environment created but not deployed
- **DEPLOYING**: Deployment in progress
- **DEPLOYED**: Successfully deployed and running
- **FAILED**: Deployment or health check failed
- **DELETING**: Deletion in progress

## Best Practices

### Naming Conventions

Use clear, descriptive names that indicate purpose:

```bash
# Good
flash env create dev
flash env create staging
flash env create production
flash env create testing

# Avoid
flash env create env1
flash env create test123
flash env create abc
```

### Environment Strategy

**Three-tier approach (recommended):**
```bash
dev        # Active development, frequent deploys
staging    # Pre-production testing, QA validation
production # Live user-facing deployment
```

**Simple approach (small projects):**
```bash
dev        # Development and testing
production # Live deployment
```

**Feature-based approach (large teams):**
```bash
dev
feature-auth      # Testing authentication feature
feature-search    # Testing search feature
staging
production
```

### Deployment Workflow

1. **Develop locally**: Test with `flash run` or `flash deploy --preview`
2. **Deploy to dev**: `flash deploy --env dev` for initial testing
3. **Deploy to staging**: `flash deploy --env staging` for QA validation
4. **Deploy to production**: `flash deploy --env production` after approval

### Resource Management

- **Monitor environments regularly**: `flash env list` to track active environments
- **Clean up unused environments**: Delete old feature environments after merge
- **Check resource usage**: `flash env get <name>` to see associated resources
- **Delete carefully**: Remember that deletion is irreversible

### Safety Features

The delete command includes safety features:
- **Confirmation prompt**: Required for all deletions
- **Resource cleanup**: Automatically undeploys endpoints and volumes
- **Validation**: Checks that all resources are properly removed
- **Abort on failure**: If any resource fails to undeploy, deletion is aborted

## Troubleshooting

### Environment Not Found

**Problem**: `Error: Environment 'staging' not found`

**Solution**: List environments to verify name:
```bash
flash env list
```

Create if missing:
```bash
flash env create staging
```

### Multiple Apps Conflict

**Problem**: Running `flash env list` shows wrong app's environments

**Solution**: Specify app explicitly:
```bash
flash env list --app my-project
```

Or navigate to project directory:
```bash
cd my-project
flash env list
```

### Cannot Delete Environment

**Problem**: `Failed to undeploy all resources; environment deletion aborted`

**Solution**: Check resource status:
```bash
flash env get <name>
```

Manually undeploy problematic resources:
```bash
flash undeploy <resource-name>
```

Then retry deletion:
```bash
flash env delete <name>
```

### Environment Stuck in DEPLOYING State

**Problem**: Environment shows DEPLOYING state but deployment completed

**Solution**: Check endpoint status in Runpod Console:
- Visit https://console.runpod.io/serverless
- Check endpoint health and logs
- If healthy, try deploying again to update state

### App Not Auto-Detected

**Problem**: Command requires `--app` flag even when in project directory

**Solution**: Ensure you're in a Flash project directory with:
- `main.py` with Flash server
- `workers/` directory
- `.env` file with `RUNPOD_API_KEY`

Or specify app explicitly:
```bash
flash env list --app my-project
```

## Related Commands

- [flash deploy](./flash-deploy.md) - Build and deploy to environment
- [flash app](./flash-app.md) - Manage Flash applications
- [flash build](./flash-build.md) - Build deployment artifact
- [flash undeploy](./flash-undeploy.md) - Manage individual endpoints
