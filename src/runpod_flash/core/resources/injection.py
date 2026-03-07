"""Process injection utilities for flash-worker tarball delivery."""

from .constants import FLASH_WORKER_TARBALL_URL_TEMPLATE, FLASH_WORKER_VERSION


def build_injection_cmd(
    worker_version: str = FLASH_WORKER_VERSION,
    tarball_url: str | None = None,
) -> str:
    """Build the dockerArgs command that downloads, extracts, and runs flash-worker.

    Supports remote URLs (curl/wget) and local file paths (file://) for testing.
    Includes version-based caching to skip re-extraction on warm workers.
    Network volume caching stores extracted tarball at /runpod-volume/.flash-worker/v{version}.
    """
    if tarball_url is None:
        tarball_url = FLASH_WORKER_TARBALL_URL_TEMPLATE.format(version=worker_version)

    if tarball_url.startswith("file://"):
        local_path = tarball_url[7:]
        return (
            "bash -c '"
            "set -e; FW_DIR=/opt/flash-worker; "
            "mkdir -p $FW_DIR; "
            f"tar xzf {local_path} -C $FW_DIR --strip-components=1; "
            "exec $FW_DIR/bootstrap.sh'"
        )

    return (
        "bash -c '"
        f"set -e; FW_DIR=/opt/flash-worker; FW_VER={worker_version}; "
        # Network volume cache check
        'NV_CACHE="/runpod-volume/.flash-worker/v$FW_VER"; '
        'if [ -d "$NV_CACHE" ] && [ -f "$NV_CACHE/.version" ]; then '
        'cp -r "$NV_CACHE" "$FW_DIR"; '
        # Local cache check (container disk persistence between restarts)
        'elif [ -f "$FW_DIR/.version" ] && [ "$(cat $FW_DIR/.version)" = "$FW_VER" ]; then '
        "true; "
        "else "
        "mkdir -p $FW_DIR; "
        f'DL_URL="{tarball_url}"; '
        "dl() { "
        '(command -v curl >/dev/null 2>&1 && curl -sSL "$1" || '
        'command -v wget >/dev/null 2>&1 && wget -qO- "$1" || '
        'python3 -c "import urllib.request,sys;sys.stdout.buffer.write(urllib.request.urlopen(sys.argv[1]).read())" "$1"); '
        "}; "
        'dl "$DL_URL" '
        "| tar xz -C $FW_DIR --strip-components=1; "
        # Cache to network volume if available
        "if [ -d /runpod-volume ]; then "
        'mkdir -p "$NV_CACHE" && cp -r "$FW_DIR"/* "$NV_CACHE/" 2>/dev/null || true; fi; '
        "fi; "
        "exec $FW_DIR/bootstrap.sh'"
    )
