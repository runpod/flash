# Diagnostic Logging Guide - State Manager Sync Debugging

## Overview

This guide explains how to use the newly added diagnostic logging to trace the State Manager manifest sync flow and identify why `resources_endpoints` may be missing at runtime.

**Commit:** 1ca15e0 - "feat: add diagnostic logging for State Manager sync debugging"

## Problem Context

After deployment, remote function calls fail with:
```
RuntimeError: Remote function 'gpu_info' endpoint not found in manifest
```

This indicates State Manager is returning empty `resources_endpoints` even though the deployment appeared successful. The root cause could be:

1. **Environment ID Mismatch** - Different IDs used during write vs read
2. **Race Condition** - Environment activated before resources provisioned
3. **Wrong Build** - `activeBuildId` points to an older build without endpoints
4. **Upload Failure** - GraphQL mutation returned success but data wasn't persisted

## Diagnostic Flow

### Phase 1: WRITE PATH (Deployment → State Manager)

When you run `flash deploy`, these log statements appear:

```
[DEPLOY SYNC] resources_endpoints mapping: {
  "resource_name": "https://api.runpod.io/...",
  ...
}

[DEPLOY SYNC] Uploading manifest to State Manager - build_id=abc123, environment_id=env456

[DEPLOY SYNC] Manifest contains resources_endpoints: {...}

[STATE MANAGER] GraphQL mutation succeeded for build_id=abc123

[STATE MANAGER] Uploaded manifest with keys: ['resources_endpoints', 'functions', ...]

[STATE MANAGER] Uploaded 2 endpoints: ['resource_1', 'resource_2']

[DEPLOY] Environment env456 activated with build_id=abc123
```

### Phase 2: READ PATH (Runtime → State Manager)

When the mothership makes a request triggering a remote call:

```
[RUNTIME SYNC] Querying State Manager with environment_id=env456

[RUNTIME SYNC] FLASH_ENVIRONMENT_ID=env456, RUNPOD_ENDPOINT_ID=(null)

[STATE MANAGER] environment_id=env456 → activeBuildId=abc123

[STATE MANAGER] Retrieved build abc123, manifest keys: ['resources_endpoints', 'functions', ...]

[STATE MANAGER] Manifest has 2 endpoints: ['resource_1', 'resource_2']

[RUNTIME SYNC] Received manifest with keys: ['resources_endpoints', 'functions', ...]

[RUNTIME SYNC] resources_endpoints contains 2 entries: ['resource_1', 'resource_2']
```

## Step-by-Step Testing

### 1. Collect Deployment Logs

```bash
cd flash-examples/03_advanced_workers/05_load_balancer

# Deploy with full logging
flash deploy --use-local-flash 2>&1 | tee deploy.log

# Extract key diagnostic lines
grep "\[DEPLOY\|STATE MANAGER\]" deploy.log
```

Expected output in deploy.log:
- `[DEPLOY SYNC] resources_endpoints mapping:` - Confirm endpoints were built
- `[STATE MANAGER] Uploaded X endpoints:` - Confirm upload succeeded
- `[DEPLOY] Environment activated with build_id=` - Confirm environment activated

### 2. Extract Critical IDs from Deployment

```bash
# Find the build_id and environment_id
grep "build_id=" deploy.log | head -1
grep "environment_id=" deploy.log | head -1

# Example output:
# 📤 DEPLOY SYNC: ... build_id=abc123 ...
# 📤 DEPLOY SYNC: ... environment_id=env456 ...
```

**Important:** Note these values for verification later.

### 3. Test Runtime with Remote Calls

```bash
# Get the mothership port from deploy output
MOTHERSHIP_PORT=$(grep "Mothership" deploy.log | grep -oP ':\K\d+' | head -1)

# Make a request that triggers a remote function
curl http://localhost:${MOTHERSHIP_PORT}/gpu/info

# Capture output
curl http://localhost:${MOTHERSHIP_PORT}/gpu/info 2>&1 | tee runtime_output.log
```

### 4. Collect Container Logs

```bash
# Get mothership container ID
CONTAINER_ID=$(docker ps | grep mothership | awk '{print $1}')

# Get logs with diagnostic entries
docker logs ${CONTAINER_ID} 2>&1 | grep "\[RUNTIME\|STATE MANAGER\]" | tee mothership_logs.log
```

### 5. Verify ID Matching

Compare the IDs across logs:

```bash
# From deployment
DEPLOY_BUILD_ID=$(grep "\[DEPLOY SYNC\]" deploy.log | grep -oP "build_id=\K\w+" | head -1)
DEPLOY_ENV_ID=$(grep "\[DEPLOY SYNC\]" deploy.log | grep -oP "environment_id=\K\w+" | head -1)

# From runtime
RUNTIME_ENV_ID=$(grep "\[RUNTIME SYNC\]: Querying" mothership_logs.log | grep -oP "environment_id=\K\w+" | head -1)
STATE_MGR_BUILD_ID=$(grep "\[STATE MANAGER\]: environment_id" mothership_logs.log | grep -oP "activeBuildId=\K\w+" | head -1)

# Print comparison
echo "Deployment:"
echo "  build_id: $DEPLOY_BUILD_ID"
echo "  environment_id: $DEPLOY_ENV_ID"
echo ""
echo "Runtime:"
echo "  environment_id: $RUNTIME_ENV_ID"
echo "  activeBuildId: $STATE_MGR_BUILD_ID"
echo ""
echo "ID Matching:"
echo "  build_id → activeBuildId: $([ "$DEPLOY_BUILD_ID" = "$STATE_MGR_BUILD_ID" ] && echo "✓ MATCH" || echo "✗ MISMATCH")"
echo "  environment_id match: $([ "$DEPLOY_ENV_ID" = "$RUNTIME_ENV_ID" ] && echo "✓ MATCH" || echo "✗ MISMATCH")"
```

