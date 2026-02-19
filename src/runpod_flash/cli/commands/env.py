"""Flash env commands - environment management."""

import asyncio

import questionary
import typer
from rich.console import Console

from ..utils.app import discover_flash_project
from ..utils.formatting import format_datetime

from runpod_flash.core.resources.app import FlashApp

console = Console()

STATE_STYLE = {"HEALTHY": "green", "BUILDING": "cyan", "ERROR": "red"}


def _state_dot(state: str) -> str:
    color = STATE_STYLE.get(state, "yellow")
    return f"[{color}]●[/{color}]"


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
        console.print(f"\nNo environments for [bold]{app_name}[/bold].")
        console.print(f"  Run [bold]flash deploy[/bold] to create one.\n")
        return

    console.print(f"\n  [bold]{app_name}[/bold]  {len(envs)} environment{'s' if len(envs) != 1 else ''}\n")
    for env in envs:
        name = env.get("name", "(unnamed)")
        state = env.get("state", "UNKNOWN")
        color = STATE_STYLE.get(state, "yellow")
        build = env.get("activeBuildId")
        created = format_datetime(env.get("createdAt"))

        console.print(
            f"    {_state_dot(state)} [bold]{name}[/bold]  "
            f"[{color}]{state.lower()}[/{color}]"
        )
        parts = []
        if build:
            parts.append(f"build {build}")
        parts.append(f"created {created}")
        console.print(f"      [dim]{'  ·  '.join(parts)}[/dim]")

    console.print()


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

    console.print(
        f"[green]✓[/green] Created environment [bold]{env_name}[/bold]  "
        f"[dim]{env.get('id')}[/dim]"
    )


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

    state = env.get("state", "UNKNOWN")
    color = STATE_STYLE.get(state, "yellow")

    console.print(
        f"\n  {_state_dot(state)} [bold]{env.get('name')}[/bold]  "
        f"[{color}]{state.lower()}[/{color}]"
    )
    console.print(f"    [dim]id[/dim]     {env.get('id')}")
    console.print(f"    [dim]app[/dim]    {app_name}")
    console.print(f"    [dim]build[/dim]  {env.get('activeBuildId') or 'none'}")

    endpoints = env.get("endpoints") or []
    network_volumes = env.get("networkVolumes") or []

    if endpoints:
        console.print(f"\n  [bold]Endpoints[/bold]")
        for ep in endpoints:
            console.print(
                f"    ▸ [bold]{ep.get('name', '-')}[/bold]  [dim]{ep.get('id', '')}[/dim]"
            )

    if network_volumes:
        console.print(f"\n  [bold]Network Volumes[/bold]")
        for nv in network_volumes:
            console.print(
                f"    ▸ [bold]{nv.get('name', '-')}[/bold]  [dim]{nv.get('id', '')}[/dim]"
            )

    if not endpoints and not network_volumes:
        console.print(f"\n    No resources deployed yet.")
        console.print(f"    Run [bold]flash deploy --env {env_name}[/bold] to deploy.")
    else:
        console.print(f"\n  [bold]Commands[/bold]")
        console.print(f"    [dim]flash deploy --env {env_name}[/dim]  Update deployment")
        console.print(f"    [dim]flash env delete {env_name}[/dim]    Tear down")

    console.print()


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
        console.print(f"[red]✗[/red] Failed to fetch environment info: {e}")
        raise typer.Exit(1)

    console.print(f"\nDeleting [bold]{env_name}[/bold]  [dim]{env.get('id')}[/dim]")

    try:
        confirmed = questionary.confirm(
            f"Are you sure you want to delete environment '{env_name}'? "
            "This will delete all resources associated with this environment!"
        ).ask()

        if not confirmed:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
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
        console.print(f"[green]✓[/green] Deleted environment [bold]{env_name}[/bold]")
    else:
        console.print(f"[red]✗[/red] Failed to delete environment '{env_name}'")
        raise typer.Exit(1)
