"""Flash dev server command."""

import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.table import Table

from .build_utils.scanner import (
    RemoteDecoratorScanner,
    file_to_module_path,
    file_to_resource_name,
    file_to_url_prefix,
)

logger = logging.getLogger(__name__)
console = Console()

# resource state file written by ResourceManager in the uvicorn subprocess
_RESOURCE_STATE_FILE = Path(".runpod") / "resources.pkl"


@dataclass
class WorkerInfo:
    """Info about a discovered @remote function for dev server generation."""

    file_path: Path
    url_prefix: str  # e.g. /longruns/stage1
    module_path: str  # e.g. longruns.stage1
    resource_name: str  # e.g. longruns_stage1
    worker_type: str  # "QB" or "LB"
    functions: List[str]  # function names
    lb_routes: List[dict] = field(default_factory=list)  # [{method, path, fn_name}]


def _scan_project_workers(project_root: Path) -> List[WorkerInfo]:
    """Scan the project for all @remote decorated functions.

    Walks all .py files (excluding .flash/, __pycache__, __init__.py) and
    builds WorkerInfo for each file that contains @remote functions.

    Files with QB functions produce one WorkerInfo per file (QB type).
    Files with LB functions produce one WorkerInfo per file (LB type).
    A file can have both QB and LB functions (unusual but supported).

    Args:
        project_root: Root directory of the Flash project

    Returns:
        List of WorkerInfo, one entry per discovered source file
    """
    scanner = RemoteDecoratorScanner(project_root)
    remote_functions = scanner.discover_remote_functions()

    # group by file path
    by_file: dict[Path, List] = {}
    for func in remote_functions:
        by_file.setdefault(func.file_path, []).append(func)

    workers: List[WorkerInfo] = []
    for file_path, funcs in sorted(by_file.items()):
        url_prefix = file_to_url_prefix(file_path, project_root)
        module_path = file_to_module_path(file_path, project_root)
        resource_name = file_to_resource_name(file_path, project_root)

        qb_funcs = [f for f in funcs if not f.is_load_balanced]
        lb_funcs = [f for f in funcs if f.is_load_balanced and f.is_lb_route_handler]

        if qb_funcs:
            workers.append(
                WorkerInfo(
                    file_path=file_path,
                    url_prefix=url_prefix,
                    module_path=module_path,
                    resource_name=resource_name,
                    worker_type="QB",
                    functions=[f.function_name for f in qb_funcs],
                )
            )

        if lb_funcs:
            lb_routes = [
                {
                    "method": f.http_method,
                    "path": f.http_path,
                    "fn_name": f.function_name,
                    "config_variable": f.config_variable,
                }
                for f in lb_funcs
            ]
            workers.append(
                WorkerInfo(
                    file_path=file_path,
                    url_prefix=url_prefix,
                    module_path=module_path,
                    resource_name=resource_name,
                    worker_type="LB",
                    functions=[f.function_name for f in lb_funcs],
                    lb_routes=lb_routes,
                )
            )

    return workers


def _print_startup_table(workers: List[WorkerInfo], host: str, port: int) -> None:
    """Print the startup table showing local paths, resource names, and types."""
    console.print(f"\n[bold green]Flash Dev Server[/bold green]  http://{host}:{port}")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Local path", style="cyan")
    table.add_column("Resource", style="white")
    table.add_column("Type", style="yellow")

    for worker in workers:
        if worker.worker_type == "QB":
            if len(worker.functions) == 1:
                table.add_row(
                    f"POST  {worker.url_prefix}/run_sync",
                    worker.resource_name,
                    "QB",
                )
            else:
                for fn in worker.functions:
                    table.add_row(
                        f"POST  {worker.url_prefix}/{fn}/run_sync",
                        worker.resource_name,
                        "QB",
                    )
        elif worker.worker_type == "LB":
            for route in worker.lb_routes:
                sub_path = route["path"].lstrip("/")
                full_path = f"{worker.url_prefix}/{sub_path}"
                table.add_row(
                    f"{route['method']}  {full_path}",
                    worker.resource_name,
                    "LB",
                )

    console.print(table)
    console.print(f"\n  Visit [bold]http://{host}:{port}/docs[/bold] for Swagger UI")
    console.print(
        "  Press [bold]Ctrl+C[/bold] to stop — provisioned endpoints are cleaned up automatically\n"
    )


