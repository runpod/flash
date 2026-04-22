"""Flash env commands - environment management."""

import asyncio

import questionary
import typer
from rich.console import Console

from ..utils.app import discover_flash_project
from ..utils.formatting import format_datetime, print_error

from runpod_flash.core.resources.app import FlashApp, FlashAppNotFoundError

console = Console(highlight=False)


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

    with console.status("[dim]undeploying resources...[/dim]"):
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
        print_error(console, "failed to undeploy all resources")
        for message in failures:
            console.print(f"  [dim]{message}[/dim]")
        raise typer.Exit(1)

    if undeployed:
        console.print(
            f"[green]\u2713[/green] undeployed {undeployed} resource{'s' if undeployed != 1 else ''}"
        )


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
    try:
        app = await FlashApp.from_name(app_name)
    except FlashAppNotFoundError:
        console.print(f"\n  no app named [bold]{app_name}[/bold] found")
        console.print("  run [bold]flash deploy[/bold] to create one\n")
        return
    envs = await app.list_environments()

    if not envs:
        console.print(f"\n  no environments for [bold]{app_name}[/bold]")
        console.print("  run [bold]flash deploy[/bold] to create one\n")
        return

    console.print(f"\n  [bold]{app_name}[/bold]\n")

    mn = max(len(e.get("name", "") or "") for e in envs)

    for env in envs:
        name = env.get("name", "(unnamed)")
        build_id = env.get("activeBuildId") or "-"
        short_build = build_id[:12] if len(build_id) > 12 else build_id
        created = format_datetime(env.get("createdAt"))

        console.print(
            f"  [white]{name:<{mn}}[/white]"
            f"  [dim]{short_build}  {created}[/dim]"
        )

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
        f"[green]\u2713[/green] created environment [bold]{env_name}[/bold]"
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

    build_id = env.get("activeBuildId") or "-"
    short_build = build_id[:12] if len(build_id) > 12 else build_id

    console.print(f"\n  [bold]{env.get('name')}[/bold]\n")
    console.print(f"  [dim]app    [/dim] {app_name}")
    console.print(f"  [dim]build  [/dim] {short_build}")

    endpoints = env.get("endpoints") or []
    network_volumes = env.get("networkVolumes") or []

    if endpoints:
        console.print()
        mn = max(len(ep.get("name", "") or "") for ep in endpoints)
        for ep in endpoints:
            ep_name = ep.get("name", "-")
            ep_id = ep.get("id", "")
            console.print(
                f"  [white]{ep_name:<{mn}}[/white]  [dim]{ep_id}[/dim]"
            )

    if network_volumes:
        console.print()
        mn = max(len(nv.get("name", "") or "") for nv in network_volumes)
        for nv in network_volumes:
            console.print(
                f"  [white]{nv.get('name', '-'):<{mn}}[/white]  [dim]{nv.get('id', '')}[/dim]"
            )

    if not endpoints and not network_volumes:
        console.print(
            f"\n  [dim]no resources. run[/dim] [bold]flash deploy --env {env_name}[/bold]"
        )

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
        print_error(console, f"failed to fetch environment info: {e}")
        raise typer.Exit(1)

    console.print(f"\n  deleting [bold]{env_name}[/bold]")

    try:
        confirmed = questionary.confirm(
            f"are you sure? this will delete all resources in '{env_name}'"
        ).ask()

        if not confirmed:
            console.print("[dim]cancelled[/dim]")
            raise typer.Exit(0)
    except KeyboardInterrupt:
        console.print("\n[dim]cancelled[/dim]")
        raise typer.Exit(0)

    asyncio.run(_delete_environment(app_name, env_name))


async def _fetch_environment_info(app_name: str, env_name: str) -> dict:
    app = await FlashApp.from_name(app_name)
    return await app.get_environment_by_name(env_name)


async def _delete_environment(app_name: str, env_name: str):
    app = await FlashApp.from_name(app_name)
    env = await app.get_environment_by_name(env_name)

    await _undeploy_environment_resources(env_name, env)

    with console.status("[dim]deleting environment...[/dim]"):
        success = await app.delete_environment(env_name)

    if success:
        console.print(f"[green]\u2713[/green] deleted environment [bold]{env_name}[/bold]")
    else:
        print_error(console, f"failed to delete environment '{env_name}'")
        raise typer.Exit(1)
