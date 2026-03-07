import os
from urllib.parse import urlparse

import runpod

CONSOLE_BASE_URL = os.environ.get("CONSOLE_BASE_URL", "https://console.runpod.io")
CONSOLE_URL = f"{CONSOLE_BASE_URL}/serverless/user/endpoint/%s"


def _endpoint_domain_from_base_url(base_url: str) -> str:
    if not base_url:
        return "api.runpod.ai"
    if "://" not in base_url:
        base_url = f"https://{base_url}"
    parsed = urlparse(base_url)
    return parsed.netloc or "api.runpod.ai"


ENDPOINT_DOMAIN = _endpoint_domain_from_base_url(runpod.endpoint_url_base)


# worker runtime Python versions. all flash workers run Python 3.12.
# one tarball serves every resource type (GPU and CPU), so packages,
# images, and the runtime must all target 3.12.
WORKER_PYTHON_VERSION: str = "3.12"
GPU_PYTHON_VERSIONS: tuple[str, ...] = ("3.12",)
CPU_PYTHON_VERSIONS: tuple[str, ...] = ("3.12",)

GPU_BASE_IMAGE_PYTHON_VERSION: str = "3.12"
DEFAULT_PYTHON_VERSION: str = "3.12"

# python versions that can run the flash SDK locally (for flash build, etc.)
SUPPORTED_PYTHON_VERSIONS: tuple[str, ...] = ("3.10", "3.11", "3.12")


def local_python_version() -> str:
    """Return the Python version used by flash workers (always 3.12)."""
    return DEFAULT_PYTHON_VERSION


# Image type to repository mapping
_IMAGE_REPOS: dict[str, str] = {
    "gpu": "runpod/flash",
    "cpu": "runpod/flash-cpu",
    "lb": "runpod/flash-lb",
    "lb-cpu": "runpod/flash-lb-cpu",
}

# Image types that require GPU-compatible Python versions
_GPU_IMAGE_TYPES: frozenset[str] = frozenset({"gpu", "lb"})

# Image types that require CPU-compatible Python versions
_CPU_IMAGE_TYPES: frozenset[str] = frozenset({"cpu", "lb-cpu"})

# Image type to environment variable override mapping
_IMAGE_ENV_VARS: dict[str, str] = {
    "gpu": "FLASH_GPU_IMAGE",
    "cpu": "FLASH_CPU_IMAGE",
    "lb": "FLASH_LB_IMAGE",
    "lb-cpu": "FLASH_CPU_LB_IMAGE",
}


def validate_python_version(version: str) -> str:
    """Validate that a Python version string is supported.

    Args:
        version: Python version string (e.g. "3.12").

    Returns:
        The validated version string.

    Raises:
        ValueError: If version is not in SUPPORTED_PYTHON_VERSIONS.
    """
    if version not in SUPPORTED_PYTHON_VERSIONS:
        supported = ", ".join(SUPPORTED_PYTHON_VERSIONS)
        raise ValueError(
            f"Python {version} is not supported. Supported versions: {supported}"
        )
    return version


