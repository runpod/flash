# flash build

Build Flash application for deployment.

## Usage

```bash
flash build [OPTIONS]
```

## Options

- `--no-deps`: Skip transitive dependencies during pip install (default: false)
- `--keep-build`: Keep `.flash/.build` directory after creating archive (default: false)
- `--output, -o`: Custom archive name (default: artifact.tar.gz)
- `--exclude`: Comma-separated packages to exclude (e.g., 'torch,torchvision')
- `--preview`: Launch local test environment after successful build (auto-enables `--keep-build`)

## Examples

```bash
# Build with all dependencies
flash build

# Skip transitive dependencies
flash build --no-deps

# Keep temporary build directory for inspection
flash build --keep-build

# Build and launch local test environment
flash build --preview

# Custom output filename
flash build --output my-app.tar.gz

# Combine options
flash build --keep-build --output deploy.tar.gz
```

## What It Does

The build process packages your Flash application into a self-contained deployment package:

1. **Discovery**: Scans your project for `@remote` decorated functions
2. **Grouping**: Groups functions by their `resource_config`
3. **Manifest Creation**: Generates `flash_manifest.json` for service discovery
4. **Dependency Installation**: Installs all Python dependencies locally
5. **Packaging**: Creates `.flash/artifact.tar.gz` ready for deployment

## Build Artifacts

After `flash build` completes:

| File/Directory | Purpose |
|---|---|
| `.flash/artifact.tar.gz` | Deployment package (ready for RunPod) |
| `.flash/flash_manifest.json` | Service discovery configuration |
| `.flash/.build/` | Temporary build directory (removed unless `--keep-build` specified) |

## Dependency Management

### Cross-Platform Builds

Flash automatically handles cross-platform builds, ensuring compatibility with RunPod's Linux x86_64 serverless infrastructure:

- **Automatic Platform Targeting**: Dependencies are always installed for Linux x86_64, regardless of your build platform (macOS, Windows, or Linux)
- **Python Version Matching**: Uses your current Python version to ensure package compatibility
- **Binary Wheel Enforcement**: Only pre-built binary wheels are used, preventing platform-specific compilation issues

This means you can safely build on macOS ARM64, Windows, or any platform, and the deployment will work correctly on RunPod.

### Default Behavior

```bash
flash build
```

Installs all dependencies specified in your project (including transitive dependencies):
- Installs Linux x86_64 compatible packages
- Includes exact versions from `requirements.txt` or `pyproject.toml`
- All packages become local modules in the deployment

### Skip Transitive Dependencies

```bash
flash build --no-deps
```

Only installs direct dependencies specified in `@remote` decorators:
- Faster builds for large projects
- Smaller deployment packages
- Useful when base image already includes dependencies

## Preview Environment

```bash
flash build --preview
```

Launch a local Docker-based test environment immediately after building. This allows you to test your distributed system locally before deploying to RunPod.

**What happens:**
1. Builds your project (creates archive, manifest)
2. Creates a Docker network for inter-container communication
3. Starts one Docker container per resource config:
   - Mothership container (orchestrator)
   - All worker containers (GPU, CPU, etc.)
4. Exposes the mothership on `localhost:8000`
5. All containers communicate via Docker DNS
6. On shutdown (Ctrl+C), automatically stops and removes all containers

**When to use:**
- Test deployment before production
- Validate manifest structure
- Debug resource provisioning
- Verify endpoint auto-discovery
- Test distributed function calls

**Note:** `--preview` automatically enables `--keep-build` since the preview needs the build directory.

## Keep Build Directory

```bash
flash build --keep-build
```

Preserves `.flash/.build/` directory for inspection:
- Useful for debugging build issues
- Check manifest structure
- Verify packaged files
- Clean up manually when done

## Cross-Endpoint Function Calls

When your application has functions on multiple endpoints (GPU and CPU, for example), the build process creates a manifest that enables functions to call each other:

```python
# CPU endpoint function
@remote(resource_config=cpu_config)
def preprocess(data):
    return clean_data

# GPU endpoint function
@remote(resource_config=gpu_config)
async def inference(data):
    # Calls CPU endpoint function
    clean = preprocess(data)
    return results
```

The manifest and runtime wrapper handle service discovery and routing automatically.

## Output

Successful build displays:

