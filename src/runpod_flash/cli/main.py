"""Main CLI entry point for Flash CLI."""

import typer
from importlib import metadata
from rich.console import Console
from rich.panel import Panel

from .commands import (
    init,
    run,
    build,
    deploy,
    env,
    apps,
    undeploy,
)


def get_version() -> str:
    """Get the package version from metadata."""
    try:
        return metadata.version("runpod-flash")
    except metadata.PackageNotFoundError:
        return "unknown"


console = Console()

# command: flash
app = typer.Typer(
    name="flash",
    help="Runpod Flash CLI - Distributed inference and serving framework",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# command: flash <command>
app.command("init")(init.init_command)
app.command("run")(run.run_command)
app.command("build")(build.build_command)
app.command("deploy")(deploy.deploy_command)
# app.command("report")(resource.report_command)


# command: flash env <subcommand>
env_app = typer.Typer(
    name="env",
    help="Environment management commands",
    no_args_is_help=True,
)

env_app.command("list")(env.list_command)
env_app.command("create")(env.create_command)
env_app.command("get")(env.get_command)
env_app.command("delete")(env.delete_command)

app.add_typer(env_app, name="env")
app.add_typer(apps.apps_app)


# command: flash undeploy
# Note: Using a simple command instead of sub-app to allow both "undeploy list" and "undeploy <name>"
# The undeploy_command internally handles the "list" case
app.command("undeploy")(undeploy.undeploy_command)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
):
    """Runpod Flash CLI - Distributed inference and serving framework."""
    if version:
        console.print(f"Runpod Flash CLI v{get_version()}")
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        console.print(
            Panel(
                "[bold blue]Runpod Flash CLI[/bold blue]\n\n"
                "A framework for distributed inference and serving of ML models.\n\n"
                "Use [bold]flash --help[/bold] to see available commands.",
                title="Welcome",
                expand=False,
            )
        )


if __name__ == "__main__":
    app()
