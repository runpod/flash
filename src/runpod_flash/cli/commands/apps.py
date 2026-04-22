"""CLI commands for managing Flash apps (create, get, list, delete)."""

import asyncio

import typer
from rich.console import Console

from runpod_flash.cli.utils.formatting import (
    format_datetime,
    print_error,
    state_dot,
)
from runpod_flash.core.resources.app import FlashApp

console = Console(highlight=False)

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
        console.print("\n  no apps found")
        console.print("  run [bold]flash deploy[/bold] to create one\n")
        return

    console.print()
    for app_data in apps:
        name = app_data.get("name", "(unnamed)")
        environments = app_data.get("flashEnvironments") or []
        builds = app_data.get("flashBuilds") or []

        env_count = len(environments)
        build_count = len(builds)
        console.print(
            f"  [bold]{name}[/bold]  "
            f"[dim]{env_count} env{'s' if env_count != 1 else ''}  "
            f"{build_count} build{'s' if build_count != 1 else ''}[/dim]"
        )

        for env in environments:
            state = env.get("state", "UNKNOWN")
            env_name = env.get("name", "?")
            console.print(
                f"    {state_dot(state)} {env_name}  [dim]{state.lower()}[/dim]"
            )

    console.print()


async def create_flash_app(app_name: str):
    with console.status("[dim]creating...[/dim]"):
        app = await FlashApp.create(app_name)

    console.print(f"[green]✓[/green] created app [bold]{app_name}[/bold]")


async def get_flash_app(app_name: str):
    with console.status("[dim]fetching...[/dim]"):
        app = await FlashApp.from_name(app_name)
        envs, builds = await asyncio.gather(app.list_environments(), app.list_builds())

    console.print(f"\n  [bold]{app.name}[/bold]\n")

    # environments
    if envs:
        max_name = max(len(e.get("name", "")) for e in envs)
        for env in envs:
            name = env.get("name", "(unnamed)")
            state = env.get("state", "UNKNOWN")
            build_id = env.get("activeBuildId") or "-"
            created = format_datetime(env.get("createdAt"))

            console.print(
                f"  {state_dot(state)} [white]{name:<{max_name}}[/white]  "
                f"[dim]build {build_id}  {created}[/dim]"
            )
    else:
        console.print("  [dim]no environments. run [/dim][bold]flash deploy[/bold]")

    # builds
    if builds:
        console.print(f"\n  [dim]{len(builds)} build{'s' if len(builds) != 1 else ''}[/dim]")
        for build in builds[:5]:
            build_id = build.get("id", "")
            created = format_datetime(build.get("createdAt"))
            console.print(f"    [dim]{build_id}  {created}[/dim]")
        if len(builds) > 5:
            console.print(
                f"    [dim]+ {len(builds) - 5} more[/dim]"
            )

    console.print()


async def delete_flash_app(app_name: str):
    with console.status("[dim]deleting...[/dim]"):
        success = await FlashApp.delete(app_name=app_name)

    if success:
        console.print(f"[green]✓[/green] deleted app [bold]{app_name}[/bold]")
    else:
        print_error(console, f"failed to delete app '{app_name}'")
        raise typer.Exit(1)


@apps_app.callback(invoke_without_command=True)
def apps(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.command.get_help(ctx))
        raise typer.Exit()
