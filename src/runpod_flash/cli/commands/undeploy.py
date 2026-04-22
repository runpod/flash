"""Undeploy command for managing RunPod serverless endpoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Dict, Optional, Tuple
import typer
from rich.console import Console

import questionary

from runpod_flash.cli.utils.formatting import print_error

if TYPE_CHECKING:
    from ...core.resources.base import DeployableResource
    from ...core.resources.resource_manager import ResourceManager

console = Console(highlight=False)


def _get_resource_manager():
    from ...core.resources.resource_manager import ResourceManager

    return ResourceManager()


def _get_serverless_resources(
    resources: Dict[str, DeployableResource],
) -> Dict[str, DeployableResource]:
    from ...core.resources.serverless import ServerlessResource

    return {
        resource_id: resource
        for resource_id, resource in resources.items()
        if isinstance(resource, ServerlessResource)
    }


def _get_resource_status(resource) -> Tuple[str, str]:
    try:
        if asyncio.run(resource.is_deployed()):
            return "green", "active"
        return "red", "inactive"
    except Exception:
        return "yellow", "unknown"


def list_command():
    """List all deployed endpoints tracked in .flash/resources.pkl."""
    manager = _get_resource_manager()
    all_resources = manager.list_all_resources()
    resources = _get_serverless_resources(all_resources)

    if not resources:
        console.print("\n  no endpoints found\n")
        return

    rows = []
    for resource_id, resource in resources.items():
        color, status = _get_resource_status(resource)
        name = getattr(resource, "name", "-")
        endpoint_id = getattr(resource, "id", "-")
        rows.append((name, endpoint_id, color, status))

    mn = max(len(r[0]) for r in rows)

    console.print()
    for name, eid, color, status in rows:
        console.print(
            f"  [{color}]\u25cf[/{color}] [white]{name:<{mn}}[/white]  [dim]{eid}[/dim]"
        )
    console.print()


def _cleanup_stale_endpoints(
    resources: Dict[str, DeployableResource], manager: ResourceManager
) -> None:
    inactive = []
    with console.status("[dim]checking endpoints...[/dim]"):
        for resource_id, resource in resources.items():
            _, status = _get_resource_status(resource)
            if status == "inactive":
                inactive.append((resource_id, resource))

    if not inactive:
        console.print("[green]\u2713[/green] no inactive endpoints")
        return

    console.print()
    for resource_id, resource in inactive:
        console.print(
            f"  [red]\u25cf[/red] [white]{resource.name}[/white]"
            f"  [dim]{getattr(resource, 'id', '-')}[/dim]"
        )

    console.print()
    try:
        if not questionary.confirm(
            f"remove {len(inactive)} inactive endpoint(s) from tracking?"
        ).ask():
            console.print("[dim]cancelled[/dim]")
            return
    except KeyboardInterrupt:
        console.print("\n[dim]cancelled[/dim]")
        return

    removed = 0
    for resource_id, resource in inactive:
        result = asyncio.run(
            manager.undeploy_resource(resource_id, resource.name, force_remove=True)
        )
        if result.get("success"):
            removed += 1

    console.print(
        f"[green]\u2713[/green] removed {removed} endpoint{'s' if removed != 1 else ''}"
    )


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

        flash undeploy list
        flash undeploy my-api
        flash undeploy --all
        flash undeploy --interactive
        flash undeploy --cleanup-stale
    """
    if name == "list":
        list_command()
        return

    manager = _get_resource_manager()
    resources = manager.list_all_resources()

    if not resources:
        console.print("\n  no endpoints found\n")
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
        print_error(
            console,
            "specify a name, use --all/--interactive, or run flash undeploy list",
        )
        raise typer.Exit(1)


