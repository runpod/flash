"""Flash deploy command - build and deploy in one step."""

import asyncio
import json
import logging
import shutil
import textwrap

import typer
from pathlib import Path
from rich.console import Console

from ..utils.app import discover_flash_project
from ..utils.deployment import deploy_to_environment
from .build import run_build

from runpod_flash.core.resources.app import FlashApp

logger = logging.getLogger(__name__)
console = Console()


def deploy_command(
    env_name: str | None = typer.Option(
        None, "--env", "-e", help="Target environment name"
    ),
    app_name: str | None = typer.Option(None, "--app", "-a", help="Flash app name"),
    no_deps: bool = typer.Option(
        False, "--no-deps", help="Skip transitive dependencies during pip install"
    ),
    exclude: str | None = typer.Option(
        None,
        "--exclude",
        help="Comma-separated packages to exclude (e.g., 'torch,torchvision')",
    ),
    use_local_flash: bool = typer.Option(
        False,
        "--use-local-flash",
        help="Bundle local runpod_flash source instead of PyPI version (for development/testing)",
    ),
    output_name: str | None = typer.Option(
        None, "--output", "-o", help="Custom archive name (default: artifact.tar.gz)"
    ),
    preview: bool = typer.Option(
        False,
        "--preview",
        help="Build and launch local preview environment instead of deploying",
    ),
):
    """
    Build and deploy Flash application.

    Builds the project and deploys to the target environment in one step.
    If only one environment exists, it is used automatically.

    Examples:
      flash deploy                              # build + deploy (auto-selects env)
      flash deploy --env staging                # build + deploy to staging
      flash deploy --app my-app --env prod      # deploy a different app
      flash deploy --preview                    # build + launch local preview
      flash deploy --exclude torch,torchvision  # exclude packages from build
    """
    try:
        project_dir, discovered_app_name = discover_flash_project()
        if not app_name:
            app_name = discovered_app_name

        archive_path = run_build(
            project_dir=project_dir,
            app_name=app_name,
            no_deps=no_deps,
            output_name=output_name,
            exclude=exclude,
            use_local_flash=use_local_flash,
        )

        if preview:
            _launch_preview(project_dir)
            return

        asyncio.run(_resolve_and_deploy(app_name, env_name, archive_path))

        build_dir = project_dir / ".flash" / ".build"
        if build_dir.exists():
            shutil.rmtree(build_dir)

    except KeyboardInterrupt:
        console.print("\n[yellow]Deploy cancelled by user[/yellow]")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red]Deploy failed:[/red] {e}")
        logger.exception("Deploy failed")
        raise typer.Exit(1)


