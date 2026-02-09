"""Deployment environment management commands."""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import asyncio

from runpod_flash.cli.utils.app import discover_flash_project


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
    app_name: str = typer.Option(..., "--app", "-a", help="Flash app name to delete"),
):
    if not app_name:
        _, app_name = discover_flash_project()
    return asyncio.run(delete_flash_app(app_name))


async def list_flash_apps():
    apps = await FlashApp.list()
    if not apps:
        console.print("No Flash apps found.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("ID", overflow="fold")
    table.add_column("Environments", overflow="fold")
    table.add_column("Builds", overflow="fold")

    for app in apps:
        environments = app.get("flashEnvironments") or []
        env_summary = ", ".join(env.get("name", "?") for env in environments) or "—"
        builds = app.get("flashBuilds") or []
        build_summary = ", ".join(build.get("id", "?") for build in builds) or "—"
        table.add_row(
            app.get("name", "(unnamed)"), app.get("id", "—"), env_summary, build_summary
        )

    console.print(table)


async def create_flash_app(app_name: str):
    with console.status(f"Creating flash app: {app_name}"):
        app = await FlashApp.create(app_name)

    panel_content = (
        f"Flash app '[bold]{app_name}[/bold]' created successfully\n\nApp ID: {app.id}"
    )
    console.print(Panel(panel_content, title="✅ App Created", expand=False))


async def get_flash_app(app_name: str):
    with console.status(f"Fetching flash app: {app_name}"):
        app = await FlashApp.from_name(app_name)
        # Fetch environments and builds in parallel for better performance
        envs, builds = await asyncio.gather(app.list_environments(), app.list_builds())

    main_info = f"Name: {app.name}\n"
    main_info += f"ID: {app.id}\n"
    main_info += f"Environments: {len(envs)}\n"
    main_info += f"Builds: {len(builds)}"

    console.print(Panel(main_info, title=f"📱 Flash App: {app_name}", expand=False))

    if envs:
        env_table = Table(title="Environments")
        env_table.add_column("Name", style="cyan")
        env_table.add_column("ID", overflow="fold")
        env_table.add_column("State", style="yellow")
        env_table.add_column("Active Build", overflow="fold")
        env_table.add_column("Created", style="dim")

        for env in envs:
            env_table.add_row(
                env.get("name"),
                env.get("id", "-"),
                env.get("state", "UNKNOWN"),
                env.get("activeBuildId", "-"),
                env.get("createdAt", "-"),
            )
        console.print(env_table)

    if builds:
        build_table = Table(title="Builds")
        build_table.add_column("ID", overflow="fold")
        build_table.add_column("Object Key", overflow="fold")
        build_table.add_column("Created", style="dim")

        for build in builds:
            build_table.add_row(
                build.get("id"),
                build.get("objectKey", "-"),
                build.get("createdAt", "-"),
            )
        console.print(build_table)


async def delete_flash_app(app_name: str):
    with console.status(f"Deleting flash app: {app_name}"):
        success = await FlashApp.delete(app_name=app_name)

    if success:
        console.print(f"✅ Flash app '{app_name}' deleted successfully")
    else:
        console.print(f"❌ Failed to delete flash app '{app_name}'")
        raise typer.Exit(1)


@apps_app.callback(invoke_without_command=True)
def apps(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.command.get_help(ctx))
        raise typer.Exit()
