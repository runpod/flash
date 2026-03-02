# flash undeploy

Manage and delete Runpod serverless endpoints deployed via Flash.

## Overview

The `flash undeploy` command helps you clean up Serverless endpoints that Flash has created when you ran/deployed a `@remote` function using `flash run` or `flash deploy`. It manages endpoints recorded in `.flash/resources.pkl` and ensures both the cloud resources and local tracking state stay in sync.

### When To Use This Command

- Cleaning up individual endpoints you no longer need
- Removing endpoints after local development/testing

### `flash undeploy` vs `flash env delete`

| Command | Scope | When to use |
|---------|-------|----------|
| `flash undeploy` | Individual endpoints from local tracking | Granular cleanup, development endpoints |
| `flash env delete` | Entire environment + all its resources | Production cleanup, full teardown |

For production deployments, use `flash env delete` to remove the entire environment and all associated resources automatically.

### How Endpoint Tracking Works

Flash tracks deployed endpoints in `.flash/resources.pkl`. Endpoints get added to this file when you:
- Run `flash run --auto-provision` (local development)
- Run `flash deploy` (production deployment)

## Synopsis

```bash
flash undeploy [NAME|list] [OPTIONS]
```

## Usage Modes

### List Endpoints

Display all tracked endpoints with their current status:

```bash
flash undeploy list
```

**Output includes:**
- Name: Endpoint name
- Endpoint ID: Runpod endpoint identifier
- Status: Current health status (Active/Inactive/Unknown)
- Type: Resource type (Live Serverless, Cpu Live Serverless, etc.)
- Resource ID: Internal tracking identifier

**Status Indicators:**
- 🟢 **Active**: Endpoint is running and responding to health checks
- 🔴 **Inactive**: Endpoint tracking exists but health check fails (likely deleted externally)
- ❓ **Unknown**: Exception occurred during health check

### Undeploy by Name

Delete a specific endpoint:

```bash
flash undeploy my-api
```

**Behavior:**
1. Searches for endpoints matching the name
2. Shows endpoint details
3. Prompts for confirmation
4. Deletes endpoint from Runpod
5. Removes from local tracking

### Undeploy All

Delete all tracked endpoints with double confirmation:

```bash
flash undeploy --all
```

**Safety features:**
1. Shows total count of endpoints
2. First confirmation: Yes/No prompt
3. Second confirmation: Type "DELETE ALL" exactly
4. Deletes all endpoints from Runpod
5. Removes all from tracking

### Interactive Selection

Select endpoints to undeploy using checkboxes:

```bash
flash undeploy --interactive
```

**Behavior:**
1. Displays interactive list with checkboxes
2. Use arrow keys to navigate
3. Use space bar to select/deselect
4. Press Enter to confirm selection
5. Prompts for final confirmation
6. Deletes selected endpoints

### Cleanup Stale Tracking

Remove inactive endpoints from tracking without API deletion:

```bash
flash undeploy --cleanup-stale
```

**Use case:** When endpoints are deleted via Runpod UI or API (not through Flash), the tracking file becomes stale. This command identifies and removes those orphaned entries.

**Behavior:**
1. Checks health status of all tracked endpoints
2. Identifies inactive endpoints
3. Lists inactive endpoints for review
4. Prompts for confirmation
5. Removes only from local tracking (endpoints already deleted)

## Options

- `--all`: Undeploy all endpoints (requires double confirmation)
- `--interactive, -i`: Interactive checkbox selection
- `--cleanup-stale`: Remove inactive endpoints from tracking

## Examples

### Basic Workflow

```bash
# Check what's deployed
flash undeploy list

# Remove a specific endpoint
flash undeploy my-api

# Clean up stale tracking
flash undeploy --cleanup-stale
```

### Bulk Operations

```bash
# Undeploy all endpoints
flash undeploy --all

# Interactive selection for partial cleanup
flash undeploy --interactive
```

### Managing External Deletions

If you delete endpoints via Runpod UI:

```bash
# Check status - will show as "Inactive"
flash undeploy list

# Remove stale tracking entries
flash undeploy --cleanup-stale
```

## Understanding Status Checks

The Status column performs a health check API call for each endpoint. This:
- Adds latency (1 API call per endpoint)
- Provides accurate current state
- Identifies endpoints deleted externally

**Why it's valuable:**
- Catches endpoints deleted via Runpod UI
- Identifies unhealthy endpoints
- Prevents stale tracking file issues

## Safety Features

### Confirmations
- All deletion operations require explicit confirmation
- `--all` requires double confirmation with exact text match
- Interactive mode shows count before deletion

### Warnings
- Clear indication that operations cannot be undone
- Displays endpoint details before deletion
- Shows success/failure counts after operations

### Error Handling
- Continues processing remaining endpoints if one fails
- Shows detailed error messages per endpoint
- Tracks success/failure counts in summary

## Tracking File

Endpoints are tracked in `.flash/resources.pkl`.

**Important:**
- This file is in `.gitignore` (never commit)
- Contains local deployment state
- Use `flash undeploy --cleanup-stale` to maintain accuracy
- `make clean` no longer deletes this file (use flash undeploy instead)

## Integration with @remote

When you use the `@remote` decorator:

```python
from runpod_flash import remote, LiveServerless

@remote(resource_config=LiveServerless(name="my-api"))
def my_function(data):
    return {"result": data}
```

Flash automatically:
1. Deploys endpoint to Runpod
2. Tracks in `.flash/resources.pkl`
3. Reuses endpoint on subsequent calls

To clean up:
```bash
flash undeploy my-api
```

## Troubleshooting

### Endpoint shows as "Inactive"

**Cause:** Endpoint was deleted via Runpod UI/API

**Solution:**
```bash
flash undeploy --cleanup-stale
```

### Can't find endpoint by name

**Symptoms:** "No endpoint found with name 'my-api'"

**Solution:** Check exact name with:
```bash
flash undeploy list
```

### Undeploy fails with API error

**Cause:** Network issues or invalid API key

**Solution:**
1. Check `RUNPOD_API_KEY` in `.env`
2. Verify network connectivity
3. Check endpoint still exists on Runpod

## Related Commands

- `flash init` - Initialize new project
- `flash run` - Run development server
- `flash build` - Build deployment packages
- `flash deploy` - Deploy to Runpod

## See Also

- [Flash CLI Overview](./README.md)
- [Runpod Serverless Documentation](https://docs.runpod.io/serverless/overview)
- [Flash Documentation](../../../README.md)
