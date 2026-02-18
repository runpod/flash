"""Run Flash development server."""

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

# Resource state file written by ResourceManager in the uvicorn subprocess.
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

    # Group by file path
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


def _ensure_gitignore(project_root: Path) -> None:
    """Add .flash/ to .gitignore if not already present."""
    gitignore = project_root / ".gitignore"
    entry = ".flash/"

    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if entry in content:
            return
        # Append with a newline
        if not content.endswith("\n"):
            content += "\n"
        gitignore.write_text(content + entry + "\n", encoding="utf-8")
    else:
        gitignore.write_text(entry + "\n", encoding="utf-8")


def _sanitize_fn_name(name: str) -> str:
    """Sanitize a string for use as a Python function name."""
    return name.replace("/", "_").replace(".", "_").replace("-", "_")


def _generate_flash_server(project_root: Path, workers: List[WorkerInfo]) -> Path:
    """Generate .flash/server.py from the discovered workers.

    Args:
        project_root: Root of the Flash project
        workers: List of discovered worker infos

    Returns:
        Path to the generated server.py
    """
    flash_dir = project_root / ".flash"
    flash_dir.mkdir(exist_ok=True)

    _ensure_gitignore(project_root)

    lines = [
        '"""Auto-generated Flash dev server. Do not edit — regenerated on each flash run."""',
        "import sys",
        "import uuid",
        "from pathlib import Path",
        "sys.path.insert(0, str(Path(__file__).parent.parent))",
        "",
        "from fastapi import FastAPI",
        "",
    ]

    # Collect all imports
    all_imports: List[str] = []
    for worker in workers:
        for fn_name in worker.functions:
            all_imports.append(f"from {worker.module_path} import {fn_name}")

    if all_imports:
        lines.extend(all_imports)
        lines.append("")

    lines += [
        "app = FastAPI(",
        '    title="Flash Dev Server",',
        '    description="Auto-generated by `flash run`. Visit /docs for interactive testing.",',
        ")",
        "",
    ]

    for worker in workers:
        tag = f"{worker.url_prefix.lstrip('/')} [{worker.worker_type}]"
        lines.append(f"# {'─' * 60}")
        lines.append(f"# {worker.worker_type}: {worker.file_path.name}")
        lines.append(f"# {'─' * 60}")

        if worker.worker_type == "QB":
            if len(worker.functions) == 1:
                fn = worker.functions[0]
                handler_name = _sanitize_fn_name(f"{worker.resource_name}_run")
                run_path = f"{worker.url_prefix}/run"
                sync_path = f"{worker.url_prefix}/run_sync"
                lines += [
                    f'@app.post("{run_path}", tags=["{tag}"])',
                    f'@app.post("{sync_path}", tags=["{tag}"])',
                    f"async def {handler_name}(body: dict):",
                    f'    result = await {fn}(body.get("input", body))',
                    '    return {"id": str(uuid.uuid4()), "status": "COMPLETED", "output": result}',
                    "",
                ]
            else:
                for fn in worker.functions:
                    handler_name = _sanitize_fn_name(f"{worker.resource_name}_{fn}_run")
                    run_path = f"{worker.url_prefix}/{fn}/run"
                    sync_path = f"{worker.url_prefix}/{fn}/run_sync"
                    lines += [
                        f'@app.post("{run_path}", tags=["{tag}"])',
                        f'@app.post("{sync_path}", tags=["{tag}"])',
                        f"async def {handler_name}(body: dict):",
                        f'    result = await {fn}(body.get("input", body))',
                        '    return {"id": str(uuid.uuid4()), "status": "COMPLETED", "output": result}',
                        "",
                    ]

        elif worker.worker_type == "LB":
            for route in worker.lb_routes:
                method = route["method"].lower()
                sub_path = route["path"].lstrip("/")
                fn_name = route["fn_name"]
                full_path = f"{worker.url_prefix}/{sub_path}"
                handler_name = _sanitize_fn_name(
                    f"_route_{worker.resource_name}_{fn_name}"
                )
                lines += [
                    f'@app.{method}("{full_path}", tags=["{tag}"])',
                    f"async def {handler_name}(body: dict):",
                    f"    return await {fn_name}(body)",
                    "",
                ]

    # Health endpoints
    lines += [
        "# Health",
        '@app.get("/", tags=["health"])',
        "def home():",
        '    return {"message": "Flash Dev Server", "docs": "/docs"}',
        "",
        '@app.get("/ping", tags=["health"])',
        "def ping():",
        '    return {"status": "healthy"}',
        "",
    ]

    server_path = flash_dir / "server.py"
    server_path.write_text("\n".join(lines), encoding="utf-8")
    return server_path


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
                    f"POST  {worker.url_prefix}/run",
                    worker.resource_name,
                    "QB",
                )
                table.add_row(
                    f"POST  {worker.url_prefix}/run_sync",
                    worker.resource_name,
                    "QB",
                )
            else:
                for fn in worker.functions:
                    table.add_row(
                        f"POST  {worker.url_prefix}/{fn}/run",
                        worker.resource_name,
                        "QB",
                    )
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
    console.print(f"\n  Visit [bold]http://{host}:{port}/docs[/bold] for Swagger UI\n")


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

        async def _do_cleanup():
            for key, resource in live_items.items():
                name = getattr(resource, "name", key)
                try:
                    success = await resource._do_undeploy()
                    if success:
                        console.print(f"  Deprovisioned: {name}")
                    else:
                        logger.warning(f"Failed to deprovision: {name}")
                except Exception as e:
                    logger.warning(f"Error deprovisioning {name}: {e}")

        asyncio.run(_do_cleanup())

        # Remove live- entries from persisted state so they don't linger.
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
):
    """Run Flash development server.

    Scans the project for @remote decorated functions, generates a dev server
    at .flash/server.py, and starts uvicorn with hot-reload.

    No main.py or FastAPI boilerplate required. Any .py file with @remote
    decorated functions is a valid Flash project.
    """
    project_root = Path.cwd()

    # Set flag for live provisioning so stubs get the live- prefix
    if not _is_reload():
        os.environ["FLASH_IS_LIVE_PROVISIONING"] = "true"

    # Discover @remote functions
    workers = _scan_project_workers(project_root)

    if not workers:
        console.print("[red]Error:[/red] No @remote functions found.")
        console.print("Add @remote decorators to your functions to get started.")
        console.print("\nExample:")
        console.print(
            "  from runpod_flash import LiveServerless, remote\n"
            "  gpu_config = LiveServerless(name='my_worker')\n"
            "\n"
            "  @remote(gpu_config)\n"
            "  async def process(input_data: dict) -> dict:\n"
            "      return {'result': input_data}"
        )
        raise typer.Exit(1)

    # Generate .flash/server.py
    _generate_flash_server(project_root, workers)

    _print_startup_table(workers, host, port)

    # Build uvicorn command using --app-dir so server:app is importable
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "server:app",
        "--app-dir",
        ".flash",
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
            ".",
            "--reload-include",
            "*.py",
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
