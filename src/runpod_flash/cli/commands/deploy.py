"""Flash deploy command - build and deploy in one step."""

import asyncio
import json
import logging
import shutil

import typer
from pathlib import Path
from rich.console import Console

from ..utils.app import discover_flash_project
from ..utils.deployment import deploy_from_uploaded_build, validate_local_manifest
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


def _display_post_deployment_guidance(
    env_name: str, lb_endpoint_url: str | None = None
) -> None:
    """Display helpful next steps after successful deployment."""
    manifest_path = Path.cwd() / ".flash" / "flash_manifest.json"
    lb_routes = {}

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
            resources_endpoints = manifest.get("resources_endpoints", {})
            resources = manifest.get("resources", {})
            routes = manifest.get("routes", {})

            for resource_name in resources_endpoints:
                if resources.get(resource_name, {}).get("is_load_balanced", False):
                    lb_routes = routes.get(resource_name, {})
                    break
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.debug(f"Could not read manifest: {e}")

    if lb_routes:
        console.print("\n[bold]Routes:[/bold]")
        for route_key in sorted(lb_routes.keys()):
            method, path = route_key.split(" ", 1)
            console.print(f"  {method:6s} {path}")

    # curl example using the first POST route
    if lb_endpoint_url and lb_routes:
        post_routes = [
            k.split(" ", 1)[1]
            for k in sorted(lb_routes.keys())
            if k.startswith("POST ")
        ]
        if post_routes:
            example_route = post_routes[0]
            curl_cmd = (
                f"curl -X POST {lb_endpoint_url}{example_route} \\\n"
                f'    -H "Content-Type: application/json" \\\n'
                '    -H "Authorization: Bearer $RUNPOD_API_KEY" \\\n'
                "    -d '{\"input\": {}}'"
            )
            console.print("\n[bold]Try it:[/bold]")
            console.print(f"  [dim]{curl_cmd}[/dim]")

    console.print("\n[bold]Useful commands:[/bold]")
    console.print(
        f"  [dim]flash env get {env_name}[/dim]       View environment status"
    )
    console.print(f"  [dim]flash deploy --env {env_name}[/dim]  Update deployment")
    console.print(f"  [dim]flash env delete {env_name}[/dim]    Remove deployment")


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
    app, resolved_env_name = await _resolve_environment(app_name, env_name)

    local_manifest = validate_local_manifest()

    with console.status("Uploading build..."):
        build = await app.upload_build(archive_path)

    with console.status("Deploying resources..."):
        result = await deploy_from_uploaded_build(
            app, build["id"], resolved_env_name, local_manifest
        )
    console.print(f"[green]Deployed[/green] to [bold]{resolved_env_name}[/bold]")

    resources_endpoints = result.get("resources_endpoints", {})
    local_manifest = result.get("local_manifest", {})
    resources = local_manifest.get("resources", {})

    # load balancer first, then workers
    lb_endpoint_url = None
    if resources_endpoints:
        console.print()
        other_items = []
        for resource_name, url in resources_endpoints.items():
            if resources.get(resource_name, {}).get("is_load_balanced", False):
                lb_endpoint_url = url
                console.print(f"  [bold]{url}[/bold]  [dim]({resource_name})[/dim]")
            else:
                other_items.append((resource_name, url))
        for resource_name, url in other_items:
            console.print(f"  [dim]{url}  ({resource_name})[/dim]")

    _display_post_deployment_guidance(
        resolved_env_name, lb_endpoint_url=lb_endpoint_url
    )


async def _resolve_environment(
    app_name: str, env_name: str | None
) -> tuple[FlashApp, str]:
    try:
        app = await FlashApp.from_name(app_name)
    except Exception as exc:
        if "app not found" not in str(exc).lower():
            raise
        target = env_name or "production"
        console.print(
            f"[dim]No app '{app_name}' found. Creating app and '{target}' environment...[/dim]"
        )
        app, _ = await FlashApp.create_environment_and_app(app_name, target)
        return app, target

    if env_name:
        envs = await app.list_environments()
        existing = {e.get("name") for e in envs}
        if env_name not in existing:
            console.print(
                f"[dim]Environment '{env_name}' not found. Creating it...[/dim]"
            )
            await app.create_environment(env_name)
        return app, env_name

    envs = await app.list_environments()

    if len(envs) == 1:
        return app, envs[0].get("name")

    if len(envs) == 0:
        console.print(
            "[dim]No environments found. Creating 'production' environment...[/dim]"
        )
        await app.create_environment("production")
        return app, "production"

    env_names = [e.get("name", "?") for e in envs]
    console.print(
        f"[red]Error:[/red] Multiple environments found: {', '.join(env_names)}\n"
        f"Please specify with [bold]--env <name>[/bold]"
    )
    raise typer.Exit(1)
