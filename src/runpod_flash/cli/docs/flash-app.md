# flash app

Manage Flash applications (top-level organizational units).

## Overview

Flash apps are the top-level organizational units in the Flash deployment hierarchy. Each app contains:
- **Environments**: Deployment contexts (dev, staging, production)
- **Builds**: Build artifacts created from your code
- **Configuration**: App-wide settings and metadata

Apps provide isolation between different projects and enable organized management of multiple deployments.

## Subcommands

### flash app list

Show all Flash apps under your account.

```bash
flash app list
```

**Example:**
```bash
flash app list
```

**Output:**
```
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Name           ┃ ID                   ┃ Environments            ┃ Builds           ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ my-project     │ app_abc123           │ dev, staging, prod      │ build_1, build_2 │
│ demo-api       │ app_def456           │ production              │ build_3          │
│ ml-inference   │ app_ghi789           │ dev, production         │ build_4, build_5 │
└────────────────┴──────────────────────┴─────────────────────────┴──────────────────┘
```

---

### flash app create

Create a new Flash app.

```bash
flash app create <name>
```

**Arguments:**
- `name`: Name for the new Flash app (e.g., my-project, api-service)

**Example:**
```bash
# Create new app
flash app create my-project
```

**Output:**
```
╭───────────────────────────────────────────────╮
│ ✅ App Created                                │
├───────────────────────────────────────────────┤
│ Flash app 'my-project' created successfully   │
│                                               │
│ App ID: app_abc123                            │
╰───────────────────────────────────────────────╯
```

**Notes:**
- App names must be unique within your account
- Newly created apps have no environments or builds until first deployment
- Apps are automatically created during first deployment if they don't exist

---

### flash app get

Get detailed information about a Flash app.

```bash
flash app get <name>
```

**Arguments:**
- `name`: Name of the Flash app to inspect

**Example:**
```bash
# Get details for my-project app
flash app get my-project
```

**Output:**
```
╭─────────────────────────────────╮
│ 📱 Flash App: my-project        │
├─────────────────────────────────┤
│ Name: my-project                │
│ ID: app_abc123                  │
│ Environments: 3                 │
│ Builds: 5                       │
╰─────────────────────────────────╯

              Environments
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Name       ┃ ID                 ┃ State   ┃ Active Build     ┃ Created          ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ dev        │ env_dev123         │ DEPLOYED│ build_xyz789     │ 2024-01-15 10:30 │
│ staging    │ env_stg456         │ DEPLOYED│ build_xyz789     │ 2024-01-16 14:20 │
│ production │ env_prd789         │ DEPLOYED│ build_abc123     │ 2024-01-20 09:15 │
└────────────┴────────────────────┴─────────┴──────────────────┴──────────────────┘

                     Builds
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ ID                 ┃ Status                   ┃ Created          ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ build_abc123       │ COMPLETED                │ 2024-01-20 09:00 │
│ build_xyz789       │ COMPLETED                │ 2024-01-18 15:45 │
│ build_def456       │ COMPLETED                │ 2024-01-15 11:20 │
└────────────────────┴──────────────────────────┴──────────────────┘
```

---

### flash app delete

Delete a Flash app and all its associated resources.

```bash
flash app delete --app <name>
```

**Options:**
- `--app, -a`: Flash app name to delete (required)

**Example:**
```bash
# Delete my-project app
flash app delete --app my-project
```

**Process:**
1. Shows app details and resources to be deleted
2. Prompts for confirmation (required)
3. Deletes all environments and their resources
4. Deletes all builds
5. Deletes the app

**Warning:** This operation is irreversible. All environments, builds, endpoints, volumes, and configuration will be permanently deleted.

## Common Workflows

### Creating Your First App

When starting a new Flash project:

```bash
# Create project with flash init
flash init my-project
cd my-project

# First deployment automatically creates app
flash deploy
# Creates app 'my-project' if it doesn't exist

# Or create app explicitly first
flash app create my-project
flash env create production
flash deploy --env production
```

### Organizing Multiple Apps

```bash
# Create apps for different projects
flash app create api-gateway
flash app create ml-inference
flash app create data-processing

# Each app has its own environments
flash env create dev --app api-gateway
flash env create prod --app api-gateway

flash env create dev --app ml-inference
flash env create prod --app ml-inference

# List all apps to see organization
flash app list
```

### Viewing App Details

