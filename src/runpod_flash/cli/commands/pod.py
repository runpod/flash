"""Pod management CLI commands.

Provides `flash pod` sub-commands for creating, starting, stopping,
terminating, and inspecting Runpod pods.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from runpod_flash.core.api.pod_client import PodApiClient
from runpod_flash.core.credentials import get_api_key
from runpod_flash.core.exceptions import RunpodAPIKeyError
from runpod_flash.core.resources.gpu import GpuType
from runpod_flash.core.resources.pod import Pod, PodConfig, PodState
from runpod_flash.core.resources.pod_lifecycle import (
    PodLifecycleManager,
    PodTracker,
    PodTrackerEntry,
)

console = Console()

pod_app = typer.Typer(
    name="pod",
    help="Pod management commands",
    no_args_is_help=True,
)


def _get_flash_dir() -> Path:
    """Return the .flash directory in the current working directory."""
    return Path.cwd() / ".flash"


def _get_tracker() -> PodTracker:
    """Create a PodTracker pointed at the current .flash directory."""
    return PodTracker(_get_flash_dir())


def _get_lifecycle() -> PodLifecycleManager:
    """Create a PodLifecycleManager with API client and tracker.

    Raises:
        typer.Exit: If no API key is configured.
    """
    api_key = get_api_key()
    if not api_key:
        raise RunpodAPIKeyError()
    client = PodApiClient(api_key=api_key)
    tracker = _get_tracker()
    return PodLifecycleManager(api_client=client, tracker=tracker)


def _parse_gpu_type(gpu_string: str) -> GpuType:
    """Parse a GPU type string, trying value lookup then name lookup.

    Args:
        gpu_string: GPU identifier (e.g. "NVIDIA A100 80GB PCIe" or "NVIDIA_A100_80GB_PCIe").

    Returns:
        Matching GpuType enum member.

    Raises:
        typer.BadParameter: If the string does not match any GpuType.
    """
    try:
        return GpuType(gpu_string)
    except ValueError:
        pass
    try:
        return GpuType[gpu_string]
    except KeyError:
        valid = ", ".join(g.name for g in GpuType)
        raise typer.BadParameter(
            f"Unknown GPU type: '{gpu_string}'. Valid names: {valid}"
        ) from None


def _entry_to_pod(entry: PodTrackerEntry) -> Pod:
    """Reconstruct a Pod instance from a tracker entry.

    Args:
        entry: Persisted pod snapshot.

    Returns:
        Pod with runtime state restored from the entry.
    """
    gpu = None
    if entry.gpu is not None:
        try:
            gpu = GpuType(entry.gpu)
        except ValueError:
            gpu = entry.gpu

    pod = Pod(name=entry.name, image=entry.image, gpu=gpu)
    pod._pod_id = entry.pod_id or None
    pod._state = PodState(entry.state)
    pod._address = entry.address
    return pod


def _print_pod_detail(entry: PodTrackerEntry) -> None:
    """Print detailed information for a single pod.

    Args:
        entry: Pod tracker entry to display.
    """
    console.print(f"[bold]Name:[/bold]    {entry.name}")
    console.print(f"[bold]ID:[/bold]      {entry.pod_id}")
    console.print(f"[bold]State:[/bold]   {entry.state}")
    console.print(f"[bold]GPU:[/bold]     {entry.gpu or 'CPU'}")
    console.print(f"[bold]Image:[/bold]   {entry.image}")
    console.print(f"[bold]Address:[/bold] {entry.address or 'N/A'}")
    console.print(f"[bold]Created:[/bold] {entry.created_at}")
    console.print(f"[bold]Config Hash:[/bold] {entry.config_hash}")


def _load_entry_or_exit(name: str) -> PodTrackerEntry:
    """Load a pod tracker entry by name, exiting on failure.

    Args:
        name: Pod name to look up.

    Returns:
        The matching PodTrackerEntry.

    Raises:
        typer.Exit: If the pod is not found.
    """
    tracker = _get_tracker()
    entry = tracker.load(name)
    if entry is None:
        console.print(
            f"[red]Pod '{name}' not found. Check available pods with: flash pod status[/red]"
        )
        raise typer.Exit(code=1)
    return entry


@pod_app.command("create")
def create_command(
    name: str = typer.Argument(..., help="Pod name"),
    image: str = typer.Option(..., "--image", help="Docker image to run"),
    gpu: Optional[str] = typer.Option(None, "--gpu", help="GPU type"),
    port: Optional[str] = typer.Option(
        None, "--port", help="Port to expose (e.g. '8080/http')"
    ),
    gpu_count: int = typer.Option(1, "--gpu-count", help="Number of GPUs"),
    cloud_type: str = typer.Option(
        "ALL", "--cloud-type", help="Cloud type (ALL, COMMUNITY, SECURE)"
    ),
) -> None:
    """Create and provision a new pod."""
    parsed_gpu = _parse_gpu_type(gpu) if gpu else None
    ports = [port] if port else None
    config = PodConfig(gpu_count=gpu_count, cloud_type=cloud_type, ports=ports)
    pod = Pod(name=name, image=image, gpu=parsed_gpu, config=config)

    lifecycle = _get_lifecycle()
    pod = asyncio.run(lifecycle.provision(pod))

    console.print("[green]Pod created successfully[/green]")
    console.print(f"  Name:    {pod.name}")
    console.print(f"  ID:      {pod._pod_id}")
    console.print(f"  Address: {pod._address or 'N/A'}")


@pod_app.command("start")
def start_command(
    name: str = typer.Argument(..., help="Pod name to start"),
) -> None:
    """Resume a stopped pod."""
    entry = _load_entry_or_exit(name)
    pod = _entry_to_pod(entry)

    lifecycle = _get_lifecycle()
    pod = asyncio.run(lifecycle.resume(pod))

    console.print(f"[green]Pod '{name}' started[/green]")
    console.print(f"  Address: {pod._address or 'N/A'}")


@pod_app.command("stop")
def stop_command(
    name: str = typer.Argument(..., help="Pod name to stop"),
) -> None:
    """Stop a running pod."""
    entry = _load_entry_or_exit(name)
    pod = _entry_to_pod(entry)

    lifecycle = _get_lifecycle()
    asyncio.run(lifecycle.stop(pod))

    console.print(f"[green]Pod '{name}' stopped[/green]")


@pod_app.command("terminate")
def terminate_command(
    name: str = typer.Argument(..., help="Pod name to terminate"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Terminate a pod permanently."""
    if not yes:
        confirm = typer.confirm(f"Terminate pod '{name}'? This cannot be undone")
        if not confirm:
            console.print("Aborted.")
            raise typer.Exit()

    entry = _load_entry_or_exit(name)
    pod = _entry_to_pod(entry)

    lifecycle = _get_lifecycle()
    asyncio.run(lifecycle.terminate(pod))

    console.print(f"[green]Pod '{name}' terminated[/green]")


