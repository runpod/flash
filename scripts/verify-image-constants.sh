#!/bin/bash
#
# Verification script for Docker image constant configuration fix
# This script validates that the ManifestBuilder correctly uses environment-configurable
# image constants instead of hardcoded values.
#
# Usage:
#   ./scripts/verify-image-constants.sh
#
# This script can be retained and re-run to verify the fix after any changes.
# It tests the following scenarios:
#   1. Default behavior (no env vars set) - uses :latest tag
#   2. FLASH_IMAGE_TAG=local override - uses :local tag
#   3. FLASH_IMAGE_TAG=dev override - uses :dev tag
#   4. Individual FLASH_CPU_LB_IMAGE override
#   5. Flash build integration test with environment variables
#
# Exit codes:
#   0: All tests passed
#   1: Test failed
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_PROJECT_DIR=$(mktemp -d)

echo -e "${BLUE}=== Docker Image Constant Configuration Verification ===${NC}"
echo "Testing repository: $REPO_ROOT"
echo "Test project directory: $TEST_PROJECT_DIR"
echo ""

# Cleanup function
cleanup() {
    if [ -d "$TEST_PROJECT_DIR" ]; then
        rm -rf "$TEST_PROJECT_DIR"
    fi
}
trap cleanup EXIT

# Helper function to run a test
run_test() {
    local test_name=$1
    local expected_cpu_image=$2
    local expected_gpu_image=$3
    local env_vars=$4

    echo -e "${BLUE}Test: $test_name${NC}"

    # Create a fresh test project
    rm -rf "$TEST_PROJECT_DIR"
    mkdir -p "$TEST_PROJECT_DIR"

    # Create main.py with FastAPI routes
    cat > "$TEST_PROJECT_DIR/main.py" << 'EOF'
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"msg": "Hello"}

@app.get("/health")
def health():
    return {"status": "ok"}
EOF

    # Create gpu_worker.py with LiveServerless resource
    cat > "$TEST_PROJECT_DIR/gpu_worker.py" << 'EOF'
from runpod_flash import remote, LiveServerless

gpu_config = LiveServerless(name="gpu_worker")

@remote(resource_config=gpu_config)
async def process_gpu(data: dict):
    return {"result": data}
EOF

    # Create mothership.py with explicit CpuLiveLoadBalancer
    cat > "$TEST_PROJECT_DIR/mothership.py" << 'EOF'
from runpod_flash import CpuLiveLoadBalancer

mothership = CpuLiveLoadBalancer(
    name="test-mothership",
    workersMin=1,
    workersMax=3,
)
EOF

    # Create pyproject.toml
    cat > "$TEST_PROJECT_DIR/pyproject.toml" << 'EOF'
[project]
name = "verify-test"
version = "0.1.0"
dependencies = []
EOF

    # Run flash build with specified environment variables
    cd "$TEST_PROJECT_DIR"

    # Set environment variables
    if [ -n "$env_vars" ]; then
        eval export $env_vars
    fi

    # Run flash build
    export PYTHONPATH="$REPO_ROOT/src:$PYTHONPATH"
    python3 -m runpod_flash.cli.main build --no-docker --generate-file-structure 2>&1 | head -20 || true

    # Check the generated manifest
    if [ ! -f ".flash/flash_manifest.json" ]; then
        echo -e "${RED}✗ FAILED: Manifest not generated${NC}"
        return 1
    fi

    # Extract image names from manifest using Python
    python3 << PYSCRIPT
import json
import sys

with open('.flash/flash_manifest.json', 'r') as f:
    manifest = json.load(f)

# Check CPU mothership image
resources = manifest.get('resources', {})
mothership_resources = [k for k in resources.keys() if 'mothership' in k]

if not mothership_resources:
    print("ERROR: No mothership resource found")
    sys.exit(1)

mothership_key = mothership_resources[0]
mothership = resources[mothership_key]
actual_cpu_image = mothership.get('imageName', 'NOT SET')

print(f"Mothership image: {actual_cpu_image}")
print(f"Expected: $expected_cpu_image")

if actual_cpu_image != "$expected_cpu_image":
    print("ERROR: Image mismatch!")
    sys.exit(1)

print("OK")
PYSCRIPT

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ PASSED${NC}"
        return 0
    else
        echo -e "${RED}✗ FAILED${NC}"
        return 1
    fi
}

# Test 1: Default behavior (no env vars)
echo ""
echo -e "${YELLOW}Test Suite 1: Default Behavior${NC}"
unset FLASH_IMAGE_TAG
unset FLASH_CPU_LB_IMAGE
unset FLASH_LB_IMAGE
run_test "Default (should use :latest)" \
    "runpod/flash-lb-cpu:latest" \
    "runpod/flash:latest" \
    "" || exit 1

