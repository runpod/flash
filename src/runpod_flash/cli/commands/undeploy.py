"""Undeploy command for managing RunPod serverless endpoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Dict, Optional, Tuple
import typer
from rich.console import Console
from rich.prompt import Confirm
import questionary

if TYPE_CHECKING:
    from ...core.resources.base import DeployableResource
    from ...core.resources.resource_manager import ResourceManager

console = Console()


def _get_resource_manager():
    """Get ResourceManager instance with lazy loading.

    Imports are deferred to avoid loading heavy dependencies (runpod, aiohttp, etc)
    at CLI startup time. This allows fast commands like 'flash init' to run without
    loading unnecessary dependencies.

    Can be mocked in tests: @patch('runpod_flash.cli.commands.undeploy._get_resource_manager')
    """
    from ...core.resources.resource_manager import ResourceManager

    return ResourceManager()


def _get_serverless_resources(
    resources: Dict[str, DeployableResource],
) -> Dict[str, DeployableResource]:
    """Filter resources to only include serverless endpoints.

    Excludes other resource types like NetworkVolume that shouldn't be undeployed
    through this command.

    Args:
        resources: Dictionary of resource_id -> DeployableResource

    Returns:
        Filtered dictionary containing only serverless endpoints
    """
    from ...core.resources.serverless import ServerlessResource

    return {
        resource_id: resource
        for resource_id, resource in resources.items()
        if isinstance(resource, ServerlessResource)
    }


def _get_resource_status(resource) -> Tuple[str, str]:
    """Get resource status color and text.

    Args:
        resource: DeployableResource to check

    Returns:
        Tuple of (color, status_text)
    """
    try:
        if resource.is_deployed():
            return "green", "active"
        return "red", "inactive"
    except Exception:
        return "yellow", "unknown"


def _get_resource_type(resource) -> str:
    """Get human-readable resource type.

    Args:
        resource: DeployableResource to check

    Returns:
        Resource type string
    """
    class_name = resource.__class__.__name__
    return class_name.replace("Serverless", " Serverless").replace(
        "Endpoint", " Endpoint"
    )


def list_command():
    """List all deployed endpoints tracked in .runpod/resources.pkl."""
    manager = _get_resource_manager()
    all_resources = manager.list_all_resources()
    resources = _get_serverless_resources(all_resources)

    if not resources:
        console.print("No endpoints found.")
        return

    active_count = 0
    inactive_count = 0

    console.print()
    for resource_id, resource in resources.items():
        color, status_text = _get_resource_status(resource)
        if status_text == "active":
            active_count += 1
        elif status_text == "inactive":
            inactive_count += 1

        name = getattr(resource, "name", "N/A")
        endpoint_id = getattr(resource, "id", "N/A")

        console.print(
            f"  [{color}]●[/{color}] [bold]{name}[/bold]  "
            f"[{color}]{status_text}[/{color}]  [dim]{endpoint_id}[/dim]"
        )

    total = len(resources)
    unknown_count = total - active_count - inactive_count
    parts = []
    if active_count > 0:
        parts.append(f"[green]{active_count} active[/green]")
    if inactive_count > 0:
        parts.append(f"[red]{inactive_count} inactive[/red]")
    if unknown_count > 0:
        parts.append(f"[yellow]{unknown_count} unknown[/yellow]")

    console.print(f"\n  {total} endpoint{'s' if total != 1 else ''}  {', '.join(parts)}")

    console.print(f"\n  [bold]Commands[/bold]")
    console.print("    [dim]flash undeploy <name>[/dim]         Remove an endpoint")
    console.print("    [dim]flash undeploy --all[/dim]          Remove all endpoints")
    console.print(
        "    [dim]flash undeploy --interactive[/dim]  Checkbox selection"
    )
    console.print()


def _cleanup_stale_endpoints(
    resources: Dict[str, DeployableResource], manager: ResourceManager
) -> None:
    """Remove inactive endpoints from tracking (already deleted externally).

    Args:
        resources: Dictionary of resource_id -> DeployableResource
        manager: ResourceManager instance for removing resources
    """
    console.print("[bold]Cleanup stale endpoints[/bold]\n")

    inactive = []
    with console.status("Checking endpoint status..."):
        for resource_id, resource in resources.items():
            color, status_text = _get_resource_status(resource)
            if status_text == "inactive":
                inactive.append((resource_id, resource))

    if not inactive:
        console.print("[green]No inactive endpoints found[/green]")
        return

    console.print(f"Found [yellow]{len(inactive)}[/yellow] inactive endpoint(s):")
    for resource_id, resource in inactive:
        console.print(f"  {resource.name}  {getattr(resource, 'id', 'N/A')}")

    if not Confirm.ask(
        "\n[yellow]Remove these from tracking?[/yellow]",
        default=False,
    ):
        console.print("[yellow]Cancelled[/yellow]")
        return

    removed_count = 0
    for resource_id, resource in inactive:
        result = asyncio.run(
            manager.undeploy_resource(resource_id, resource.name, force_remove=True)
        )

        removed_count += 1
        console.print(
            f"  [green]Removed[/green] {resource.name}"
        )

    console.print(f"\n[green]Cleaned up {removed_count} endpoint(s)[/green]")


def undeploy_command(
    name: Optional[str] = typer.Argument(
        None, help="Name of the endpoint to undeploy (or 'list' to show all)"
    ),
    all: bool = typer.Option(False, "--all", help="Undeploy all endpoints"),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Interactive selection with checkboxes"
    ),
    cleanup_stale: bool = typer.Option(
        False,
        "--cleanup-stale",
        help="Remove inactive endpoints from tracking (already deleted externally)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force operation without confirmation prompts"
    ),
):
    """Undeploy (delete) RunPod serverless endpoints.

    Examples:

        # List all endpoints
        flash undeploy list

        # Undeploy specific endpoint by name
        flash undeploy my-api

        # Undeploy all endpoints (with confirmation)
        flash undeploy --all

        # Undeploy all endpoints without confirmation
        flash undeploy --all --force

        # Interactive selection
        flash undeploy --interactive

        # Remove stale endpoint tracking (already deleted externally)
        flash undeploy --cleanup-stale
    """
    if name == "list":
        list_command()
        return

    manager = _get_resource_manager()
    resources = manager.list_all_resources()

    if not resources:
        console.print("No endpoints found to undeploy.")
        return

    if cleanup_stale:
        _cleanup_stale_endpoints(resources, manager)
        return

    if interactive:
        _interactive_undeploy(resources, skip_confirm=force)
    elif all:
        _undeploy_all(resources, skip_confirm=force)
    elif name:
        _undeploy_by_name(name, resources, skip_confirm=force)
    else:
        console.print(
            "[red]Error:[/red] Please specify a name, use --all/--interactive, or run `flash undeploy list`"
        )
        raise typer.Exit(0)


def _undeploy_by_name(name: str, resources: dict, skip_confirm: bool = False):
    """Undeploy endpoints matching the given name.

    Args:
        name: Name to search for
        resources: Dict of all resources
        skip_confirm: Skip confirmation prompts
    """
    matches = []
    for resource_id, resource in resources.items():
        if hasattr(resource, "name") and resource.name == name:
            matches.append((resource_id, resource))

    if not matches:
        console.print(f"[red]Error:[/red] No endpoint found with name '{name}'")
        console.print(
            "\n  [dim]flash undeploy list[/dim]  Show available endpoints"
        )
        raise typer.Exit(1)

    console.print()
    for resource_id, resource in matches:
        endpoint_id = getattr(resource, "id", "N/A")
        console.print(f"  [bold]{resource.name}[/bold]  {endpoint_id}")
    console.print("\n  [yellow]This action cannot be undone.[/yellow]\n")

    if not skip_confirm:
        try:
            confirmed = questionary.confirm(
                f"Are you sure you want to delete {len(matches)} endpoint(s)?"
            ).ask()

            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    console.print()
    manager = _get_resource_manager()
    results = []
    for resource_id, resource in matches:
        with console.status(f"Deleting {resource.name}..."):
            result = asyncio.run(manager.undeploy_resource(resource_id, resource.name))
        if result["success"]:
            console.print(f"  [green]Deleted[/green] {resource.name}")
        else:
            console.print(f"  [red]Failed[/red] {resource.name}")
        results.append(result)

    _print_undeploy_summary(results)


def _undeploy_all(resources: dict, skip_confirm: bool = False):
    """Undeploy all endpoints with confirmation.

    Args:
        resources: Dict of all resources
        skip_confirm: Skip confirmation prompts
    """
    console.print()
    for resource_id, resource in resources.items():
        name = getattr(resource, "name", "N/A")
        endpoint_id = getattr(resource, "id", "N/A")
        console.print(f"  [bold]{name}[/bold]  {endpoint_id}")
    console.print(
        f"\n  [yellow]All {len(resources)} endpoint(s) will be deleted. "
        f"This action cannot be undone.[/yellow]\n"
    )

    if not skip_confirm:
        try:
            confirmed = questionary.confirm(
                f"Are you sure you want to delete ALL {len(resources)} endpoints?"
            ).ask()

            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

            typed_confirm = questionary.text("Type 'DELETE ALL' to confirm:").ask()

            if typed_confirm != "DELETE ALL":
                console.print("[red]Confirmation failed[/red] - text does not match")
                raise typer.Exit(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    console.print()
    manager = _get_resource_manager()
    results = []
    for resource_id, resource in resources.items():
        name = getattr(resource, "name", "N/A")
        with console.status(f"Deleting {name}..."):
            result = asyncio.run(manager.undeploy_resource(resource_id, name))
        if result["success"]:
            console.print(f"  [green]Deleted[/green] {name}")
        else:
            console.print(f"  [red]Failed[/red] {name}")
        results.append(result)

    _print_undeploy_summary(results)


def _interactive_undeploy(resources: dict, skip_confirm: bool = False):
    """Interactive checkbox selection for undeploying endpoints.

    Args:
        resources: Dict of all resources
        skip_confirm: Skip confirmation prompts
    """
    choices = []
    resource_map = {}

    for resource_id, resource in resources.items():
        name = getattr(resource, "name", "N/A")
        endpoint_id = getattr(resource, "id", "N/A")
        color, status_text = _get_resource_status(resource)

        choice_text = f"{name} ({endpoint_id}) - {status_text}"
        choices.append(choice_text)
        resource_map[choice_text] = (resource_id, resource)

    try:
        selected = questionary.checkbox(
            "Select endpoints to undeploy (Space to select, Enter to confirm):",
            choices=choices,
        ).ask()

        if not selected:
            console.print("No endpoints selected")
            raise typer.Exit(0)

        selected_resources = []
        console.print()
        for choice in selected:
            resource_id, resource = resource_map[choice]
            selected_resources.append((resource_id, resource))
            name = getattr(resource, "name", "N/A")
            endpoint_id = getattr(resource, "id", "N/A")
            console.print(f"  [bold]{name}[/bold]  {endpoint_id}")
        console.print("\n  [yellow]This action cannot be undone.[/yellow]\n")

        if not skip_confirm:
            confirmed = questionary.confirm(
                f"Are you sure you want to delete {len(selected)} endpoint(s)?"
            ).ask()

            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
        raise typer.Exit(0)

    console.print()
    manager = _get_resource_manager()
    results = []
    for resource_id, resource in selected_resources:
        name = getattr(resource, "name", "N/A")
        with console.status(f"Deleting {name}..."):
            result = asyncio.run(manager.undeploy_resource(resource_id, name))
        if result["success"]:
            console.print(f"  [green]Deleted[/green] {name}")
        else:
            console.print(f"  [red]Failed[/red] {name}")
        results.append(result)

    _print_undeploy_summary(results)


def _print_undeploy_summary(results: list[dict]):
    """Print summary after undeploy operations."""
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    console.print()
    if fail_count == 0:
        console.print(
            f"[green]Deleted[/green] {success_count} "
            f"endpoint{'s' if success_count != 1 else ''}"
        )
    else:
        console.print(
            f"[red]{fail_count}[/red] of {len(results)} endpoint(s) failed to delete"
        )
        for result in results:
            if not result["success"]:
                console.print(f"  {result['message']}")