@pod_app.command("status")
def status_command(
    name: Optional[str] = typer.Argument(None, help="Pod name for detailed view"),
) -> None:
    """Show pod status. Lists all pods or shows detail for a specific pod."""
    tracker = _get_tracker()

    if name is not None:
        entry = tracker.load(name)
        if entry is None:
            console.print(f"[red]Pod '{name}' not found[/red]")
            raise typer.Exit(code=1)
        _print_pod_detail(entry)
        return

    entries = tracker.load_all()
    if not entries:
        console.print("No tracked pods")
        return

    table = Table(title="Pods")
    table.add_column("NAME", style="bold")
    table.add_column("STATE")
    table.add_column("GPU")
    table.add_column("IMAGE")
    table.add_column("ADDRESS")

    for entry in entries:
        table.add_row(
            entry.name,
            entry.state,
            entry.gpu or "CPU",
            entry.image,
            entry.address or "N/A",
        )

    console.print(table)


@pod_app.command("ssh")
def ssh_command(
    name: str = typer.Argument(..., help="Pod name to connect to"),
) -> None:
    """Show SSH connection info for a running pod."""
    entry = _load_entry_or_exit(name)

    if entry.state != PodState.RUNNING.value:
        console.print(
            f"[red]Pod '{name}' is in state '{entry.state}', not running. "
            f"Start it with: flash pod start {name}[/red]"
        )
        raise typer.Exit(code=1)

    console.print("[bold]SSH Connection Info[/bold]")
    console.print(f"  Pod ID:  {entry.pod_id}")
    console.print(f"  Address: {entry.address or 'N/A'}")
    console.print(
        f"  Connect: ssh root@{entry.address.split('//')[1].split(':')[0] if entry.address else 'N/A'}"
    )
