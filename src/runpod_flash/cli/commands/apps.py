"""Deployment environment management commands."""

import asyncio

import typer
from rich.console import Console

from runpod_flash.cli.utils.formatting import format_datetime
from runpod_flash.core.resources.app import FlashApp

console = Console()

apps_app = typer.Typer(short_help="Manage existing apps", name="app")


@apps_app.command("create", short_help="Create a new flash app")
def create(app_name: str = typer.Argument(..., help="Name for the new flash app")):
    return asyncio.run(create_flash_app(app_name))


@apps_app.command("get", short_help="Get detailed information about a flash app")
def get(app_name: str = typer.Argument(..., help="Name of the flash app")):
    return asyncio.run(get_flash_app(app_name))


@apps_app.command("list", short_help="List existing apps under your account.")
def list_command():
    return asyncio.run(list_flash_apps())


@apps_app.command(
    "delete", short_help="Delete an existing flash app and all its associated resources"
)
def delete(
    app_name: str = typer.Argument(..., help="Name of the flash app to delete"),
):
    return asyncio.run(delete_flash_app(app_name))


async def list_flash_apps():
    apps = await FlashApp.list()
    if not apps:
        console.print("No Flash apps found.")
        return

    console.print(f"\n[bold]Apps[/bold]\n")
    for app in apps:
        name = app.get("name", "(unnamed)")
        app_id = app.get("id", "")
        environments = app.get("flashEnvironments") or []
        env_names = ", ".join(env.get("name", "?") for env in environments) or "-"
        builds = app.get("flashBuilds") or []
        console.print(f"  [bold]{name}[/bold]  {app_id}")
        console.print(f"    envs: {env_names}  builds: {len(builds)}")


async def create_flash_app(app_name: str):
    with console.status(f"Creating flash app: {app_name}"):
        app = await FlashApp.create(app_name)

    console.print(f"[green]Created[/green] app [bold]{app_name}[/bold]  {app.id}")


async def get_flash_app(app_name: str):
    with console.status(f"Fetching flash app: {app_name}"):
        app = await FlashApp.from_name(app_name)
        envs, builds = await asyncio.gather(app.list_environments(), app.list_builds())

    console.print(f"\n[bold]{app.name}[/bold]  {app.id}")

    if envs:
        console.print(f"\n[bold]Environments[/bold]")
        for env in envs:
            state = env.get("state", "UNKNOWN")
            state_color = "green" if state == "HEALTHY" else "yellow"
            console.print(
                f"  [bold]{env.get('name')}[/bold]  "
                f"[{state_color}]{state}[/{state_color}]  "
                f"{env.get('id', '-')}"
            )
            build_id = env.get("activeBuildId") or "-"
            created = format_datetime(env.get("createdAt"))
            console.print(f"    build {build_id}  created {created}")
    else:
        console.print("\nNo environments")

    if builds:
        console.print(f"\n[bold]Builds[/bold]")
        for build in builds:
            console.print(
                f"  {build.get('id')}  {format_datetime(build.get('createdAt'))}"
            )
    else:
        console.print("\nNo builds")


async def delete_flash_app(app_name: str):
    with console.status(f"Deleting flash app: {app_name}"):
        success = await FlashApp.delete(app_name=app_name)

    if success:
        console.print(f"[green]Deleted[/green] app [bold]{app_name}[/bold]")
    else:
        console.print(f"[red]Error:[/red] Failed to delete app '{app_name}'")
        raise typer.Exit(1)


@apps_app.callback(invoke_without_command=True)
def apps(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.command.get_help(ctx))
        raise typer.Exit()
