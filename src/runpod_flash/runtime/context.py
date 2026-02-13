"""Runtime context detection utilities."""

import os


def is_deployed_container() -> bool:
    """Check if running in a deployed RunPod container.

    A deployed container is identified by:
    - RUNPOD_ENDPOINT_ID is set (RunPod sets this for serverless endpoints)
    - OR RUNPOD_POD_ID is set (RunPod sets this for pods)

    Returns:
        True if running in deployed container, False for local dev
    """
    return bool(os.getenv("RUNPOD_ENDPOINT_ID") or os.getenv("RUNPOD_POD_ID"))


def is_local_development() -> bool:
    """Check if running in local development mode.

    Returns:
        True if local development, False if deployed
    """
    return not is_deployed_container()
