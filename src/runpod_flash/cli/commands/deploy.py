"""Flash deploy command - build and deploy in one step."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

import typer
from rich.console import Console

from runpod_flash.cli.utils.formatting import print_error
from runpod_flash.core.exceptions import RunpodAPIKeyError
from runpod_flash.core.resources.app import FlashApp

from ..utils.app import discover_flash_project
from ..utils.deployment import deploy_from_uploaded_build, validate_local_manifest
from .build import run_build

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
        help="Comma-separated additional packages to exclude (torch packages are auto-excluded)",
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
      flash deploy --exclude transformers        # exclude additional packages from build
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
    except RunpodAPIKeyError as e:
        console.print()
        print_error(console, f"{e}")
        raise typer.Exit(1)
    except Exception as e:
        _handle_deploy_error(e)


def _handle_deploy_error(exc: Exception) -> None:
    """Handle deploy errors, providing targeted guidance for SSL issues."""
    from requests.exceptions import SSLError

    console.print()
    if isinstance(exc, SSLError):
        print_error(console, f"{exc}")
        raise typer.Exit(1)
    print_error(console, f"Deploy failed: {exc}")
    logger.exception("Deploy failed")
    raise typer.Exit(1)


def _print_curl_example(url: str, method: str = "POST") -> None:
    """Print a curl example for the given URL."""
    lines = [f"curl -X {method} {url}"]
    if method == "POST":
        lines.append(f'  -H "Content-Type: application/json"')
    lines.append(f'  -H "Authorization: Bearer $RUNPOD_API_KEY"')
    if method == "POST":
        lines.append(f"""  -d '{{"input": {{}}}}'""")
    console.print("[dim]" + " \\\n".join(lines) + "[/dim]")


def _display_post_deployment_guidance(
    env_name: str,
    resources_endpoints: dict[str, str],
    resources: dict[str, Any],
    routes: dict[str, dict[str, str]],
) -> None:
    """Display helpful next steps after successful deployment."""
    lb_entries: list[tuple[str, str, dict[str, str]]] = []
    qb_entries: list[tuple[str, str]] = []

    for resource_name, url in resources_endpoints.items():
        if resources.get(resource_name, {}).get("is_load_balanced", False):
            lb_routes = routes.get(resource_name, {})
            lb_entries.append((resource_name, url, lb_routes))
        else:
            qb_entries.append((resource_name, url))

    for name, url in qb_entries:
        console.print(f"\n{name}  [dim]QB[/dim]")
        console.print(f"{url}/runsync")

    for name, url, lb_routes in lb_entries:
        console.print(f"\n{name}  [dim]LB[/dim]")
        for route_key in sorted(lb_routes.keys()):
            method, path = route_key.split(" ", 1)
            console.print(f"{method:6s} {url}{path}")

    # one curl example
    if qb_entries:
        first_url = qb_entries[0][1]
        console.print()
        _print_curl_example(f"{first_url}/runsync")
    elif lb_entries:
        _name, curl_url, lb_routes = lb_entries[0]
        post_routes = [
            k.split(" ", 1)[1]
            for k in sorted(lb_routes.keys())
            if k.startswith("POST ")
        ]
        get_routes = [
            k.split(" ", 1)[1]
            for k in sorted(lb_routes.keys())
            if k.startswith("GET ")
        ]
        if post_routes:
            console.print()
            _print_curl_example(f"{curl_url}{post_routes[0]}")
        elif get_routes:
            console.print()
            _print_curl_example(f"{curl_url}{get_routes[0]}", method="GET")




def _launch_preview(project_dir):
    build_dir = project_dir / ".flash" / ".build"
    console.print("\nlaunching preview...")
    console.print("[dim]Starting all endpoints locally in Docker...[/dim]\n")

    try:
        from .preview import launch_preview

        manifest_path = project_dir / ".flash" / "flash_manifest.json"
        launch_preview(build_dir=build_dir, manifest_path=manifest_path)
    except KeyboardInterrupt:
        console.print("\n[yellow]Preview stopped by user[/yellow]")
    except Exception as e:
        print_error(console, f"Preview failed: {e}")
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

    console.print(f"\n[green]\u2713[/green] deployed to {resolved_env_name}")

    resources_endpoints = result.get("resources_endpoints", {})
    manifest = result.get("local_manifest", {})
    resources = manifest.get("resources", {})
    routes = manifest.get("routes", {})

    _display_post_deployment_guidance(
        resolved_env_name, resources_endpoints, resources, routes
    )


async def _resolve_environment(
    app_name: str, env_name: str | None
) -> tuple[FlashApp, str]:
    from runpod_flash.core.resources.app import FlashAppNotFoundError

    try:
        app = await FlashApp.from_name(app_name)
    except FlashAppNotFoundError:
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
    print_error(
        console,
        f"Multiple environments found: {', '.join(env_names)}\n"
        f"Please specify with [bold]--env <name>[/bold]",
    )
    raise typer.Exit(1)
