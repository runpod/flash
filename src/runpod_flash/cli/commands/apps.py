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

    # build rows
    rows = []
    for app_data in apps:
        name = app_data.get("name", "(unnamed)")
        environments = app_data.get("flashEnvironments") or []
        builds = app_data.get("flashBuilds") or []
        env_names = []
        for env in environments:
            state = env.get("state", "UNKNOWN")
            env_name = env.get("name", "?")
            env_names.append((env_name, state))
        rows.append((name, len(environments), len(builds), env_names))

    max_name = max(len(r[0]) for r in rows)
    max_envs = max(len(str(r[1])) for r in rows)
    max_builds = max(len(str(r[2])) for r in rows)

    console.print()
    console.print(
        f"  [dim]{'name':<{max_name}}  {'envs':>{max_envs + 1}}  {'builds':>{max_builds + 1}}[/dim]"
    )
    for name, env_count, build_count, env_names in rows:
        console.print(
            f"  [white]{name:<{max_name}}[/white]  "
            f"[dim]{env_count:>{max_envs + 1}}  {build_count:>{max_builds + 1}}[/dim]"
        )
        for env_name, state in env_names:
            console.print(
                f"    {state_dot(state)} {env_name}  [dim]{state.lower()}[/dim]"
            )
    console.print()


async def create_flash_app(app_name: str):
    with console.status("[dim]creating...[/dim]"):
        app = await FlashApp.create(app_name)
    console.print(f"[green]\u2713[/green] created app [bold]{app_name}[/bold]")


async def get_flash_app(app_name: str):
    with console.status("[dim]fetching...[/dim]"):
        app = await FlashApp.from_name(app_name)
        envs, builds = await asyncio.gather(app.list_environments(), app.list_builds())

    console.print(f"\n  [bold]{app.name}[/bold]\n")

    # environments table
    if envs:
        max_name = max(len(e.get("name", "") or "") for e in envs)
        console.print(
            f"  [dim]{'name':<{max_name}}  state         build[/dim]"
        )
        for env in envs:
            name = env.get("name", "(unnamed)")
            state = env.get("state", "UNKNOWN")
            build_id = env.get("activeBuildId") or "-"
            short_build = build_id[:12] if len(build_id) > 12 else build_id
            console.print(
                f"  {state_dot(state)} [white]{name:<{max_name}}[/white]  "
                f"[dim]{state.lower():<12}[/dim]  "
                f"[dim]{short_build}[/dim]"
            )
    else:
        console.print("  [dim]no environments. run [/dim][bold]flash deploy[/bold]")

    # builds table
    if builds:
        console.print(f"\n  [dim]builds ({len(builds)})[/dim]")
        for build in builds[:5]:
            build_id = build.get("id", "")
            short_id = build_id[:12] if len(build_id) > 12 else build_id
            created = format_datetime(build.get("createdAt"))
            console.print(f"  [dim]{short_id}  {created}[/dim]")
        if len(builds) > 5:
            console.print(f"  [dim]+ {len(builds) - 5} more[/dim]")

    console.print()


async def delete_flash_app(app_name: str):
    with console.status("[dim]deleting...[/dim]"):
        success = await FlashApp.delete(app_name=app_name)
    if success:
        console.print(f"[green]\u2713[/green] deleted app [bold]{app_name}[/bold]")
    else:
        print_error(console, f"failed to delete app '{app_name}'")
        raise typer.Exit(1)


@apps_app.callback(invoke_without_command=True)
def apps(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.command.get_help(ctx))
        raise typer.Exit()
