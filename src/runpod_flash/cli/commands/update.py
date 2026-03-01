"""CLI command for updating runpod-flash to latest or a specific version."""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from importlib import metadata
from typing import Optional

import typer
from rich.console import Console

console = Console()

PYPI_URL = "https://pypi.org/pypi/runpod-flash/json"
PIP_TIMEOUT_SECONDS = 120


def _get_current_version() -> str:
    """Return installed runpod-flash version, or 'unknown' if not found."""
    try:
        return metadata.version("runpod-flash")
    except metadata.PackageNotFoundError:
        return "unknown"


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a version string like '1.5.0' into a comparable tuple (1, 5, 0)."""
    return tuple(int(part) for part in version.split("."))


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

    latest = data["info"]["version"]
    releases = set(data.get("releases", {}).keys())
    return latest, releases


def _run_pip_install(version: str) -> subprocess.CompletedProcess[str]:
    """Run pip install for the given version of runpod-flash.

    Raises:
        subprocess.TimeoutExpired: pip took longer than PIP_TIMEOUT_SECONDS.
        RuntimeError: pip exited with non-zero code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", f"runpod-flash=={version}", "--quiet"],
        capture_output=True,
        text=True,
        timeout=PIP_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"pip install failed (exit {result.returncode}): {stderr}")
    return result


def update_command(
    version: Optional[str] = typer.Option(
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
            console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=1)

    target = version or latest

    # Validate target version exists on PyPI
    if target not in releases:
        console.print(
            f"[red]error:[/red] version [bold]{target}[/bold] not found on PyPI"
        )
        raise typer.Exit(code=1)

    # Already on target
    if current == target:
        console.print(f"Already on version [bold]{target}[/bold]. Nothing to do.")
        raise typer.Exit(code=0)

    # Downgrade warning
    if current != "unknown":
        try:
            if _parse_version(target) < _parse_version(current):
                console.print(
                    f"[yellow]note:[/yellow] {target} is older than {current} (downgrade)"
                )
        except ValueError:
            pass  # non-standard version string, skip comparison

    # Install
    console.print(f"Installing runpod-flash [bold]{target}[/bold]...")
    with console.status("Running pip install..."):
        try:
            _run_pip_install(target)
        except subprocess.TimeoutExpired:
            console.print(
                f"[red]error:[/red] pip install timed out after {PIP_TIMEOUT_SECONDS}s"
            )
            raise typer.Exit(code=1)
        except RuntimeError as exc:
            console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=1)

    console.print(f"[green]Updated runpod-flash {current} -> {target}[/green]")