```bash
# Get comprehensive app information
flash app get my-project

# See all environments and builds
# Check deployment status
# View resource allocation
```

### Cleaning Up Apps

```bash
# List all apps
flash app list

# Delete unused app and all its resources
flash app delete --app old-project
```

## App Concepts

### What is a Flash App?

A Flash app is the top-level container that organizes all deployment-related resources:

```
Flash App (my-project)
│
├── Environments
│   ├── dev
│   │   ├── Endpoints (ep1, ep2)
│   │   └── Volumes (vol1)
│   ├── staging
│   │   ├── Endpoints (ep1, ep2)
│   │   └── Volumes (vol1)
│   └── production
│       ├── Endpoints (ep1, ep2)
│       └── Volumes (vol1)
│
└── Builds
    ├── build_v1 (2024-01-15)
    ├── build_v2 (2024-01-18)
    └── build_v3 (2024-01-20)
```

### Relationship to Environments and Builds

**Apps contain Environments:**
- Each app can have multiple environments (dev, staging, prod)
- Environments are isolated deployment contexts within an app
- Use `flash env` commands to manage environments

**Apps store Builds:**
- Each deployment creates a build artifact
- Builds are versioned and tracked within the app
- Environments reference builds to know what code to run

**Apps provide Isolation:**
- Different apps don't share resources
- Each app has its own quota and limits
- Apps can have different access controls

### App Discovery and Auto-Detection

Flash CLI automatically detects the app name from your current directory:

```bash
# In project directory
cd /path/to/my-project

# App name auto-detected from directory or config
flash deploy          # Deploys to 'my-project' app
flash env list        # Lists 'my-project' environments
```

You can always override with the `--app` flag:

```bash
flash deploy --app other-project
flash env list --app other-project
```

### App Hierarchy

```
RunPod Account
├── Flash App: my-api
│   ├── Environment: dev
│   ├── Environment: prod
│   └── Builds: [v1, v2, v3]
│
├── Flash App: ml-inference
│   ├── Environment: staging
│   ├── Environment: production
│   └── Builds: [v1, v2]
│
└── Flash App: data-processor
    ├── Environment: production
    └── Builds: [v1]
```

## Examples with Real Output

### List Apps

```bash
$ flash app list

┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Name           ┃ ID                   ┃ Environments            ┃ Builds           ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ my-api         │ app_abc123           │ dev, staging, prod      │ build_1, build_2 │
│ ml-inference   │ app_def456           │ production              │ build_3          │
└────────────────┴──────────────────────┴─────────────────────────┴──────────────────┘
```

### Create App

```bash
$ flash app create demo-api

╭───────────────────────────────────────────────╮
│ ✅ App Created                                │
├───────────────────────────────────────────────┤
│ Flash app 'demo-api' created successfully     │
│                                               │
│ App ID: app_xyz789                            │
╰───────────────────────────────────────────────╯
```

### Get App Details

```bash
$ flash app get my-api

╭─────────────────────────────────╮
│ 📱 Flash App: my-api            │
├─────────────────────────────────┤
│ Name: my-api                    │
│ ID: app_abc123                  │
│ Environments: 3                 │
│ Builds: 5                       │
╰─────────────────────────────────╯

              Environments
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Name       ┃ ID                 ┃ State   ┃ Active Build     ┃ Created          ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ dev        │ env_dev123         │ DEPLOYED│ build_latest     │ 2024-01-15 10:30 │
│ staging    │ env_stg456         │ DEPLOYED│ build_v2         │ 2024-01-16 14:20 │
│ production │ env_prd789         │ DEPLOYED│ build_v1         │ 2024-01-20 09:15 │
└────────────┴────────────────────┴─────────┴──────────────────┴──────────────────┘

                     Builds
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ ID                 ┃ Status                   ┃ Created          ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ build_latest       │ COMPLETED                │ 2024-01-20 09:00 │
│ build_v2           │ COMPLETED                │ 2024-01-18 15:45 │
│ build_v1           │ COMPLETED                │ 2024-01-15 11:20 │
└────────────────────┴──────────────────────────┴──────────────────┘
```

### Delete App

