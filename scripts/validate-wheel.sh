#!/bin/bash
# Validate that wheel packaging includes all necessary template files

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Building wheel..."
uv build

WHEEL_FILE=$(ls -t dist/runpod_flash-*.whl | head -1)
echo "Testing wheel: $WHEEL_FILE"
echo ""

# Check wheel contents without installing
echo "Checking wheel contents..."
REQUIRED_TEMPLATE_FILES=(
    "runpod_flash/cli/utils/skeleton_template/.env.example"
    "runpod_flash/cli/utils/skeleton_template/.gitignore"
    "runpod_flash/cli/utils/skeleton_template/.flashignore"
    "runpod_flash/cli/utils/skeleton_template/cpu_worker.py"
    "runpod_flash/cli/utils/skeleton_template/gpu_worker.py"
    "runpod_flash/cli/utils/skeleton_template/lb_worker.py"
    "runpod_flash/cli/utils/skeleton_template/pyproject.toml"
    "runpod_flash/cli/utils/skeleton_template/README.md"
    "runpod_flash/cli/utils/skeleton_template/requirements.txt"
)

MISSING_IN_WHEEL=0
for file in "${REQUIRED_TEMPLATE_FILES[@]}"; do
    if unzip -l "$WHEEL_FILE" | grep -q "$file"; then
        echo "[OK] $file"
    else
        echo "[MISSING] $file"
        MISSING_IN_WHEEL=$((MISSING_IN_WHEEL + 1))
    fi
done

if [ $MISSING_IN_WHEEL -gt 0 ]; then
    echo ""
    echo "ERROR: Wheel validation failed: $MISSING_IN_WHEEL file(s) missing from wheel"
    exit 1
fi

echo ""
echo "Creating test environment..."
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

# Use project's Python from .venv if available, otherwise find best system python3
if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON_CMD="$PROJECT_DIR/.venv/bin/python"
else
    # Find the highest available python3.x interpreter
    PYTHON_CMD=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3.9 || command -v python3)
    if [ -z "$PYTHON_CMD" ]; then
        echo "ERROR: No python3 interpreter found in PATH"
        exit 1
    fi
fi

echo "Using Python: $($PYTHON_CMD --version)"
$PYTHON_CMD -m venv test_env
source test_env/bin/activate

echo "Installing wheel..."
pip install -q "$PROJECT_DIR/$WHEEL_FILE"

echo "Testing flash init..."
flash init test_project > /dev/null 2>&1

# Verify critical files exist
echo ""
echo "Verifying created files..."
REQUIRED_FILES=(".env.example" ".gitignore" ".flashignore" "cpu_worker.py" "gpu_worker.py" "lb_worker.py" "pyproject.toml" "README.md" "requirements.txt")
MISSING_IN_OUTPUT=0

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "test_project/$file" ]; then
        # Check file is not empty
        if [ -s "test_project/$file" ]; then
            echo "[OK] $file ($(wc -c < "test_project/$file") bytes)"
        else
            echo "[WARN] $file (EMPTY)"
        fi
    else
        echo "[MISSING] $file"
        MISSING_IN_OUTPUT=$((MISSING_IN_OUTPUT + 1))
    fi
done

# Cleanup
deactivate
cd - > /dev/null
rm -rf "$TEMP_DIR"

echo ""
if [ $MISSING_IN_OUTPUT -gt 0 ]; then
    echo "ERROR: Validation failed: $MISSING_IN_OUTPUT file(s) missing in flash init output"
    exit 1
else
    echo "SUCCESS: Wheel validation passed"
    echo ""
    echo "Summary:"
    echo "  - All template files present in wheel"
    echo "  - All files created by flash init"
    echo "  - Hidden files (.env, .gitignore, etc.) working correctly"
fi
