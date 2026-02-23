"""Runtime context detection utilities."""

import os


def is_deployed_container() -> bool:
    """Check if running in a deployed RunPod container.

    A deployed container is identified by:
    - RUNPOD_ENDPOINT_ID is set (RunPod sets this for serverless endpoints)
    - OR RUNPOD_POD_ID is set (RunPod sets this for pods)
    - BUT NOT when FLASH_IS_LIVE_PROVISIONING is true (explicit local dev mode)

    The FLASH_IS_LIVE_PROVISIONING flag allows local development with on-demand
    provisioning even when RunPod environment variables are present (e.g., from
    testing or previous deployments).

    Returns:
        True if running in deployed container, False for local dev
    """
    # Explicit local development mode - overrides container detection
    if os.getenv("FLASH_IS_LIVE_PROVISIONING", "").lower() == "true":
        return False

    return bool(os.getenv("RUNPOD_ENDPOINT_ID") or os.getenv("RUNPOD_POD_ID"))


def is_local_development() -> bool:
    """Check if running in local development mode.

    Returns:
        True if local development, False if deployed
    """
    return not is_deployed_container()