```
╭───────────────────────── Flash Build Configuration ──────────────────────────╮
│ Project: my-project                                                          │
│ Directory: /path/to/project                                                  │
│ Archive: .flash/artifact.tar.gz                                              │
│ Skip transitive deps: False                                                  │
│ Keep build dir: False                                                        │
╰──────────────────────────────────────────────────────────────────────────────╯
⠙ ✓ Loaded ignore patterns
⠙ ✓ Found 42 files to package
⠙ ✓ Created .flash/.build/my-project/
⠙ ✓ Copied 42 files
⠙ ✓ Created manifest and registered 3 resources
⠙ ✓ Installed 5 packages
⠙ ✓ Created artifact.tar.gz (45.2 MB)
⠙ ✓ Removed .build directory

 Application     my-project
 Files packaged  42
 Dependencies    5
 Archive         .flash/artifact.tar.gz
 Size            45.2 MB
╭────────── ✓ Build Complete ──────────╮
│ my-project built successfully!       │
│                                      │
│ Archive ready for deployment.        │
╰──────────────────────────────────────╯
```

## Troubleshooting

### Build fails with "functions not found"

Ensure your project has `@remote` decorated functions in `workers/` directory:

```python
from runpod_flash import remote, LiveServerless

gpu_config = LiveServerless(name="my-gpu")

@remote(resource_config=gpu_config)
def my_function(data):
    return result
```

### Archive is too large

Use `--no-deps` to skip transitive dependencies if base image already includes them:

```bash
flash build --no-deps
```

### Need to examine generated files

Use `--keep-build` to preserve handler files and manifest:

```bash
flash build --keep-build
ls .flash/.build/my-project/
```

### Dependency installation fails

If a package doesn't have pre-built Linux x86_64 wheels:

1. **Install standard pip**: `python -m ensurepip --upgrade` - standard pip has better manylinux compatibility than uv pip
2. **Check package availability**: Visit PyPI and verify the package has Linux wheels for your Python version
3. **Newer Python versions**: Python 3.13+ packages often require manylinux_2_27 or higher - standard pip handles these correctly
4. **uv pip limitations**: uv pip has known issues with manylinux_2_27+ detection - use standard pip when possible
5. **Pure-Python packages**: These should work regardless, as they don't require platform-specific builds

## Managing Deployment Size

### Size Limits

RunPod serverless enforces a **500MB limit** on deployment archives. Exceeding this will cause deployment failures.

### Excluding Base Image Packages

Use `--exclude` to skip packages already in your Docker base image:

```bash
# Exclude PyTorch packages (common in GPU images)
flash build --exclude torch,torchvision,torchaudio

# Multiple packages, comma-separated
flash build --exclude numpy,scipy,pillow
```

### Base Image Package Reference (worker-flash)

Check the [worker-flash repository](https://github.com/runpod-workers/worker-flash) for current base images and pre-installed packages.

**Base image patterns** (check repository for current versions):

| Dockerfile | Base Image Pattern | Pre-installed ML Frameworks | Common Exclusions |
|------------|-------------------|----------------------------|-------------------|
| `Dockerfile` (GPU) | `pytorch/pytorch:*-cuda*-cudnn*-runtime` | torch, torchvision, torchaudio | `--exclude torch,torchvision,torchaudio` |
| `Dockerfile-cpu` (CPU) | `python:*-slim` | **None** | Do not exclude ML packages |
| `Dockerfile-lb` (GPU LoadBalanced) | `pytorch/pytorch:*-cuda*-cudnn*-runtime` | torch, torchvision, torchaudio | `--exclude torch,torchvision,torchaudio` |
| `Dockerfile-lb-cpu` (CPU LoadBalanced) | `python:*-slim` | **None** | Do not exclude ML packages |

**Common pre-installed packages** (versions change - verify in [worker-flash Dockerfiles](https://github.com/runpod-workers/worker-flash)):
- cloudpickle
- pydantic
- requests
- runpod
- huggingface-hub
- fastapi / uvicorn

**Important:**
- Only exclude packages you're certain exist in your base image
- Check your resource config's base image before excluding
- Verify current versions in the [worker-flash repository](https://github.com/runpod-workers/worker-flash)
- CPU deployments: Do NOT exclude torch (not pre-installed)
- GPU deployments: Safe to exclude torch/torchvision/torchaudio

**How to determine your base image:**
1. Check your `@remote` decorator's `resource_config`
2. GPU configs use PyTorch base → exclude torch packages
3. CPU configs use Python slim → bundle all ML packages
4. When in doubt, check the [worker-flash Dockerfiles](https://github.com/runpod-workers/worker-flash)

## Next Steps

After building:

1. **Test Locally**: Run `flash run` to test the application
2. **Deploy**: Use `flash deploy` to deploy to RunPod serverless
3. **Preview**: Test with `flash build --preview` before production deployment
4. **Monitor**: Use `flash env get` to check deployment status

## Related Commands

- [flash deploy](./flash-deploy.md) - Build and deploy in one step
- [flash run](./flash-run.md) - Start development server
- [flash env](./flash-env.md) - Manage deployment environments
- [flash undeploy](./flash-undeploy.md) - Manage deployed endpoints
