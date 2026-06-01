"""User-Agent header generation for HTTP requests."""

import os
import platform


def get_user_agent() -> str:
    """Get the User-Agent string for flash HTTP requests.

    Appends coding agent source tags when the corresponding environment
    variables are set (e.g. CLAUDECODE=1 for Claude Code).

    Returns:
        User-Agent string in format: Runpod Flash/<version> (Python <python_version>; <OS> <OS_version>; <arch>)

    Example:
        >>> get_user_agent()
        'Runpod Flash/1.4.1 (Python 3.11.12; Darwin 25.2.0; arm64)'
    """
    from runpod_flash import __version__

    python_version = platform.python_version()
    os_name = platform.system()
    os_version = platform.release()
    arch = platform.machine()

    ua = f"Runpod Flash/{__version__} (Python {python_version}; {os_name} {os_version}; {arch})"

    if os.getenv("CLAUDECODE") == "1":
        ua += " (via claude-code)"

    return ua