## Diagnostic Scenarios

### Scenario 1: IDs Don't Match

**Log shows:**
```
[DEPLOY] Environment {env_name} activated with build_id=abc123
[STATE MANAGER] environment_id=xyz789 → activeBuildId=abc123
```

**Root Cause:** `FLASH_ENVIRONMENT_ID` environment variable is incorrect at runtime.

**Solution:** Check `mothership_provisioner.py` to verify `FLASH_ENVIRONMENT_ID` is set with the correct value.

### Scenario 2: Wrong Build Deployed

**Log shows:**
```
[DEPLOY] Environment env456 activated with build_id=abc123
[STATE MANAGER] environment_id=env456 → activeBuildId=old789
```

**Root Cause:** Environment's `activeBuildId` wasn't updated to the new build.

**Solution:** Check `deploy_build_to_environment()` to verify the GraphQL mutation succeeded and returned the correct build ID.

### Scenario 3: Manifest Upload Failed

**Log shows:**
```
[DEPLOY SYNC] Uploading manifest to State Manager - build_id=abc123
[STATE MANAGER] GraphQL mutation succeeded for build_id=abc123
[STATE MANAGER] Manifest MISSING resources_endpoints!
```

**Root Cause:** GraphQL mutation claims success but didn't actually persist the data.

**Solution:**
- Check State Manager backend logs for errors
- Verify manifest wasn't too large or contained invalid data
- Add retry logic to the update_build_manifest call

### Scenario 4: Race Condition Detected

**Log shows:**
```
[DEPLOY] Environment env456 activated with build_id=abc123
[DEPLOY SYNC] Uploading manifest to State Manager...
[STATE MANAGER] Uploaded X endpoints
```

**Root Cause:** Environment activated BEFORE resources were provisioned.

**Solution:** In `deployment.py`, reorder the flow:
1. Build and upload manifest to State Manager FIRST
2. Then activate the environment

## Log File Structure

### Deployment Logs

Look for these patterns in order:

```
1. Resource provisioning:
   "[DEPLOY SYNC] resources_endpoints mapping:"

2. Manifest preparation:
   "[DEPLOY SYNC] Uploading manifest to State Manager"

3. GraphQL upload:
   "[STATE MANAGER] Uploaded X endpoints"

4. Environment activation:
   "[DEPLOY] Environment X activated with build_id=Y"
```

### Runtime Logs

Look for these patterns in order:

```
1. Environment ID retrieval:
   "[RUNTIME SYNC] Querying State Manager with environment_id="

2. Build lookup:
   "[STATE MANAGER] environment_id=X → activeBuildId=Y"

3. Manifest fetch:
   "[STATE MANAGER] Retrieved build X, manifest keys:"

4. Endpoint verification:
   "[STATE MANAGER] Manifest has N endpoints:"
```

## Interpreting Empty Endpoints

If you see:
```
[STATE MANAGER] Manifest MISSING resources_endpoints!
Full manifest keys: [...]
```

This means the manifest exists but doesn't have `resources_endpoints`. Check:

1. Was the manifest uploaded during deployment? (Look for "[DEPLOY SYNC] Uploaded X endpoints")
2. Is the same build ID being queried? (Compare build IDs)
3. Did the upload succeed? (Look for "[STATE MANAGER] GraphQL mutation succeeded")

## Tools for Log Analysis

### Extract all diagnostic lines:
```bash
grep "\[DEPLOY\|STATE MANAGER\|RUNTIME\]" deployment.log mothership_logs.log | sort
```

### Check for errors or warnings:
```bash
grep -i "missing\|error\|failed\|warning" mothership_logs.log
```

### Timeline reconstruction:
```bash
cat deploy.log mothership_logs.log | grep -E "^\[" | sort
```

## Expected Success Output

When everything works correctly, you should see:

**Deployment:**
- PASS: `[DEPLOY SYNC] resources_endpoints mapping:` contains entries
- PASS: `[STATE MANAGER] Uploaded N endpoints:` where N > 0
- PASS: `[DEPLOY] Environment X activated with build_id=Y`

**Runtime:**
- PASS: `[RUNTIME SYNC] Querying State Manager with environment_id=`
- PASS: `[STATE MANAGER] environment_id=X → activeBuildId=Y` (matches deployment)
- PASS: `[STATE MANAGER] Manifest has N endpoints:` where N > 0
- PASS: `[RUNTIME SYNC] resources_endpoints contains N entries:` where N > 0

## Next Steps If Diagnosis Fails

If logs don't clearly identify the issue:

1. Enable verbose logging in State Manager client
2. Add logging to `get_flash_environment()` and `get_flash_build()` queries
3. Inspect the actual GraphQL responses in State Manager
4. Check if manifest is being corrupted during serialization/deserialization

## Related Files

- `src/runpod_flash/cli/utils/deployment.py` - Deployment flow with write logs
- `src/runpod_flash/core/api/runpod.py` - GraphQL mutation with upload logs
- `src/runpod_flash/runtime/service_registry.py` - Runtime load with read logs
- `src/runpod_flash/runtime/state_manager_client.py` - State Manager queries with mapping logs