def _cleanup_live_endpoints() -> None:
    """Deprovision all Live Serverless endpoints created during this session.

    Reads the resource state file written by the uvicorn subprocess, finds
    all endpoints with the 'live-' name prefix, and deprovisions them.
    Best-effort: errors per endpoint are logged but do not prevent cleanup
    of other endpoints.
    """
    if not _RESOURCE_STATE_FILE.exists():
        return

    try:
        import asyncio
        import cloudpickle
        from ...core.utils.file_lock import file_lock

        with open(_RESOURCE_STATE_FILE, "rb") as f:
            with file_lock(f, exclusive=False):
                data = cloudpickle.load(f)

        if isinstance(data, tuple):
            resources, configs = data
        else:
            resources, configs = data, {}

        live_items = {
            key: resource
            for key, resource in resources.items()
            if hasattr(resource, "name")
            and resource.name
            and resource.name.startswith("live-")
        }

        if not live_items:
            return

        import time

        async def _do_cleanup():
            undeployed = 0
            for key, resource in live_items.items():
                name = getattr(resource, "name", key)
                try:
                    success = await resource._do_undeploy()
                    if success:
                        console.print(f"  Deprovisioned: {name}")
                        undeployed += 1
                    else:
                        logger.warning(f"Failed to deprovision: {name}")
                except Exception as e:
                    logger.warning(f"Error deprovisioning {name}: {e}")
            return undeployed

        t0 = time.monotonic()
        undeployed = asyncio.run(_do_cleanup())
        elapsed = time.monotonic() - t0
        console.print(
            f"  Cleanup completed: {undeployed}/{len(live_items)} "
            f"resource(s) undeployed in {elapsed:.1f}s"
        )

        # remove live- entries from persisted state so they don't linger
        remaining = {k: v for k, v in resources.items() if k not in live_items}
        remaining_configs = {k: v for k, v in configs.items() if k not in live_items}
        try:
            with open(_RESOURCE_STATE_FILE, "wb") as f:
                with file_lock(f, exclusive=True):
                    cloudpickle.dump((remaining, remaining_configs), f)
        except Exception as e:
            logger.warning(f"Could not update resource state after cleanup: {e}")

    except Exception as e:
        logger.warning(f"Live endpoint cleanup failed: {e}")


def _is_reload() -> bool:
    """Check if running in uvicorn reload subprocess."""
    return "UVICORN_RELOADER_PID" in os.environ


def _discover_resources(project_root: Path):
    """Discover deployable resources in project files.

    Uses ResourceDiscovery to find all DeployableResource instances by
    parsing @remote decorators and importing the referenced config variables.

    Args:
        project_root: Root directory of the Flash project

    Returns:
        List of discovered DeployableResource instances
    """
    from ...core.discovery import ResourceDiscovery

    py_files = sorted(
        p
        for p in project_root.rglob("*.py")
        if not any(
            skip in p.parts
            for skip in (".flash", ".venv", "venv", "__pycache__", ".git")
        )
    )

    # add project root to sys.path so cross-module imports resolve
    root_str = str(project_root)
    added_to_path = root_str not in sys.path
    if added_to_path:
        sys.path.insert(0, root_str)

    resources = []
    try:
        for py_file in py_files:
            try:
                discovery = ResourceDiscovery(str(py_file), max_depth=0)
                resources.extend(discovery.discover())
            except Exception as e:
                logger.debug("Discovery failed for %s: %s", py_file, e)
    finally:
        if added_to_path:
            sys.path.remove(root_str)

    if resources:
        console.print(f"\n[dim]Discovered {len(resources)} resource(s):[/dim]")
        for res in resources:
            res_name = getattr(res, "name", "Unknown")
            res_type = res.__class__.__name__
            console.print(f"  [dim]- {res_name} ({res_type})[/dim]")
        console.print()

    return resources


