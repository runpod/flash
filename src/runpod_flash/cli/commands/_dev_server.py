"""Programmatic FastAPI dev server for flash dev.

Builds the FastAPI app by scanning for @remote functions and registering
routes via add_api_route(). User modules are imported directly, so
tracebacks point to the original source files.
"""

import importlib
import os
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

from fastapi import FastAPI, Request

if TYPE_CHECKING:
    from .run import WorkerInfo


def create_app(
    project_root: Optional[Path] = None,
    workers: Optional[List["WorkerInfo"]] = None,
) -> FastAPI:
    """Factory function for the Flash dev server.

    When called by uvicorn via ``--factory``, both parameters are None and
    the function reads ``FLASH_PROJECT_ROOT`` from the environment and
    scans for workers itself. Tests can pass both directly.
    """
    if project_root is None:
        project_root = Path(os.environ.get("FLASH_PROJECT_ROOT", os.getcwd()))

    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    if workers is None:
        from .run import _scan_project_workers

        workers = _scan_project_workers(project_root)

    app = FastAPI(
        title="Flash Dev Server",
        description="Built by `flash dev`. Visit /docs for interactive testing.",
    )

    for worker in workers:
        _register_worker_routes(app, worker, project_root)

    @app.get("/", tags=["health"])
    def home():
        return {"message": "Flash Dev Server", "docs": "/docs"}

    @app.get("/ping", tags=["health"])
    def ping():
        return {"status": "healthy"}

    return app


def _import_from_module(module_path: str, name: str, project_root: Path):
    """Import *name* from *module_path*, handling numeric-prefix directories.

    When a dotted module path contains segments starting with a digit
    (e.g. ``01_hello.gpu_worker``), Python's ``from`` syntax cannot be
    used. This function uses ``importlib.import_module`` and temporarily
    scopes ``sys.path`` so that sibling imports within the target module
    resolve to the correct subdirectory.
    """
    has_numeric = any(seg and seg[0].isdigit() for seg in module_path.split("."))

    if has_numeric:
        parts = module_path.rsplit(".", 1)
        if len(parts) > 1:
            subdir = str(project_root / parts[0].replace(".", os.sep))
            sys.path.insert(0, subdir)
            try:
                mod = importlib.import_module(module_path)
            finally:
                try:
                    sys.path.remove(subdir)
                except ValueError:
                    pass
        else:
            mod = importlib.import_module(module_path)
    else:
        mod = importlib.import_module(module_path)

    return getattr(mod, name)


def _register_worker_routes(
    app: FastAPI, worker: "WorkerInfo", project_root: Path
) -> None:
    """Register FastAPI routes for a single discovered worker."""
    tag = f"{worker.url_prefix.lstrip('/')} [{worker.worker_type}]"

    if worker.worker_type == "QB":
        _register_qb_routes(app, worker, project_root, tag)
    elif worker.worker_type == "LB":
        _register_lb_routes(app, worker, project_root, tag)


def _register_qb_routes(
    app: FastAPI, worker: "WorkerInfo", project_root: Path, tag: str
) -> None:
    """Register queue-based (QB) routes.

    Single-function workers get one ``/runsync`` endpoint.
    Multi-function workers get ``/<fn_name>/runsync`` for each function.
    """
    if len(worker.functions) == 1:
        fn_name = worker.functions[0]
        fn = _import_from_module(worker.module_path, fn_name, project_root)
        path = f"{worker.url_prefix}/runsync"

        async def qb_handler(body: dict, _fn=fn):
            result = await _fn(body.get("input", body))
            return {
                "id": str(uuid.uuid4()),
                "status": "COMPLETED",
                "output": result,
            }

        qb_handler.__name__ = f"{worker.resource_name}_runsync"
        app.add_api_route(path, qb_handler, methods=["POST"], tags=[tag])
    else:
        for fn_name in worker.functions:
            fn = _import_from_module(worker.module_path, fn_name, project_root)
            path = f"{worker.url_prefix}/{fn_name}/runsync"

            async def qb_handler(body: dict, _fn=fn):
                result = await _fn(body.get("input", body))
                return {
                    "id": str(uuid.uuid4()),
                    "status": "COMPLETED",
                    "output": result,
                }

            qb_handler.__name__ = f"{worker.resource_name}_{fn_name}_runsync"
            app.add_api_route(path, qb_handler, methods=["POST"], tags=[tag])


def _register_lb_routes(
    app: FastAPI,
    worker: "WorkerInfo",
    project_root: Path,
    tag: str,
    executor: Optional[Callable] = None,
) -> None:
    """Register load-balanced (LB) routes.

    Each LB route is dispatched through *executor* (defaults to
    ``lb_execute`` from ``_run_server_helpers``). Tests can pass a
    substitute to avoid hitting real infrastructure.
    """
    if executor is None:
        from ._run_server_helpers import lb_execute

        executor = lb_execute

    # import config variables (deduplicated)
    config_vars: dict = {}
    for route in worker.lb_routes:
        var_name = route.get("config_variable")
        if var_name and var_name not in config_vars:
            config_vars[var_name] = _import_from_module(
                worker.module_path, var_name, project_root
            )

    for route in worker.lb_routes:
        method = route["method"]
        sub_path = route["path"].lstrip("/")
        fn_name = route["fn_name"]
        config_var_name = route["config_variable"]
        full_path = f"{worker.url_prefix}/{sub_path}"

        fn = _import_from_module(worker.module_path, fn_name, project_root)
        config = config_vars.get(config_var_name)

        has_body = method.upper() in ("POST", "PUT", "PATCH", "DELETE")
        if has_body:

            async def lb_body_handler(
                body: dict, _config=config, _fn=fn, _exec=executor
            ):
                return await _exec(_config, _fn, body)

            lb_body_handler.__name__ = f"_route_{worker.resource_name}_{fn_name}"
            app.add_api_route(
                full_path,
                lb_body_handler,
                methods=[method.upper()],
                tags=[tag],
            )
        else:

            async def lb_query_handler(
                request: Request, _config=config, _fn=fn, _exec=executor
            ):
                return await _exec(_config, _fn, dict(request.query_params))

            lb_query_handler.__name__ = f"_route_{worker.resource_name}_{fn_name}"
            app.add_api_route(
                full_path,
                lb_query_handler,
                methods=[method.upper()],
                tags=[tag],
            )
