"""User-Agent header generation for HTTP requests."""

import platform
from importlib.metadata import version


def get_user_agent() -> str:
    """Get the User-Agent string for flash HTTP requests.

    Returns:
        User-Agent string in format: Runpod Flash/<version> (Python <python_version>; <OS>)

    Example:
        >>> get_user_agent()
        'Runpod Flash/1.1.1 (Python 3.11.12; Darwin)'
    """
    try:
        pkg_version = version("runpod-flash")
    except Exception:
        pkg_version = "unknown"

    python_version = platform.python_version()
    os_name = platform.system()

    return f"Runpod Flash/{pkg_version} (Python {python_version}; {os_name})"
