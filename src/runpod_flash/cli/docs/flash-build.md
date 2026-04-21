# flash build

Build a deployment-ready artifact for your Flash application.

## Overview

The `flash build` command packages your Flash project into a deployable archive (`.flash/artifact.tar.gz`). It scans your codebase for `Endpoint` definitions, resolves dependencies, and creates a manifest that tells Runpod how to provision your serverless endpoints.

### What happens during build

1. **Endpoint discovery:** Finds all `Endpoint` definitions and groups them by resource configuration
2. **Manifest generation:** Creates `.flash/flash_manifest.json` with endpoint definitions and routing info
3. **Handler generation:** Creates appropriate handler code for each endpoint type (function, class, or LB)
4. **Dependency installation:** Installs Python packages for Linux x86_64 (cross-platform compatible)
5. **Packaging:** Bundles everything into a compressed archive

> **Tip:** Most users should use `flash deploy` instead, which runs build + deploy in one step. Use `flash build` when you need more control over the build process or want to inspect the artifact before deploying.


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
- `--python-version`: Target Python version for worker images (`3.10`, `3.11`, or `3.12`). Overrides per-resource `python_version`. Default: value declared on resource configs, or 3.12 if none set.

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

## Build Artifacts

After `flash build` completes:

| File/Directory | Purpose |
|---|---|
| `.flash/artifact.tar.gz` | Deployment package (ready for Runpod) |
| `.flash/flash_manifest.json` | Service discovery configuration |
| `.flash/.build/` | Temporary build directory (removed unless `--keep-build` specified) |

## Dependency Management

### Cross-Platform Builds

Flash automatically handles cross-platform builds, ensuring compatibility with Runpod's Linux x86_64 serverless infrastructure:

- **Automatic Platform Targeting**: Dependencies are always installed for Linux x86_64, regardless of your build platform (macOS, Windows, or Linux)
- **Python Version**: Targets Python 3.12 for wheel ABI selection regardless of local interpreter
- **Binary Wheel Enforcement**: Only pre-built binary wheels are used, preventing platform-specific compilation issues

This means you can safely build on macOS ARM64, Windows, or any platform, and the deployment will work correctly on Runpod.

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

Only installs direct dependencies specified in `Endpoint` definitions:
- Faster builds for large projects
- Smaller deployment packages
- Useful when base image already includes dependencies

## Preview Environment

```bash
flash build --preview
```

Launch a local Docker-based test environment immediately after building. This allows you to test your distributed system locally before deploying to Runpod.

**What happens:**
1. Builds your project (creates archive, manifest)
2. Creates a Docker network for inter-container communication
3. Starts one Docker container per resource config:
   - Application container
   - All worker containers (GPU, CPU, etc.)
4. Exposes the application on `localhost:8888`
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
@Endpoint(name="preprocessor", cpu="cpu3c-4-8")
def preprocess(data):
    return clean_data

# GPU endpoint function
@Endpoint(name="inference", gpu=GpuGroup.AMPERE_80)
async def inference(data):
    # calls CPU endpoint function
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

### Build fails with "endpoints not found"

Ensure your project has `Endpoint` definitions:

```python
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="my-worker", gpu=GpuGroup.ANY)
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

1. **Install standard pip**: `python -m ensurepip --upgrade` -- standard pip has better manylinux compatibility than uv pip
2. **Check package availability**: Visit PyPI and verify the package has Linux wheels for Python 3.12
3. **Python 3.12**: All flash workers run Python 3.12. Ensure packages are available for this version.
4. **Pure-Python packages**: These work regardless, as they don't require platform-specific builds

## Managing Deployment Size

### Size Limits

Runpod Serverless enforces a **1.5GB limit** on deployment archives. Exceeding this will cause your deployment to fail.

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

**Important:**
- Only exclude packages you're certain exist in your base image
- GPU endpoints: safe to exclude torch/torchvision/torchaudio
- CPU endpoints: do NOT exclude torch (not pre-installed)
- Verify current versions in the [worker-flash repository](https://github.com/runpod-workers/worker-flash)

## Next Steps

After building:

1. **Test locally**: Run `flash dev` to test the application
2. **Deploy**: Use `flash deploy` to deploy to RunPod Serverless
3. **Preview**: Test with `flash build --preview` before production deployment
4. **Monitor**: Use `flash env get` to check deployment status

## Related commands

- [flash deploy](./flash-deploy.md) - Build and deploy in one step
- [flash dev](./flash-run.md) - Start development server
- [flash env](./flash-env.md) - Manage deployment environments
- [flash undeploy](./flash-undeploy.md) - Manage deployed endpoints