def get_image_name(
    image_type: str,
    python_version: str,
    *,
    tag: str | None = None,
) -> str:
    """Resolve a versioned Docker image name for the given type and Python version.

    Args:
        image_type: One of 'gpu', 'cpu', 'lb', 'lb-cpu'.
        python_version: Python version string (e.g. "3.12").
        tag: Image tag suffix. Defaults to FLASH_IMAGE_TAG env var or "latest".

    Returns:
        Fully qualified image name, e.g. "runpod/flash:py3.12-latest".

    Raises:
        ValueError: If image_type is unknown or python_version is unsupported.
    """
    if image_type not in _IMAGE_REPOS:
        raise ValueError(
            f"Unknown image type '{image_type}'. "
            f"Valid types: {', '.join(sorted(_IMAGE_REPOS))}"
        )

    # Environment variable override takes precedence, bypassing version validation
    env_var = _IMAGE_ENV_VARS[image_type]
    override = os.environ.get(env_var)
    if override:
        return override

    validate_python_version(python_version)

    if image_type in _GPU_IMAGE_TYPES and python_version not in GPU_PYTHON_VERSIONS:
        gpu_versions = ", ".join(GPU_PYTHON_VERSIONS)
        raise ValueError(
            f"GPU endpoints require Python {gpu_versions}. Got Python {python_version}."
        )

    if image_type in _CPU_IMAGE_TYPES and python_version not in CPU_PYTHON_VERSIONS:
        cpu_versions = ", ".join(CPU_PYTHON_VERSIONS)
        raise ValueError(
            f"CPU endpoints require Python {cpu_versions}. Got Python {python_version}."
        )

    resolved_tag = tag or os.environ.get("FLASH_IMAGE_TAG", "latest")
    repo = _IMAGE_REPOS[image_type]
    return f"{repo}:py{python_version}-{resolved_tag}"


# Docker image configuration
FLASH_IMAGE_TAG = os.environ.get("FLASH_IMAGE_TAG", "latest")
_RESOLVED_TAG = FLASH_IMAGE_TAG

FLASH_GPU_IMAGE = os.environ.get(
    "FLASH_GPU_IMAGE", f"runpod/flash:py{DEFAULT_PYTHON_VERSION}-{_RESOLVED_TAG}"
)
FLASH_CPU_IMAGE = os.environ.get(
    "FLASH_CPU_IMAGE", f"runpod/flash-cpu:py{DEFAULT_PYTHON_VERSION}-{_RESOLVED_TAG}"
)
FLASH_LB_IMAGE = os.environ.get(
    "FLASH_LB_IMAGE", f"runpod/flash-lb:py{DEFAULT_PYTHON_VERSION}-{_RESOLVED_TAG}"
)
FLASH_CPU_LB_IMAGE = os.environ.get(
    "FLASH_CPU_LB_IMAGE",
    f"runpod/flash-lb-cpu:py{DEFAULT_PYTHON_VERSION}-{_RESOLVED_TAG}",
)

# Base images for process injection (no flash-worker baked in)
FLASH_GPU_BASE_IMAGE = os.environ.get(
    "FLASH_GPU_BASE_IMAGE", "pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime"
)
FLASH_CPU_BASE_IMAGE = os.environ.get("FLASH_CPU_BASE_IMAGE", "python:3.11-slim")

# Worker tarball for process injection
FLASH_WORKER_VERSION = os.environ.get("FLASH_WORKER_VERSION", "1.1.1")
FLASH_WORKER_TARBALL_URL_TEMPLATE = os.environ.get(
    "FLASH_WORKER_TARBALL_URL",
    "https://github.com/runpod-workers/flash/releases/download/"
    "v{version}/flash-worker-v{version}-py3.11-linux-x86_64.tar.gz",
)

# Worker configuration defaults
DEFAULT_WORKERS_MIN = 0
DEFAULT_WORKERS_MAX = 1

# Flash app artifact upload constants
TARBALL_CONTENT_TYPE = "application/gzip"
MAX_TARBALL_SIZE_MB = 1500  # Maximum tarball size in megabytes
VALID_TARBALL_EXTENSIONS = (".tar.gz", ".tgz")  # Valid tarball file extensions
GZIP_MAGIC_BYTES = (0x1F, 0x8B)  # Magic bytes for gzip files

# tarball upload retry/timeout settings
UPLOAD_TIMEOUT_SECONDS = 600  # 10 minutes per attempt
UPLOAD_MAX_RETRIES = 3
UPLOAD_BACKOFF_BASE_SECONDS = 2.0
UPLOAD_BACKOFF_MAX_SECONDS = 30.0

# Load balancer stub timeout (seconds)
DEFAULT_LB_STUB_TIMEOUT = 60.0
