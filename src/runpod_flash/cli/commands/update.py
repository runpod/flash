"""CLI command for updating runpod-flash to latest or a specific version."""

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path

import typer
from rich.console import Console

from runpod_flash.cli.utils.formatting import print_error, print_warning

console = Console()

PYPI_URL = "https://pypi.org/pypi/runpod-flash/json"
INSTALL_TIMEOUT_SECONDS = 120
UV_TOOL_DIR_TIMEOUT_SECONDS = 10

# Substrings pip/uv emit when refusing to modify a PEP 668 externally managed
# interpreter (Homebrew, Debian/Ubuntu system Python, etc.).
_EXTERNALLY_MANAGED_MARKERS = (
    "externally-managed-environment",
    "externally managed",
)


def _get_current_version() -> str:
    """Return installed runpod-flash version, or 'unknown' if not found."""
    try:
        return metadata.version("runpod-flash")
    except metadata.PackageNotFoundError:
        return "unknown"


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a version string like '1.5.0' into a comparable tuple (1, 5, 0).

    Tuples are NOT padded here -- callers comparing two parsed versions should
    use ``_compare_versions()`` to handle differing component counts.
    """
    return tuple(int(part) for part in version.split("."))


def _compare_versions(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Compare two parsed version tuples, padding shorter one with zeros.

    Returns negative if a < b, zero if equal, positive if a > b.
    Handles differing component counts: (2, 0) and (2, 0, 0) are equal.
    """
    max_len = max(len(a), len(b))
    a_padded = a + (0,) * (max_len - len(a))
    b_padded = b + (0,) * (max_len - len(b))
    if a_padded < b_padded:
        return -1
    if a_padded > b_padded:
        return 1
    return 0


def _fetch_pypi_metadata() -> tuple[str, set[str]]:
    """Fetch latest version and available releases from PyPI.

    Returns:
        Tuple of (latest_version, set_of_all_version_strings).

    Raises:
        ConnectionError: Network unreachable or DNS failure.
        RuntimeError: HTTP error from PyPI.
    """
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        if isinstance(exc, urllib.error.HTTPError):
            raise RuntimeError(
                f"PyPI returned HTTP {exc.code}. Try again later."
            ) from exc
        raise ConnectionError(
            "Could not reach PyPI. Check your network connection."
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            "PyPI returned an unexpected response. Try again later."
        ) from exc

    try:
        latest = data["info"]["version"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            "PyPI response missing version info. Try again later."
        ) from exc

    releases = set(data.get("releases", {}).keys())
    return latest, releases


