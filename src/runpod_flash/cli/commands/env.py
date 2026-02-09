"""Flash env commands - environment management."""

import asyncio

import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..utils.app import discover_flash_project

from runpod_flash.core.resources.app import FlashApp

console = Console()


def _get_resource_manager():
    from runpod_flash.core.resources.resource_manager import ResourceManager

    return ResourceManager()


async def _undeploy_environment_resources(env_name: str, env: dict) -> None:
    """Undeploy resources tied to a flash environment before deletion."""
    endpoints = env.get("endpoints") or []
    network_volumes = env.get("networkVolumes") or []

    if not endpoints and not network_volumes:
        return

    manager = _get_resource_manager()
    failures = []
    undeployed = 0
    seen_resource_ids = set()

    with console.status(f"Undeploying resources for '{env_name}'..."):
        for label, items in (
            ("Endpoint", endpoints),
            ("Network volume", network_volumes),
        ):
            for item in items:
                provider_id = item.get("id") if isinstance(item, dict) else None
                name = item.get("name") if isinstance(item, dict) else None
                if not provider_id:
                    failures.append(f"{label} missing id in environment '{env_name}'")
                    continue

                matches = manager.find_resources_by_provider_id(provider_id)
                if not matches:
                    display_name = name if name else provider_id
                    failures.append(
                        f"{label} '{display_name}' ({provider_id}) not found in local tracking"
                    )
                    continue

                for resource_id, resource in matches:
                    if resource_id in seen_resource_ids:
                        continue
                    seen_resource_ids.add(resource_id)
                    resource_name = getattr(resource, "name", name) or provider_id
                    result = await manager.undeploy_resource(resource_id, resource_name)
                    if result.get("success"):
                        undeployed += 1
                    else:
                        failures.append(
                            result.get(
                                "message",
                                f"Failed to undeploy {label.lower()} '{resource_name}'",
                            )
                        )

    if failures:
        console.print("Failed to undeploy all resources; environment deletion aborted.")
        for message in failures:
            console.print(f"  - {message}")
        raise typer.Exit(1)

    if undeployed:
        console.print(f"Undeployed {undeployed} resource(s) for '{env_name}'")


def list_command(
    app_name: str | None = typer.Option(
        None, "--app", "-a", help="Flash app name to inspect"
    ),
):
    """Show available deployment environments."""
    if not app_name:
        _, app_name = discover_flash_project()
    asyncio.run(_list_environments(app_name))