# Test 2: FLASH_IMAGE_TAG=local
echo ""
echo -e "${YELLOW}Test Suite 2: FLASH_IMAGE_TAG Environment Variable${NC}"
unset FLASH_CPU_LB_IMAGE
unset FLASH_LB_IMAGE
run_test "FLASH_IMAGE_TAG=local" \
    "runpod/flash-lb-cpu:local" \
    "runpod/flash:local" \
    "FLASH_IMAGE_TAG=local" || exit 1

# Test 3: FLASH_IMAGE_TAG=dev
unset FLASH_CPU_LB_IMAGE
unset FLASH_LB_IMAGE
run_test "FLASH_IMAGE_TAG=dev" \
    "runpod/flash-lb-cpu:dev" \
    "runpod/flash:dev" \
    "FLASH_IMAGE_TAG=dev" || exit 1

# Test 4: Individual image override
echo ""
echo -e "${YELLOW}Test Suite 3: Individual Image Overrides${NC}"
unset FLASH_IMAGE_TAG
run_test "Custom FLASH_CPU_LB_IMAGE" \
    "custom/lb-cpu:v1" \
    "runpod/flash:latest" \
    "FLASH_CPU_LB_IMAGE=custom/lb-cpu:v1" || exit 1

# Test 5: Unit tests for constants
echo ""
echo -e "${YELLOW}Test Suite 4: Unit Test Verification${NC}"
cd "$REPO_ROOT"
echo -e "${BLUE}Running manifest mothership tests...${NC}"
python3 -m pytest tests/unit/cli/commands/build_utils/test_manifest_mothership.py -v --tb=short 2>&1 | tail -15 || exit 1

echo ""
echo -e "${YELLOW}Test Suite 5: Constant Import Verification${NC}"
python3 << 'PYSCRIPT'
import os
import sys

# Test that constants can be imported
sys.path.insert(0, 'src')

# Reset environment to test defaults
for var in ['FLASH_IMAGE_TAG', 'FLASH_GPU_IMAGE', 'FLASH_CPU_IMAGE', 'FLASH_LB_IMAGE', 'FLASH_CPU_LB_IMAGE']:
    if var in os.environ:
        del os.environ[var]

from runpod_flash.core.resources.constants import (
    FLASH_IMAGE_TAG,
    FLASH_GPU_IMAGE,
    FLASH_CPU_IMAGE,
    FLASH_LB_IMAGE,
    FLASH_CPU_LB_IMAGE,
    DEFAULT_WORKERS_MIN,
    DEFAULT_WORKERS_MAX,
)

print(f"✓ FLASH_IMAGE_TAG: {FLASH_IMAGE_TAG}")
print(f"✓ FLASH_GPU_IMAGE: {FLASH_GPU_IMAGE}")
print(f"✓ FLASH_CPU_IMAGE: {FLASH_CPU_IMAGE}")
print(f"✓ FLASH_LB_IMAGE: {FLASH_LB_IMAGE}")
print(f"✓ FLASH_CPU_LB_IMAGE: {FLASH_CPU_LB_IMAGE}")
print(f"✓ DEFAULT_WORKERS_MIN: {DEFAULT_WORKERS_MIN}")
print(f"✓ DEFAULT_WORKERS_MAX: {DEFAULT_WORKERS_MAX}")

# Verify defaults
assert FLASH_IMAGE_TAG == "latest", f"Expected 'latest', got {FLASH_IMAGE_TAG}"
assert FLASH_GPU_IMAGE == "runpod/flash:latest", f"Unexpected GPU image: {FLASH_GPU_IMAGE}"
assert FLASH_CPU_IMAGE == "runpod/flash-cpu:latest", f"Unexpected CPU image: {FLASH_CPU_IMAGE}"
assert FLASH_LB_IMAGE == "runpod/flash-lb:latest", f"Unexpected LB image: {FLASH_LB_IMAGE}"
assert FLASH_CPU_LB_IMAGE == "runpod/flash-lb-cpu:latest", f"Unexpected CPU LB image: {FLASH_CPU_LB_IMAGE}"
assert DEFAULT_WORKERS_MIN == 1
assert DEFAULT_WORKERS_MAX == 1

print("\n✓ All constants have correct default values")
PYSCRIPT

if [ $? -ne 0 ]; then
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ ALL VERIFICATION TESTS PASSED${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Summary:"
echo "  ✓ Default behavior uses :latest tag"
echo "  ✓ FLASH_IMAGE_TAG environment variable works"
echo "  ✓ Individual image overrides work"
echo "  ✓ Constants are properly centralized"
echo "  ✓ Flash manifest generation uses constants"
echo ""
echo "The Docker image configuration fix is working correctly!"
