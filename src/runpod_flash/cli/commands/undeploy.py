"""Undeploy command for managing RunPod serverless endpoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Dict, Optional, Tuple
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
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
    """Get resource status with icon and text.

    Args:
        resource: DeployableResource to check

    Returns:
        Tuple of (status_icon, status_text)
    """
    try:
        if resource.is_deployed():
            return "🟢", "Active"
        return "🔴", "Inactive"
    except Exception:
        return "❓", "Unknown"


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
        console.print(
            Panel(
                "No endpoints found\n\n"
                "Endpoints are automatically tracked when you use @remote decorator.",
                title="Tracked Endpoints",
                expand=False,
            )
        )
        return

    table = Table(title="Tracked RunPod Serverless Endpoints")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Endpoint ID", style="magenta")
    table.add_column("Status", justify="center")
    table.add_column("Type", style="yellow")
    table.add_column("Resource ID", style="dim", no_wrap=True)

    active_count = 0
    inactive_count = 0

    for resource_id, resource in resources.items():
        status_icon, status_text = _get_resource_status(resource)
        if status_text == "Active":
            active_count += 1
        elif status_text == "Inactive":
            inactive_count += 1

        # Get name if available
        name = getattr(resource, "name", "N/A")
        endpoint_id = getattr(resource, "id", "N/A")
        resource_type = _get_resource_type(resource)

        # Truncate resource_id for display
        display_resource_id = (
            resource_id[:12] + "..." if len(resource_id) > 12 else resource_id
        )

        table.add_row(
            name,
            endpoint_id,
            f"{status_icon} {status_text}",
            resource_type,
            display_resource_id,
        )

    console.print(table)

    # Summary
    total = len(resources)
    unknown_count = total - active_count - inactive_count
    summary = f"Total: {total} endpoint{'s' if total != 1 else ''}"
    if active_count > 0:
        summary += f" ({active_count} active"
    if inactive_count > 0:
        summary += (
            f", {inactive_count} inactive"
            if active_count > 0
            else f" ({inactive_count} inactive"
        )
    if unknown_count > 0:
        summary += (
            f", {unknown_count} unknown"
            if (active_count > 0 or inactive_count > 0)
            else f" ({unknown_count} unknown"
        )
    if active_count > 0 or inactive_count > 0 or unknown_count > 0:
        summary += ")"

    console.print(f"\n{summary}\n")
    console.print("💡 Use [bold]flash undeploy <name>[/bold] to remove an endpoint")
    console.print("💡 Use [bold]flash undeploy --all[/bold] to remove all endpoints")
    console.print(
        "💡 Use [bold]flash undeploy --interactive[/bold] for checkbox selection"
    )


def _cleanup_stale_endpoints(
    resources: Dict[str, DeployableResource], manager: ResourceManager
) -> None:
    """Remove inactive endpoints from tracking (already deleted externally).

    Args:
        resources: Dictionary of resource_id -> DeployableResource
        manager: ResourceManager instance for removing resources
    """
    console.print(
        Panel(
            "Checking for inactive endpoints...\n\n"
            "This will remove endpoints from tracking that are no longer active\n"
            "(already deleted via RunPod UI or API).",
            title="Cleanup Stale Endpoints",
            expand=False,
        )
    )

    # Find inactive endpoints
    inactive = []
    with console.status("Checking endpoint status..."):
        for resource_id, resource in resources.items():
            status_icon, status_text = _get_resource_status(resource)
            if status_text == "Inactive":
                inactive.append((resource_id, resource))

    if not inactive:
        console.print("\n[green]✓[/green] No inactive endpoints found")
        return

    # Show what will be removed
    console.print(f"\nFound [yellow]{len(inactive)}[/yellow] inactive endpoint(s):")
    for resource_id, resource in inactive:
        console.print(f"  • {resource.name} ({getattr(resource, 'id', 'N/A')})")

    # Confirm removal
    if not Confirm.ask(
        "\n[yellow]⚠️  Remove these from tracking?[/yellow]",
        default=False,
    ):
        console.print("[yellow]Cancelled[/yellow]")
        return

    # Undeploy inactive endpoints (force remove from tracking even if already deleted remotely)
    removed_count = 0
    for resource_id, resource in inactive:
        result = asyncio.run(
            manager.undeploy_resource(resource_id, resource.name, force_remove=True)
        )

        if result["success"]:
            removed_count += 1
            console.print(
                f"[green]✓[/green] Removed [cyan]{resource.name}[/cyan] from tracking"
            )
        else:
            # Resource already deleted remotely, but force_remove cleaned up tracking
            removed_count += 1
            console.print(
                f"[yellow]⚠[/yellow] {resource.name}: Already deleted remotely, removed from tracking"
            )

    console.print(f"\n[green]✓[/green] Cleaned up {removed_count} inactive endpoint(s)")


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
    # Handle "list" as a special case
    if name == "list":
        list_command()
        return

    manager = _get_resource_manager()
    resources = manager.list_all_resources()

    if not resources:
        console.print(
            Panel(
                "No endpoints found to undeploy\n\n"
                "Use @remote decorator to deploy endpoints.",
                title="No Endpoints",
                expand=False,
            )
        )
        return

    # Handle cleanup-stale mode
    if cleanup_stale:
        _cleanup_stale_endpoints(resources, manager)
        return

    # Handle different modes
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
        # Exit 0: Treat usage help display as successful operation for better UX
        raise typer.Exit(0)


def _undeploy_by_name(name: str, resources: dict, skip_confirm: bool = False):
    """Undeploy endpoints matching the given name.

    Args:
        name: Name to search for
        resources: Dict of all resources
        skip_confirm: Skip confirmation prompts
    """
    # Find matching resources
    matches = []
    for resource_id, resource in resources.items():
        if hasattr(resource, "name") and resource.name == name:
            matches.append((resource_id, resource))

    if not matches:
        console.print(f"[red]Error:[/red] No endpoint found with name '{name}'")
        console.print(
            "\nUse [bold]flash undeploy list[/bold] to see available endpoints"
        )
        raise typer.Exit(1)

    # Show what will be deleted
    console.print()
    for resource_id, resource in matches:
        endpoint_id = getattr(resource, "id", "N/A")
        console.print(f"  [bold]{resource.name}[/bold]  [dim]({endpoint_id})[/dim]")
    console.print()
    console.print("  [yellow]This action cannot be undone.[/yellow]")
    console.print()

    if not skip_confirm:
        try:
            confirmed = questionary.confirm(
                f"Are you sure you want to delete {len(matches)} endpoint(s)?"
            ).ask()

            if not confirmed:
                console.print("Cancelled.")
                raise typer.Exit(0)
        except KeyboardInterrupt:
            console.print("\nCancelled.")
            raise typer.Exit(0)

    console.print()
    manager = _get_resource_manager()
    results = []
    for resource_id, resource in matches:
        with console.status(f"  Deleting [bold]{resource.name}[/bold]..."):
            result = asyncio.run(manager.undeploy_resource(resource_id, resource.name))
        if result["success"]:
            console.print(f"  [green]✓[/green] Deleted [bold]{resource.name}[/bold]")
        else:
            console.print(
                f"  [red]✗[/red] Failed to delete [bold]{resource.name}[/bold]"
            )
        results.append(result)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    console.print()
    if fail_count == 0:
        console.print(
            f"[green]✓[/green] Successfully deleted {success_count} "
            f"endpoint{'s' if success_count != 1 else ''}"
        )
    else:
        console.print(
            f"[red]✗[/red] {fail_count} of {len(results)} endpoint(s) failed to delete"
        )
        for result in results:
            if not result["success"]:
                console.print(f"  {result['message']}")


def _undeploy_all(resources: dict, skip_confirm: bool = False):
    """Undeploy all endpoints with confirmation.

    Args:
        resources: Dict of all resources
        skip_confirm: Skip confirmation prompts
    """
    # Show what will be deleted
    console.print()
    for resource_id, resource in resources.items():
        name = getattr(resource, "name", "N/A")
        endpoint_id = getattr(resource, "id", "N/A")
        console.print(f"  [bold]{name}[/bold]  [dim]({endpoint_id})[/dim]")
    console.print()
    console.print(
        f"  [yellow]All {len(resources)} endpoint(s) will be deleted. "
        f"This action cannot be undone.[/yellow]"
    )
    console.print()

    if not skip_confirm:
        try:
            confirmed = questionary.confirm(
                f"Are you sure you want to delete ALL {len(resources)} endpoints?"
            ).ask()

            if not confirmed:
                console.print("Cancelled.")
                raise typer.Exit(0)

            # Double confirmation for --all
            typed_confirm = questionary.text("Type 'DELETE ALL' to confirm:").ask()

            if typed_confirm != "DELETE ALL":
                console.print("Confirmation failed - text does not match")
                raise typer.Exit(1)
        except KeyboardInterrupt:
            console.print("\nCancelled.")
            raise typer.Exit(0)

    console.print()
    manager = _get_resource_manager()
    results = []
    for resource_id, resource in resources.items():
        name = getattr(resource, "name", "N/A")
        with console.status(f"  Deleting [bold]{name}[/bold]..."):
            result = asyncio.run(manager.undeploy_resource(resource_id, name))
        if result["success"]:
            console.print(f"  [green]✓[/green] Deleted [bold]{name}[/bold]")
        else:
            console.print(f"  [red]✗[/red] Failed to delete [bold]{name}[/bold]")
        results.append(result)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    console.print()
    if fail_count == 0:
        console.print(
            f"[green]✓[/green] Successfully deleted {success_count} "
            f"endpoint{'s' if success_count != 1 else ''}"
        )
    else:
        console.print(
            f"[red]✗[/red] {fail_count} of {len(results)} endpoint(s) failed to delete"
        )
        for result in results:
            if not result["success"]:
                console.print(f"  {result['message']}")


def _interactive_undeploy(resources: dict, skip_confirm: bool = False):
    """Interactive checkbox selection for undeploying endpoints.

    Args:
        resources: Dict of all resources
        skip_confirm: Skip confirmation prompts
    """
    # Create choices for questionary
    choices = []
    resource_map = {}

    for resource_id, resource in resources.items():
        name = getattr(resource, "name", "N/A")
        endpoint_id = getattr(resource, "id", "N/A")
        status_icon, status_text = _get_resource_status(resource)

        choice_text = f"{name} ({endpoint_id}) - {status_icon} {status_text}"
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

        # Show confirmation
        selected_resources = []
        console.print()
        for choice in selected:
            resource_id, resource = resource_map[choice]
            selected_resources.append((resource_id, resource))
            name = getattr(resource, "name", "N/A")
            endpoint_id = getattr(resource, "id", "N/A")
            console.print(f"  [bold]{name}[/bold]  [dim]({endpoint_id})[/dim]")
        console.print()
        console.print("  [yellow]This action cannot be undone.[/yellow]")
        console.print()

        if not skip_confirm:
            confirmed = questionary.confirm(
                f"Are you sure you want to delete {len(selected)} endpoint(s)?"
            ).ask()

            if not confirmed:
                console.print("Cancelled.")
                raise typer.Exit(0)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(0)

    console.print()
    manager = _get_resource_manager()
    results = []
    for resource_id, resource in selected_resources:
        name = getattr(resource, "name", "N/A")
        with console.status(f"  Deleting [bold]{name}[/bold]..."):
            result = asyncio.run(manager.undeploy_resource(resource_id, name))
        if result["success"]:
            console.print(f"  [green]✓[/green] Deleted [bold]{name}[/bold]")
        else:
            console.print(f"  [red]✗[/red] Failed to delete [bold]{name}[/bold]")
        results.append(result)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    console.print()
    if fail_count == 0:
        console.print(
            f"[green]✓[/green] Successfully deleted {success_count} "
            f"endpoint{'s' if success_count != 1 else ''}"
        )
    else:
        console.print(
            f"[red]✗[/red] {fail_count} of {len(results)} endpoint(s) failed to delete"
        )
        for result in results:
            if not result["success"]:
                console.print(f"  {result['message']}")
