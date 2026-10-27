"""Flash deploy command - build and deploy in one step."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape

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
    python_version: str | None = typer.Option(
        None,
        "--python-version",
        help=(
            "Target Python version for worker images (3.10, 3.11, or 3.12). "
            "Overrides per-resource python_version declarations."
        ),
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
      flash deploy --python-version 3.11        # target Python 3.11 workers
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
            python_version=python_version,
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


def _required_params(
    file_path: str, func_name: str, class_name: str | None = None
) -> list[str] | None:
    """names of a function's parameters that have no default, read from source.

    looks only at top-level definitions (or methods of a top-level class),
    which is what the generated handler imports. returns None when the
    source can't be read or the definition isn't found.
    """
    try:
        tree = ast.parse(Path(file_path).read_text())
    except (OSError, SyntaxError, ValueError):
        return None

    body: list[ast.stmt] = tree.body
    if class_name is not None:
        classes = [
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name
        ]
        if not classes:
            return None
        body = classes[-1].body

    # the last definition wins at import time, as in python itself
    matches = [
        node
        for node in body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == func_name
    ]
    if not matches:
        return None

    func = matches[-1]
    args = func.args
    positional = args.posonlyargs + args.args
    required = positional[: len(positional) - len(args.defaults)]
    required += [
        a for a, default in zip(args.kwonlyargs, args.kw_defaults) if default is None
    ]
    # a method's receiver (whatever it's named) is bound by the handler, not
    # sent as input. static methods have no receiver.
    is_static = any(
        (isinstance(d, ast.Name) and d.id == "staticmethod")
        or (isinstance(d, ast.Attribute) and d.attr == "staticmethod")
        for d in func.decorator_list
    )
    if class_name is not None and not is_static and required:
        if required[0] is positional[0]:
            required = required[1:]
    return [a.arg for a in required]


def _qb_example_input(resource: dict[str, Any]) -> dict[str, Any]:
    """example runsync input for a queue-based endpoint.

    runpod drops a job whose input is an empty dict, so the job never
    reaches the worker and times out. the deployed handler strips the
    "__empty" marker, so use it when the call needs no arguments.
    """
    functions = resource.get("functions") or []
    if not functions:
        return {"__empty": True}
    func = functions[0]
    file_path = resource.get("file_path", "")

    if func.get("is_class"):
        methods = func.get("class_methods") or []
        if not methods:
            return {"method": "<method_name>"}
        method = methods[0]
        params = _required_params(file_path, method, class_name=func.get("name"))
        body: dict[str, Any] = {name: f"<{name}>" for name in params or []}
        # class handlers dispatch on "method" only when there's more than one
        if len(methods) > 1:
            body = {"method": method, **body}
        return body or {"__empty": True}

    params = _required_params(file_path, func.get("name", ""))
    if not params:
        return {"__empty": True}
    return {name: f"<{name}>" for name in params}


def _print_curl_example(
    url: str, method: str = "POST", body: dict[str, Any] | None = None
) -> None:
    """Print a curl example for the given URL."""
    lines = [f"curl -X {method} {url}"]
    if method == "POST":
        lines.append('  -H "Content-Type: application/json"')
    lines.append('  -H "Authorization: Bearer $RUNPOD_API_KEY"')
    if method == "POST":
        payload = json.dumps(body if body is not None else {"input": {}})
        lines.append(f"  -d '{payload}'")
    console.print("[dim]" + escape(" \\\n".join(lines)) + "[/dim]")


def _display_post_deployment_guidance(
    env_name: str,
    resources_endpoints: dict[str, str],
    resources: dict[str, Any],
    routes: dict[str, dict[str, str]],
) -> None:
    """Display endpoint list and curl example after deployment."""
    lb_entries: list[tuple[str, str, dict[str, str]]] = []
    qb_entries: list[tuple[str, str]] = []

    for resource_name, url in resources_endpoints.items():
        if resources.get(resource_name, {}).get("is_load_balanced", False):
            lb_routes = routes.get(resource_name, {})
            lb_entries.append((resource_name, url, lb_routes))
        else:
            qb_entries.append((resource_name, url))

    if not qb_entries and not lb_entries:
        return

    console.print()

    # collect rows for alignment: (name, url_display, routes_info)
    max_name = 0
    rows: list[tuple[str, str, list[tuple[str, str]]]] = []

    for name, url in qb_entries:
        max_name = max(max_name, len(name))
        rows.append((name, f"{url}/runsync", []))

    for name, url, lb_routes in lb_entries:
        max_name = max(max_name, len(name))
        route_list = []
        for k in sorted(lb_routes.keys()):
            m, p = k.split(" ", 1)
            route_list.append((m, p))
        rows.append((name, url, route_list))

    for name, url, route_list in rows:
        console.print(f"  [white]{name:<{max_name}}[/white]  [dim]{url}[/dim]")
        for method, path in route_list:
            console.print(f"  {' ' * max_name}  [dim]{method:6s}{path}[/dim]")

    # a RUNPOD_API_KEY the user set in env is theirs; Flash does not add it
    keyed = sorted(
        name
        for name, _url, _routes in rows
        if resources.get(name, {}).get("makes_remote_calls")
        and "RUNPOD_API_KEY" not in (resources[name].get("env") or {})
    )
    if keyed:
        console.print()
        console.print(
            "[dim]RUNPOD_API_KEY set by Flash on endpoints that call other endpoints: "
            f"{', '.join(keyed)}[/dim]"
        )

    # one curl example
    curl_url = None
    curl_method = "POST"
    curl_body = None
    if qb_entries:
        qb_name, qb_url = qb_entries[0]
        curl_url = f"{qb_url}/runsync"
        curl_body = {"input": _qb_example_input(resources.get(qb_name, {}))}
    elif lb_entries:
        _name, base_url, lb_routes = lb_entries[0]
        for k in sorted(lb_routes.keys()):
            m, p = k.split(" ", 1)
            if m == "POST":
                curl_url = f"{base_url}{p}"
                break
        if not curl_url:
            for k in sorted(lb_routes.keys()):
                m, p = k.split(" ", 1)
                curl_url = f"{base_url}{p}"
                curl_method = m
                break

    if curl_url:
        console.print()
        _print_curl_example(curl_url, method=curl_method, body=curl_body)


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
    import time as _time

    local_manifest = validate_local_manifest()

    # An empty resources map means the project declares no deployable
    # endpoints at all (no @remote functions, no client-mode
    # Endpoint(image=...) declarations -- the build registers those in the
    # manifest). Nothing is provisioned here, so don't claim a deployment.
    if not local_manifest.get("resources"):
        console.print(
            "[yellow]No deployable resources found; nothing was deployed[/yellow]"
        )
        return

    app, resolved_env_name = await _resolve_environment(app_name, env_name)

    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        TextColumn,
        TransferSpeedColumn,
    )

    archive_size = archive_path.stat().st_size
    t0 = _time.monotonic()

    with Progress(
        TextColumn("[dim]uploading[/dim]"),
        BarColumn(bar_width=30),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("upload", total=archive_size)

        def _on_progress(n: int):
            progress.advance(task, n)

        app._upload_progress_callback = _on_progress
        try:
            build = await app.upload_build(archive_path)
        finally:
            app._upload_progress_callback = None

    upload_s = _time.monotonic() - t0
    size_mb = archive_size / (1024 * 1024)
    console.print(
        f"[green]\u2713[/green] uploaded  [dim]{size_mb:.1f} MB  {upload_s:.1f}s[/dim]"
    )

    t0 = _time.monotonic()
    with console.status("[dim]deploying...[/dim]"):
        result = await deploy_from_uploaded_build(
            app, build["id"], resolved_env_name, local_manifest
        )
    deploy_s = _time.monotonic() - t0
    console.print(
        f"[green]\u2713[/green] deployed to [bold]{resolved_env_name}[/bold]  "
        f"[dim]{deploy_s:.1f}s[/dim]"
    )

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