def _is_uv_tool_install() -> bool:
    """Return True when flash runs from a uv-managed tool environment.

    ``uv tool install runpod-flash`` places flash in an isolated environment
    under ``uv tool dir`` (default ~/.local/share/uv/tools, overridable via
    $UV_TOOL_DIR). Such installs must be upgraded with ``uv tool install
    --force`` -- ``uv pip install`` fails because there is no ambient venv to
    discover from the working directory.

    Detection compares flash's own interpreter prefix (``sys.prefix``) against
    the authoritative tool directory reported by ``uv tool dir``. Returns False
    on any failure (uv missing, non-zero exit, empty output), so callers fall
    back to the pip-style install path.
    """
    try:
        result = subprocess.run(
            ["uv", "tool", "dir"],
            capture_output=True,
            text=True,
            timeout=UV_TOOL_DIR_TIMEOUT_SECONDS,
            check=False,  # returncode handled explicitly below
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    tool_dir = result.stdout.strip()
    if not tool_dir:
        return False
    return Path(sys.prefix).resolve().is_relative_to(Path(tool_dir).resolve())


def _build_install_command(version: str, *, pinned: bool) -> list[str]:
    """Build the install command for flash's own environment.

    Args:
        version: Resolved target version (e.g. "1.5.0").
        pinned: True when the user requested an explicit ``--version``. For uv
            tool installs this controls whether the tool receipt records an
            exact version pin (see below).

    Returns the command as a list of strings suitable for subprocess.run.
    Selects the mechanism that matches how flash was installed:

    - uv tool install -> ``uv tool install <spec> --force`` (upgrades the
      isolated tool environment; works from any directory). ``uv tool install``
      writes the given specifier into the tool's uv receipt, so an unpinned
      update uses ``runpod-flash@latest`` to keep the receipt unpinned --
      otherwise a later ``uv tool upgrade`` would report the tool as pinned and
      refuse to move it. An explicit ``--version`` intentionally pins.
    - uv venv install -> ``uv pip install <spec> --python <sys.executable>``
      (targets flash's interpreter directly, so the current working directory
      does not need to contain a discoverable virtual environment).
    - no uv on PATH -> ``python -m pip install <spec>`` fallback.
    """
    package_spec = f"runpod-flash=={version}"
    if shutil.which("uv"):
        if _is_uv_tool_install():
            tool_spec = package_spec if pinned else "runpod-flash@latest"
            return ["uv", "tool", "install", tool_spec, "--force", "--quiet"]
        return [
            "uv",
            "pip",
            "install",
            package_spec,
            "--python",
            sys.executable,
            "--quiet",
        ]
    return [sys.executable, "-m", "pip", "install", package_spec, "--quiet"]


def _is_externally_managed_error(stderr: str) -> bool:
    """Return True when installer stderr signals a PEP 668 externally managed env."""
    lowered = stderr.lower()
    return any(marker in lowered for marker in _EXTERNALLY_MANAGED_MARKERS)


def _run_install(version: str, *, pinned: bool) -> subprocess.CompletedProcess[str]:
    """Install the given version of runpod-flash.

    Args:
        version: Resolved target version to install.
        pinned: Forwarded to :func:`_build_install_command`; True when the user
            requested an explicit ``--version``.

    Raises:
        subprocess.TimeoutExpired: Install took longer than INSTALL_TIMEOUT_SECONDS.
        RuntimeError: Installer exited with non-zero code.
    """
    cmd = _build_install_command(version, pinned=pinned)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=INSTALL_TIMEOUT_SECONDS,
        check=False,  # returncode handled explicitly below
    )
    if result.returncode != 0:
        installer = "uv" if cmd[0] == "uv" else "pip"
        stderr = result.stderr.strip()
        if _is_externally_managed_error(stderr):
            raise RuntimeError(
                f"{installer} install failed (exit {result.returncode}): the target "
                "Python is an externally managed environment (PEP 668), so it cannot "
                "be updated in place. Reinstall flash inside a virtual environment or "
                "with `uv tool install runpod-flash`, then run flash update again."
            )
        raise RuntimeError(
            f"{installer} install failed (exit {result.returncode}): {stderr}"
        )
    return result


def update_command(
    version: str | None = typer.Option(
        None, "--version", "-V", help="Target version to install (default: latest)"
    ),
) -> None:
    """Update runpod-flash to the latest version or a specific version."""
    current = _get_current_version()
    console.print(f"Current version: [bold]{current}[/bold]")

    # Fetch PyPI metadata
    with console.status("Checking PyPI for available versions..."):
        try:
            latest, releases = _fetch_pypi_metadata()
        except (ConnectionError, RuntimeError) as exc:
            print_error(console, str(exc))
            raise typer.Exit(code=1)

    target = version or latest

    # Validate target version exists on PyPI
    if target not in releases:
        print_error(console, f"version [bold]{target}[/bold] not found on PyPI")
        raise typer.Exit(code=1)

    # Already on target
    if current == target:
        console.print(f"Already on version [bold]{target}[/bold]. Nothing to do.")
        raise typer.Exit(code=0)

    # Downgrade warning
    if current != "unknown":
        try:
            if _compare_versions(_parse_version(target), _parse_version(current)) < 0:
                print_warning(
                    console,
                    f"{target} is older than {current} (downgrade)",
                )
        except ValueError:
            pass  # non-standard version string, skip comparison

    # Install. An explicit --version pins; a bare `flash update` tracks latest.
    console.print(f"Installing runpod-flash [bold]{target}[/bold]...")
    with console.status("Installing..."):
        try:
            _run_install(target, pinned=version is not None)
        except subprocess.TimeoutExpired:
            print_error(
                console,
                f"install timed out after {INSTALL_TIMEOUT_SECONDS}s",
            )
            raise typer.Exit(code=1)
        except RuntimeError as exc:
            print_error(console, str(exc))
            raise typer.Exit(code=1)

    console.print(f"[green]Updated runpod-flash {current} -> {target}[/green]")
