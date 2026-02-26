"""User-Agent header generation for HTTP requests."""

import platform

from runpod_flash import __version__


def get_user_agent() -> str:
    """Get the User-Agent string for flash HTTP requests.

    Returns:
        User-Agent string in format: Runpod Flash/<version> (Python <python_version>; <OS> <OS_version>; <arch>)

    Example:
        >>> get_user_agent()
        'Runpod Flash/1.4.1 (Python 3.11.12; Darwin 25.2.0; arm64)'
    """
    python_version = platform.python_version()
    os_name = platform.system()
    os_version = platform.release()
    arch = platform.machine()

    return f"Runpod Flash/{__version__} (Python {python_version}; {os_name} {os_version}; {arch})"
