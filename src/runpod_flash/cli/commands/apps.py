"""Deployment environment management commands."""

import asyncio

import typer
from rich.console import Console

from runpod_flash.cli.utils.formatting import format_datetime
from runpod_flash.core.resources.app import FlashApp

console = Console()

STATE_STYLE = {"HEALTHY": "green", "BUILDING": "cyan", "ERROR": "red"}

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


def _state_dot(state: str) -> str:
    color = STATE_STYLE.get(state, "yellow")
    return f"[{color}]●[/{color}]"


async def list_flash_apps():
    apps = await FlashApp.list()
    if not apps:
        console.print("\nNo Flash apps found.")
        console.print("  Run [bold]flash deploy[/bold] to create one.\n")
        return

    console.print()
    for app_data in apps:
        name = app_data.get("name", "(unnamed)")
        app_id = app_data.get("id", "")
        environments = app_data.get("flashEnvironments") or []
        builds = app_data.get("flashBuilds") or []

        env_count = len(environments)
        build_count = len(builds)
        console.print(
            f"  [bold]{name}[/bold]  "
            f"{env_count} env{'s' if env_count != 1 else ''}, "
            f"{build_count} build{'s' if build_count != 1 else ''}  "
            f"[dim]{app_id}[/dim]"
        )

        for env in environments:
            state = env.get("state", "UNKNOWN")
            env_name = env.get("name", "?")
            console.print(f"    {_state_dot(state)} {env_name}  [dim]{state.lower()}[/dim]")

        console.print()


async def create_flash_app(app_name: str):
    with console.status(f"Creating flash app: {app_name}"):
        app = await FlashApp.create(app_name)

    console.print(f"[green]✓[/green] Created app [bold]{app_name}[/bold]  [dim]{app.id}[/dim]")


async def get_flash_app(app_name: str):
    with console.status(f"Fetching flash app: {app_name}"):
        app = await FlashApp.from_name(app_name)
        envs, builds = await asyncio.gather(app.list_environments(), app.list_builds())

    console.print(f"\n  [bold]{app.name}[/bold]  [dim]{app.id}[/dim]")

    # environments
    console.print(f"\n  [bold]Environments[/bold]")
    if envs:
        for env in envs:
            state = env.get("state", "UNKNOWN")
            color = STATE_STYLE.get(state, "yellow")
            name = env.get("name", "(unnamed)")
            build_id = env.get("activeBuildId")
            created = format_datetime(env.get("createdAt"))

            console.print(
                f"    {_state_dot(state)} [bold]{name}[/bold]  "
                f"[{color}]{state.lower()}[/{color}]"
            )
            parts = []
            if build_id:
                parts.append(f"build {build_id}")
            parts.append(f"created {created}")
            console.print(f"      [dim]{'  ·  '.join(parts)}[/dim]")
    else:
        console.print("    [dim]None yet — run [/dim][bold]flash deploy[/bold]")

    # builds — show most recent, summarize the rest
    max_shown = 5
    console.print(f"\n  [bold]Builds ({len(builds)})[/bold]")
    if builds:
        recent = builds[:max_shown]
        for build in recent:
            build_id = build.get("id", "")
            created = format_datetime(build.get("createdAt"))
            console.print(f"    {build_id}  [dim]{created}[/dim]")
        if len(builds) > max_shown:
            console.print(f"    [dim]… and {len(builds) - max_shown} older builds[/dim]")
    else:
        console.print("    [dim]None yet — run [/dim][bold]flash build[/bold]")

    console.print()


async def delete_flash_app(app_name: str):
    with console.status(f"Deleting flash app: {app_name}"):
        success = await FlashApp.delete(app_name=app_name)

    if success:
        console.print(f"[green]✓[/green] Deleted app [bold]{app_name}[/bold]")
    else:
        console.print(f"[red]✗[/red] Failed to delete app '{app_name}'")
        raise typer.Exit(1)


@apps_app.callback(invoke_without_command=True)
def apps(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.command.get_help(ctx))
        raise typer.Exit()