```bash
$ flash app delete --app old-project

╭───────────────────────────────────────╮
│ Delete Confirmation                   │
├───────────────────────────────────────┤
│ App 'old-project' will be deleted     │
│                                       │
│ App ID: app_old123                    │
│ Environments: 2                       │
│ Builds: 3                             │
│                                       │
│ This will delete ALL environments,    │
│ endpoints, volumes, and builds!       │
╰───────────────────────────────────────╯

? Are you sure you want to delete app 'old-project'? Yes

Deleting environment 'dev'...
Undeploying 2 resource(s)...
Environment 'dev' deleted successfully

Deleting environment 'staging'...
Undeploying 2 resource(s)...
Environment 'staging' deleted successfully

Deleting builds...
Deleted 3 build(s)

App 'old-project' deleted successfully
```

## Best Practices

### Naming Conventions

Use clear, descriptive names that reflect the project:

```bash
# Good
flash app create user-api
flash app create ml-inference
flash app create data-pipeline

# Avoid
flash app create app1
flash app create test
flash app create abc
```

### App Organization Strategies

**Single app per project (recommended for most cases):**
```bash
my-project/
└── Flash App: my-project
    ├── Environment: dev
    ├── Environment: staging
    └── Environment: production
```

**Multiple apps for microservices:**
```bash
# Separate apps for each service
flash app create auth-service
flash app create payment-service
flash app create notification-service

# Each has its own lifecycle
flash deploy --app auth-service --env prod
flash deploy --app payment-service --env prod
```

**App per team or feature:**
```bash
# Team-based
flash app create frontend-team-app
flash app create backend-team-app

# Feature-based (temporary)
flash app create feature-search
flash app create feature-recommendations
```

### App Lifecycle Management

1. **Development Phase**:
   - Create app: `flash app create my-project`
   - Create dev environment: `flash env create dev`
   - Deploy and test: `flash deploy --env dev`

2. **Staging Phase**:
   - Create staging environment: `flash env create staging`
   - Deploy for QA: `flash deploy --env staging`

3. **Production Phase**:
   - Create production environment: `flash env create production`
   - Deploy to prod: `flash deploy --env production`

4. **Maintenance**:
   - Monitor: `flash app get my-project`
   - Update: `flash deploy --env <env>`
   - Scale: Adjust resource configs

5. **Cleanup**:
   - Delete unused environments: `flash env delete <name>`
   - Delete entire app: `flash app delete --app my-project`

### Resource Management

- **Monitor app usage**: Use `flash app get` to track environments and builds
- **Clean up old builds**: Builds accumulate over time
- **Delete unused apps**: Remove apps you're no longer using
- **Check costs**: Each app's resources contribute to your RunPod usage

### Safety Features

App deletion includes safety features:
- **Confirmation prompt**: Required for all app deletions
- **Cascade delete**: Automatically removes all environments and resources
- **Validation**: Ensures all resources are properly cleaned up
- **Abort on failure**: If any resource fails to delete, operation is aborted

## Troubleshooting

### App Not Found

**Problem**: `Error: App 'my-project' not found`

**Solution**: List apps to verify name:
```bash
flash app list
```

Create if missing:
```bash
flash app create my-project
```

### App Name Conflict

**Problem**: `Error: App 'my-project' already exists`

**Solution**: Choose a different name or use existing app:
```bash
# Use existing app
flash deploy --app my-project

# Or create with different name
flash app create my-project-v2
```

### Cannot Delete App

**Problem**: App deletion fails with resource errors

**Solution**: Manually delete environments first:
```bash
# List environments
flash env list --app my-project

# Delete each environment
flash env delete dev --app my-project
flash env delete staging --app my-project

# Then delete app
flash app delete --app my-project
```

### App Auto-Detection Fails

**Problem**: Commands don't detect app from current directory

**Solution**: Specify app explicitly:
```bash
flash env list --app my-project
flash deploy --app my-project
```

Or ensure you're in a valid Flash project directory with:
- `main.py` with Flash server
- `workers/` directory
- Proper project structure

### Multiple Apps With Same Name

**Problem**: Multiple people on team created apps with same name

**Solution**: Apps are namespaced to your account, so this shouldn't happen. If confused:
```bash
# List all your apps
flash app list

# Use app ID instead of name if needed
flash app get <app-id>
```

## Related Commands

- [flash deploy](./flash-deploy.md) - Build and deploy to app/environment
- [flash env](./flash-env.md) - Manage app environments
- [flash build](./flash-build.md) - Create build artifacts
- [flash init](./flash-init.md) - Initialize new Flash project