def _undeploy_by_name(name: str, resources: dict, skip_confirm: bool = False):
    matches = [
        (rid, r)
        for rid, r in resources.items()
        if hasattr(r, "name") and r.name == name
    ]

    if not matches:
        print_error(console, f"no endpoint named '{name}'")
        console.print("  [dim]flash undeploy list[/dim]  show available endpoints")
        raise typer.Exit(1)

    console.print()
    for _, resource in matches:
        eid = getattr(resource, "id", "-")
        console.print(f"  [white]{resource.name}[/white]  [dim]{eid}[/dim]")

    if not skip_confirm:
        console.print()
        try:
            if not questionary.confirm("delete?").ask():
                console.print("[dim]cancelled[/dim]")
                raise typer.Exit(0)
        except KeyboardInterrupt:
            console.print("\n[dim]cancelled[/dim]")
            raise typer.Exit(0)

    manager = _get_resource_manager()
    results = []
    for resource_id, resource in matches:
        with console.status(f"[dim]deleting {resource.name}...[/dim]"):
            result = asyncio.run(manager.undeploy_resource(resource_id, resource.name))
        if result["success"]:
            console.print(f"[green]\u2713[/green] deleted {resource.name}")
        else:
            console.print(f"[red]\u2717[/red] failed to delete {resource.name}")
        results.append(result)


def _undeploy_all(resources: dict, skip_confirm: bool = False):
    mn = max(len(getattr(r, "name", "-")) for r in resources.values())

    console.print()
    for resource in resources.values():
        name = getattr(resource, "name", "-")
        eid = getattr(resource, "id", "-")
        console.print(f"  [white]{name:<{mn}}[/white]  [dim]{eid}[/dim]")

    if not skip_confirm:
        console.print()
        try:
            if not questionary.confirm(f"delete all {len(resources)} endpoints?").ask():
                console.print("[dim]cancelled[/dim]")
                raise typer.Exit(0)

            typed = questionary.text("type 'DELETE ALL' to confirm:").ask()
            if typed != "DELETE ALL":
                console.print("[dim]cancelled[/dim]")
                raise typer.Exit(1)
        except KeyboardInterrupt:
            console.print("\n[dim]cancelled[/dim]")
            raise typer.Exit(0)

    manager = _get_resource_manager()
    deleted = 0
    for resource_id, resource in resources.items():
        name = getattr(resource, "name", "-")
        with console.status(f"[dim]deleting {name}...[/dim]"):
            result = asyncio.run(manager.undeploy_resource(resource_id, name))
        if result["success"]:
            deleted += 1

    console.print(
        f"\n[green]\u2713[/green] deleted {deleted}/{len(resources)} endpoints"
    )


def _interactive_undeploy(resources: dict, skip_confirm: bool = False):
    choices = []
    resource_map = {}

    for resource_id, resource in resources.items():
        name = getattr(resource, "name", "-")
        eid = getattr(resource, "id", "-")
        label = f"{name}  {eid}"
        choices.append(label)
        resource_map[label] = (resource_id, resource)

    try:
        selected = questionary.checkbox(
            "select endpoints to delete:",
            choices=choices,
        ).ask()

        if not selected:
            console.print("[dim]cancelled[/dim]")
            raise typer.Exit(0)

        if not skip_confirm:
            if not questionary.confirm(f"delete {len(selected)} endpoint(s)?").ask():
                console.print("[dim]cancelled[/dim]")
                raise typer.Exit(0)
    except KeyboardInterrupt:
        console.print("\n[dim]cancelled[/dim]")
        raise typer.Exit(0)

    manager = _get_resource_manager()
    deleted = 0
    for choice in selected:
        resource_id, resource = resource_map[choice]
        name = getattr(resource, "name", "-")
        with console.status(f"[dim]deleting {name}...[/dim]"):
            result = asyncio.run(manager.undeploy_resource(resource_id, name))
        if result["success"]:
            deleted += 1

    console.print(
        f"\n[green]\u2713[/green] deleted {deleted}/{len(selected)} endpoints"
    )