def _display_post_deployment_guidance(env_name: str) -> None:
    """Display helpful next steps after successful deployment."""
    # Try to read manifest for endpoint information
    manifest_path = Path.cwd() / ".flash" / "flash_manifest.json"
    mothership_url = None
    mothership_routes = {}

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
            resources_endpoints = manifest.get("resources_endpoints", {})
            resources = manifest.get("resources", {})
            routes = manifest.get("routes", {})

            # Find mothership URL and routes
            for resource_name, url in resources_endpoints.items():
                if resources.get(resource_name, {}).get("is_mothership", False):
                    mothership_url = url
                    mothership_routes = routes.get(resource_name, {})
                    break
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.debug(f"Could not read manifest: {e}")

    console.print("\n[bold]Next Steps:[/bold]\n")

    # 1. Authentication
    console.print("[bold cyan]1. Authentication Required[/bold cyan]")
    console.print(
        "   All endpoints require authentication. Set your API key as an environment "
        "variable. Avoid typing secrets directly into shell commands, as they may be "
        "stored in your shell history."
    )
    console.print(
        "   [dim]# Recommended: store RUNPOD_API_KEY in a .env file or your shell profile[/dim]"
    )
    console.print(
        "   [dim]# Or securely prompt for it without echo (Bash example):[/dim]"
    )
    console.print("   [dim]read -s RUNPOD_API_KEY && export RUNPOD_API_KEY[/dim]\n")

    # 2. Calling functions
    console.print("[bold cyan]2. Call Your Functions[/bold cyan]")

    if mothership_url:
        console.print(
            f"   Your mothership is deployed at:\n   [link]{mothership_url}[/link]\n"
        )

    console.print("   [bold]Using HTTP/curl:[/bold]")
    if mothership_url:
        curl_example = textwrap.dedent(f"""
            curl -X POST {mothership_url}/YOUR_PATH \\
                -H "Authorization: Bearer $RUNPOD_API_KEY" \\
                -H "Content-Type: application/json" \\
                -d '{{"param1": "value1"}}'
        """).strip()
    else:
        curl_example = textwrap.dedent("""
            curl -X POST https://YOUR_ENDPOINT_URL/YOUR_PATH \\
                -H "Authorization: Bearer $RUNPOD_API_KEY" \\
                -H "Content-Type: application/json" \\
                -d '{"param1": "value1"}'
        """).strip()
    console.print(f"   [dim]{curl_example}[/dim]\n")

    # 3. Available routes
    console.print("[bold cyan]3. Available Routes[/bold cyan]")
    if mothership_routes:
        for route_key in sorted(mothership_routes.keys()):
            # route_key format: "POST /api/hello"
            method, path = route_key.split(" ", 1)
            console.print(f"   [cyan]{method:6s}[/cyan] {path}")
        console.print()
    else:
        # Routes not found - could mean manifest missing, no LB endpoints, or no routes defined
        if mothership_url:
            console.print(
                "   [dim]No routes found in manifest. Check @remote decorators in your code.[/dim]\n"
            )
        else:
            console.print(
                "   Check your code for @remote decorators to find available endpoints:"
            )
            console.print(
                '   [dim]@remote(mothership, method="POST", path="/api/process")[/dim]\n'
            )

    # 4. Monitor & Debug
    console.print("[bold cyan]4. Monitor & Debug[/bold cyan]")
    console.print(f"   [dim]flash env get {env_name}[/dim]  - View environment status")
    console.print(
        "   [dim]Runpod Console[/dim]  - View logs and metrics at https://console.runpod.io/serverless\n"
    )

    # 5. Update & Teardown
    console.print("[bold cyan]5. Update or Remove Deployment[/bold cyan]")
    console.print(f"   [dim]flash deploy --env {env_name}[/dim]  - Update deployment")
    console.print(f"   [dim]flash env delete {env_name}[/dim]  - Remove deployment\n")


def _launch_preview(project_dir):
    build_dir = project_dir / ".flash" / ".build"
    console.print("\n[bold cyan]Launching multi-container preview...[/bold cyan]")
    console.print("[dim]Starting all endpoints locally in Docker...[/dim]\n")

    try:
        from .preview import launch_preview

        manifest_path = project_dir / ".flash" / "flash_manifest.json"
        launch_preview(build_dir=build_dir, manifest_path=manifest_path)
    except KeyboardInterrupt:
        console.print("\n[yellow]Preview stopped by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Preview error:[/red] {e}")
        logger.exception("Preview launch failed")
        raise typer.Exit(1)


async def _resolve_and_deploy(
    app_name: str, env_name: str | None, archive_path
) -> None:
    resolved_env_name = await _resolve_environment(app_name, env_name)

    console.print(f"\nDeploying to '[bold]{resolved_env_name}[/bold]'...")

    await deploy_to_environment(app_name, resolved_env_name, archive_path)

    # Display next steps guidance
    _display_post_deployment_guidance(resolved_env_name)


async def _resolve_environment(app_name: str, env_name: str | None) -> str:
    try:
        app = await FlashApp.from_name(app_name)
    except Exception as exc:
        if "app not found" not in str(exc).lower():
            raise
        target = env_name or "production"
        console.print(
            f"[dim]No app '{app_name}' found. Creating app and '{target}' environment...[/dim]"
        )
        await FlashApp.create_environment_and_app(app_name, target)
        return target

    if env_name:
        envs = await app.list_environments()
        existing = {e.get("name") for e in envs}
        if env_name not in existing:
            console.print(
                f"[dim]Environment '{env_name}' not found. Creating it...[/dim]"
            )
            await app.create_environment(env_name)
        return env_name

    envs = await app.list_environments()

    if len(envs) == 1:
        resolved = envs[0].get("name")
        console.print(f"[dim]Auto-selected environment: {resolved}[/dim]")
        return resolved

    if len(envs) == 0:
        console.print(
            "[dim]No environments found. Creating 'production' environment...[/dim]"
        )
        await app.create_environment("production")
        return "production"

    env_names = [e.get("name", "?") for e in envs]
    console.print(
        f"[red]Error:[/red] Multiple environments found: {', '.join(env_names)}\n"
        f"Please specify with [bold]--env <name>[/bold]"
    )
    raise typer.Exit(1)