def _provision_resources(resources) -> None:
    """Provision resources in parallel and wait for completion.

    Args:
        resources: List of DeployableResource instances to provision
    """
    import asyncio

    from ...core.deployment import DeploymentOrchestrator

    try:
        console.print(f"[bold]Provisioning {len(resources)} resource(s)...[/bold]")
        orchestrator = DeploymentOrchestrator(max_concurrent=3)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(orchestrator.deploy_all(resources, show_progress=True))
        loop.close()
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Provisioning failed: {e}")
        console.print(
            "[dim]Resources will be provisioned on-demand at first request.[/dim]"
        )


def run_command(
    host: str = typer.Option(
        "localhost",
        "--host",
        envvar="FLASH_HOST",
        help="Host to bind to (env: FLASH_HOST)",
    ),
    port: int = typer.Option(
        8888,
        "--port",
        "-p",
        envvar="FLASH_PORT",
        help="Port to bind to (env: FLASH_PORT)",
    ),
    reload: bool = typer.Option(
        True, "--reload/--no-reload", help="Enable auto-reload"
    ),
    auto_provision: bool = typer.Option(
        False,
        "--auto-provision",
        help="Auto-provision all endpoints on startup (eliminates cold-start on first request)",
    ),
):
    """Start Flash development server.

    Scans the project for @remote decorated functions and starts a FastAPI
    dev server via uvicorn. The app is built programmatically (no codegen)
    so tracebacks point directly to your source files.

    No main.py or FastAPI boilerplate required. Any .py file with @remote
    decorated functions is a valid Flash project.
    """
    project_root = Path.cwd()

    # set flag for live provisioning so stubs get the live- prefix
    if not _is_reload():
        os.environ["FLASH_IS_LIVE_PROVISIONING"] = "true"

    # auto-provision all endpoints upfront (eliminates cold-start)
    if auto_provision and not _is_reload():
        try:
            resources = _discover_resources(project_root)
            if resources:
                _provision_resources(resources)
        except Exception as e:
            logger.error("Auto-provisioning failed", exc_info=True)
            console.print(f"[yellow]Warning:[/yellow] Auto-provisioning failed: {e}")
            console.print(
                "[dim]Resources will be provisioned on-demand at first request.[/dim]"
            )

    # discover @remote functions for the startup table
    workers = _scan_project_workers(project_root)

    if not workers:
        console.print("[red]Error:[/red] No @remote functions found.")
        console.print("Add @remote decorators to your functions to get started.")
        console.print(
            "\nExample:\n"
            "  from runpod_flash import LiveServerless, remote\n"
            "  gpu_config = LiveServerless(name='my_worker')\n"
            "\n"
            "  @remote(gpu_config)\n"
            "  async def process(input_data: dict) -> dict:\n"
            "      return {'result': input_data}"
        )
        raise typer.Exit(1)

    _print_startup_table(workers, host, port)

    # tell the factory function where the project lives
    os.environ["FLASH_PROJECT_ROOT"] = str(project_root)

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "--factory",
        "runpod_flash.cli.commands._dev_server:create_app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]

    if reload:
        cmd += [
            "--reload",
            "--reload-dir",
            str(project_root),
        ]

    process = None
    try:
        if sys.platform == "win32":
            process = subprocess.Popen(
                cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            process = subprocess.Popen(cmd, preexec_fn=os.setsid)

        process.wait()

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping server and cleaning up...[/yellow]")

        if process:
            try:
                if sys.platform == "win32":
                    process.terminate()
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)

                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    if sys.platform == "win32":
                        process.kill()
                    else:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait()

            except (ProcessLookupError, OSError):
                pass

        _cleanup_live_endpoints()
        console.print("[green]Server stopped[/green]")
        raise typer.Exit(0)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")

        if process:
            try:
                if sys.platform == "win32":
                    process.terminate()
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        _cleanup_live_endpoints()
        raise typer.Exit(1)