async def _list_environments(app_name: str):
    app = await FlashApp.from_name(app_name)
    envs = await app.list_environments()

    if not envs:
        console.print(f"No environments found for '{app_name}'.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("ID", overflow="fold")
    table.add_column("Active Build", overflow="fold")
    table.add_column("Created At", overflow="fold")

    for env in envs:
        table.add_row(
            env.get("name"),
            env.get("id"),
            env.get("activeBuildId", "-"),
            env.get("createdAt"),
        )

    console.print(table)


def create_command(
    app_name: str | None = typer.Option(
        None, "--app", "-a", help="Flash app name to create a new environment in"
    ),
    name: str = typer.Argument(
        ..., help="Name of the deployment environment to create"
    ),
):
    """Create a new deployment environment."""
    if not app_name:
        _, app_name = discover_flash_project()
    assert app_name is not None
    asyncio.run(_create_environment(app_name, name))


async def _create_environment(app_name: str, env_name: str):
    app, env = await FlashApp.create_environment_and_app(app_name, env_name)

    panel_content = (
        f"Environment '[bold]{env_name}[/bold]' created successfully\n\n"
        f"App: {app_name}\n"
        f"Environment ID: {env.get('id')}\n"
        f"Status: {env.get('state', 'PENDING')}"
    )
    console.print(Panel(panel_content, title="Environment Created", expand=False))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("ID", overflow="fold")
    table.add_column("Status", overflow="fold")
    table.add_column("Created At", overflow="fold")

    table.add_row(
        env.get("name"),
        env.get("id"),
        env.get("state", "PENDING"),
        env.get("createdAt", "Just now"),
    )
    console.print(table)


def get_command(
    env_name: str = typer.Argument(..., help="Name of the deployment environment"),
    app_name: str = typer.Option(None, "--app", "-a", help="Flash app name"),
):
    """Show detailed information about a deployment environment."""
    if not app_name:
        _, app_name = discover_flash_project()
    asyncio.run(_get_environment(app_name, env_name))


async def _get_environment(app_name: str, env_name: str):
    app = await FlashApp.from_name(app_name)
    env = await app.get_environment_by_name(env_name)

    main_info = f"Environment: {env.get('name')}\n"
    main_info += f"ID: {env.get('id')}\n"
    main_info += f"State: {env.get('state', 'UNKNOWN')}\n"
    main_info += f"Active Build: {env.get('activeBuildId', 'None')}\n"

    if env.get("createdAt"):
        main_info += f"Created: {env.get('createdAt')}\n"

    console.print(Panel(main_info, title=f"Environment: {env_name}", expand=False))

    endpoints = env.get("endpoints") or []
    if endpoints:
        endpoint_table = Table(title="Associated Endpoints")
        endpoint_table.add_column("Name", style="cyan")
        endpoint_table.add_column("ID", overflow="fold")

        for endpoint in endpoints:
            endpoint_table.add_row(
                endpoint.get("name", "-"),
                endpoint.get("id", "-"),
            )
        console.print(endpoint_table)

    network_volumes = env.get("networkVolumes") or []
    if network_volumes:
        nv_table = Table(title="Associated Network Volumes")
        nv_table.add_column("Name", style="cyan")
        nv_table.add_column("ID", overflow="fold")

        for nv in network_volumes:
            nv_table.add_row(
                nv.get("name", "-"),
                nv.get("id", "-"),
            )
        console.print(nv_table)


def delete_command(
    env_name: str = typer.Argument(
        ..., help="Name of the deployment environment to delete"
    ),
    app_name: str = typer.Option(None, "--app", "-a", help="Flash app name"),
):
    """Delete a deployment environment."""
    if not app_name:
        _, app_name = discover_flash_project()

    try:
        env = asyncio.run(_fetch_environment_info(app_name, env_name))
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to fetch environment info: {e}")
        raise typer.Exit(1)

    panel_content = (
        f"Environment '[bold]{env_name}[/bold]' will be deleted\n\n"
        f"Environment ID: {env.get('id')}\n"
        f"App: {app_name}\n"
        f"Active Build: {env.get('activeBuildId', 'None')}"
    )
    console.print(Panel(panel_content, title="Delete Confirmation", expand=False))

    try:
        confirmed = questionary.confirm(
            f"Are you sure you want to delete environment '{env_name}'? "
            "This will delete all resources associated with this environment!"
        ).ask()

        if not confirmed:
            console.print("Deletion cancelled")
            raise typer.Exit(0)
    except KeyboardInterrupt:
        console.print("\nDeletion cancelled")
        raise typer.Exit(0)

    asyncio.run(_delete_environment(app_name, env_name))


async def _fetch_environment_info(app_name: str, env_name: str) -> dict:
    app = await FlashApp.from_name(app_name)
    return await app.get_environment_by_name(env_name)


async def _delete_environment(app_name: str, env_name: str):
    app = await FlashApp.from_name(app_name)
    env = await app.get_environment_by_name(env_name)

    await _undeploy_environment_resources(env_name, env)

    with console.status(f"Deleting environment '{env_name}'..."):
        success = await app.delete_environment(env_name)

    if success:
        console.print(f"Environment '{env_name}' deleted successfully")
    else:
        console.print(f"[red]Failed to delete environment '{env_name}'[/red]")
        raise typer.Exit(1)
