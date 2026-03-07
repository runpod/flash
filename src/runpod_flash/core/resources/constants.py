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


# Docker image configuration
FLASH_IMAGE_TAG = os.environ.get("FLASH_IMAGE_TAG", "latest")
_RESOLVED_TAG = FLASH_IMAGE_TAG

FLASH_GPU_IMAGE = os.environ.get("FLASH_GPU_IMAGE", f"runpod/flash:{_RESOLVED_TAG}")
FLASH_CPU_IMAGE = os.environ.get("FLASH_CPU_IMAGE", f"runpod/flash-cpu:{_RESOLVED_TAG}")
FLASH_LB_IMAGE = os.environ.get("FLASH_LB_IMAGE", f"runpod/flash-lb:{_RESOLVED_TAG}")
FLASH_CPU_LB_IMAGE = os.environ.get(
    "FLASH_CPU_LB_IMAGE", f"runpod/flash-lb-cpu:{_RESOLVED_TAG}"
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
MAX_TARBALL_SIZE_MB = 500  # Maximum tarball size in megabytes
VALID_TARBALL_EXTENSIONS = (".tar.gz", ".tgz")  # Valid tarball file extensions
GZIP_MAGIC_BYTES = (0x1F, 0x8B)  # Magic bytes for gzip files

# Load balancer stub timeout (seconds)
DEFAULT_LB_STUB_TIMEOUT = 60.0
