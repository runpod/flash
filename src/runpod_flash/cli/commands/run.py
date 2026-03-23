"""Run Flash development server."""

import asyncio
import importlib.util
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.table import Table

try:
    from watchfiles import DefaultFilter as _WatchfilesDefaultFilter
    from watchfiles import watch as _watchfiles_watch
except ModuleNotFoundError:

    def _watchfiles_watch(*_a, **_kw):  # type: ignore[misc]
        raise ModuleNotFoundError(
            "watchfiles is required for flash run --reload. "
            "Install it with: pip install watchfiles"
        )

    class _WatchfilesDefaultFilter:  # type: ignore[no-redef]
        def __init__(self, **_kw):
            pass


from ..utils.ignore import get_file_tree, load_ignore_patterns
from .build_utils.scanner import (
    RuntimeScanner,
    file_to_module_path,
    file_to_resource_name,
    file_to_url_prefix,
)
from runpod_flash.core.api.pod_client import PodApiClient
from runpod_flash.core.credentials import get_api_key
from runpod_flash.core.pod_scanner import PodScanner
from runpod_flash.core.resources.pod import Pod, PodState
from runpod_flash.core.resources.pod_lifecycle import PodLifecycleManager, PodTracker
from runpod_flash.runtime.pod_registry import PodRegistry

logger = logging.getLogger(__name__)
console = Console()

# Resource state file written by ResourceManager in the uvicorn subprocess.
_RESOURCE_STATE_FILE = Path(".runpod") / "resources.pkl"

_MAX_PORT_ATTEMPTS = 20


def _find_available_port(host: str, start_port: int) -> int:
    """Find the first available port starting from start_port.

    Tries up to _MAX_PORT_ATTEMPTS consecutive ports. Raises typer.Exit
    if no port is available.
    """
    for offset in range(_MAX_PORT_ATTEMPTS):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return port
        except OSError:
            continue

    console.print(
        f"[red]Error:[/red] No available port found in range "
        f"{start_port}-{start_port + _MAX_PORT_ATTEMPTS - 1}."
    )
    raise typer.Exit(1)


@dataclass
class WorkerInfo:
    """Info about a discovered @remote function for dev server generation."""

    file_path: Path
    url_prefix: str  # e.g. /longruns/stage1
    module_path: str  # e.g. longruns.stage1
    resource_name: str  # e.g. longruns_stage1
    worker_type: str  # "QB" or "LB"
    functions: List[str]  # function names
    class_remotes: List[dict] = field(
        default_factory=list
    )  # [{name, methods, method_params}]
    lb_routes: List[dict] = field(default_factory=list)  # [{method, path, fn_name}]
    function_params: dict[str, list[str]] = field(
        default_factory=dict
    )  # fn_name -> param_names
    function_docstrings: dict[str, str] = field(
        default_factory=dict
    )  # fn_or_method_name -> first line of docstring


def _scan_project_workers(
    project_root: Path,
) -> tuple[List[WorkerInfo], RuntimeScanner]:
    """scan the project for all @remote decorated functions.

    returns (workers, scanner) so callers can inspect import_errors.
    """
    scanner = RuntimeScanner(project_root)
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

        qb_funcs = [f for f in funcs if not f.is_load_balanced and not f.is_class]
        qb_classes = [f for f in funcs if not f.is_load_balanced and f.is_class]
        lb_funcs = [f for f in funcs if f.is_load_balanced and f.is_lb_route_handler]

        if qb_funcs or qb_classes:
            docstrings: dict[str, str] = {}
            for f in qb_funcs:
                if f.docstring:
                    docstrings[f.function_name] = f.docstring
            for c in qb_classes:
                # Class-level docstring as fallback for methods without their own
                for method in c.class_methods:
                    method_doc = c.class_method_docstrings.get(method)
                    if method_doc:
                        docstrings[method] = method_doc
                    elif c.docstring:
                        docstrings[method] = c.docstring
            workers.append(
                WorkerInfo(
                    file_path=file_path,
                    url_prefix=url_prefix,
                    module_path=module_path,
                    resource_name=resource_name,
                    worker_type="QB",
                    functions=[f.function_name for f in qb_funcs],
                    class_remotes=[
                        {
                            "name": c.function_name,
                            "methods": c.class_methods,
                            "method_params": c.class_method_params,
                        }
                        for c in qb_classes
                    ],
                    function_params={f.function_name: f.param_names for f in qb_funcs},
                    function_docstrings=docstrings,
                )
            )

        if lb_funcs:
            lb_routes = [
                {
                    "method": f.http_method,
                    "path": f.http_path,
                    "fn_name": f.function_name,
                    "config_variable": f.config_variable,
                    "docstring": f.docstring,
                    "local": f.local,
                }
                for f in lb_funcs
            ]
            lb_docstrings: dict[str, str] = {}
            for f in lb_funcs:
                if f.docstring:
                    lb_docstrings[f.function_name] = f.docstring
            workers.append(
                WorkerInfo(
                    file_path=file_path,
                    url_prefix=url_prefix,
                    module_path=module_path,
                    resource_name=resource_name,
                    worker_type="LB",
                    functions=[f.function_name for f in lb_funcs],
                    lb_routes=lb_routes,
                    function_docstrings=lb_docstrings,
                )
            )

    return workers, scanner


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
    """Sanitize a string for use as a Python function name.

    Replaces non-identifier characters with underscores and prepends '_'
    if the result starts with a digit (Python identifiers cannot start
    with digits).
    """
    result = name.replace("/", "_").replace(".", "_").replace("-", "_")
    if result and result[0].isdigit():
        result = "_" + result
    return result


def _has_numeric_module_segments(module_path: str) -> bool:
    """Check if any segment in a dotted module path starts with a digit.

    Python identifiers cannot start with digits, so ``from 01_foo import bar``
    is a SyntaxError. Callers should use ``importlib.import_module()`` instead.
    """
    return any(seg and seg[0].isdigit() for seg in module_path.split("."))


def _module_parent_subdir(module_path: str) -> str | None:
    """Return the parent sub-directory for a dotted module path, or None for top-level.

    Example: ``01_getting_started.03_mixed.pipeline`` → ``01_getting_started/03_mixed``
    """
    parts = module_path.rsplit(".", 1)
    if len(parts) == 1:
        return None
    return parts[0].replace(".", "/")


def _make_import_line(module_path: str, name: str, alias: str | None = None) -> str:
    """Build an import statement for *name* from *module_path*.

    Uses a regular ``from … import …`` when the module path is a valid
    Python identifier chain. Falls back to ``_flash_import()`` (a generated
    helper in server.py) when any segment starts with a digit. The helper
    temporarily scopes ``sys.path`` so sibling imports in the target module
    resolve to the correct directory.

    Args:
        module_path: Dotted module path to import from.
        name: Symbol name to import.
        alias: If provided, assign the import to this variable name instead
            of *name*. Prevents collisions when multiple modules export the
            same symbol (e.g. multiple files exporting ``api``).
    """
    target = alias or name
    if _has_numeric_module_segments(module_path):
        subdir = _module_parent_subdir(module_path)
        if subdir:
            return f'{target} = _flash_import("{module_path}", "{name}", "{subdir}")'
        return f'{target} = _flash_import("{module_path}", "{name}")'
    if alias:
        return f"from {module_path} import {name} as {alias}"
    return f"from {module_path} import {name}"


def _escape_summary(text: str) -> str:
    """Escape a string for safe embedding in a generated Python string literal."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def _extract_path_params(path: str) -> list[str]:
    """Extract path parameter names from a FastAPI-style route path.

    Example: "/images/{file_id}" -> ["file_id"]
    """
    return _PATH_PARAM_RE.findall(path)


def _build_call_expr(callable_name: str, params: list[str] | None) -> tuple[str, bool]:
    """Build an async call expression based on parameter count.

    Args:
        callable_name: Fully qualified callable (e.g. "fn" or "instance.method")
        params: List of param names, or None if unknown (backward compat)

    Returns:
        Tuple of (call_expression, needs_body). needs_body is False when the
        handler signature should omit the body parameter.
    """
    if params is not None and len(params) == 0:
        return f"await {callable_name}()", False
    return f"await _call_with_body({callable_name}, body)", True


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

    has_lb_workers = any(w.worker_type == "LB" for w in workers)

    lines = [
        '"""Auto-generated Flash dev server. Do not edit — regenerated on each flash run."""',
        "import sys",
        "import uuid",
        "from pathlib import Path",
        "_project_root = Path(__file__).parent.parent",
        "sys.path.insert(0, str(_project_root))",
        "",
    ]

    # When modules live in directories with numeric prefixes (e.g. 01_hello/),
    # we cannot use ``from … import …`` — Python identifiers cannot start with
    # digits.  Instead we emit a small ``_flash_import`` helper that uses
    # ``importlib.import_module()`` *and* temporarily scopes ``sys.path`` so
    # that sibling imports inside the loaded module (e.g. ``from cpu_worker
    # import …``) resolve to the correct directory rather than a same-named
    # file from a different example subdirectory.
    needs_importlib = any(_has_numeric_module_segments(w.module_path) for w in workers)

    if needs_importlib:
        lines += [
            "import importlib as _importlib",
            "",
            "",
            "def _flash_import(module_path, name, subdir=None):",
            '    """Import *name* from *module_path* with scoped sys.path for sibling imports."""',
            "    _path = str(_project_root / subdir) if subdir else None",
            "    if _path:",
            "        sys.path.insert(0, _path)",
            "    try:",
            "        return getattr(_importlib.import_module(module_path), name)",
            "    finally:",
            "        if _path is not None:",
            "            try:",
            "                if sys.path and sys.path[0] == _path:",
            "                    sys.path.pop(0)",
            "                else:",
            "                    sys.path.remove(_path)",
            "            except ValueError:",
            "                pass",
            "",
        ]

    lines += [
        "from runpod_flash.cli.commands._run_server_helpers import make_input_model as _make_input_model",
        "from runpod_flash.cli.commands._run_server_helpers import make_wrapped_model as _make_wrapped_model",
        "from runpod_flash.cli.commands._run_server_helpers import call_with_body as _call_with_body",
        "from runpod_flash.cli.commands._run_server_helpers import has_file_params as _has_file_params",
        "from runpod_flash.cli.commands._run_server_helpers import register_file_upload_lb_route as _register_file_upload_lb_route",
    ]

    if has_lb_workers:
        lines += [
            "from fastapi import FastAPI, Request",
            "from runpod_flash.cli.commands._run_server_helpers import lb_execute as _lb_execute",
            "from runpod_flash.cli.commands._run_server_helpers import to_dict as _to_dict",
            "",
        ]
    else:
        lines += [
            "from fastapi import FastAPI",
            "",
        ]

    # Purge user modules from sys.modules so uvicorn hot-reload reimports them
    # with current code and config values (e.g. updated env dicts).
    user_modules = sorted({w.module_path for w in workers})
    if user_modules:
        module_list = ", ".join(f'"{m}"' for m in user_modules)
        lines += [
            f"for _mod in [{module_list}]:",
            "    sys.modules.pop(_mod, None)",
            "",
        ]

    # Collect imports — QB functions are called directly, LB config variables and
    # functions are passed to lb_execute for dispatch via LoadBalancerSlsStub.
    all_imports: List[str] = []
    for worker in workers:
        if worker.worker_type == "QB":
            for fn_name in worker.functions:
                all_imports.append(_make_import_line(worker.module_path, fn_name))
            for cls_info in worker.class_remotes:
                all_imports.append(
                    _make_import_line(worker.module_path, cls_info["name"])
                )
        elif worker.worker_type == "LB":
            # Import the resource config variable (e.g. "api" from api = LiveLoadBalancer(...))
            # Use aliased names to prevent collisions when multiple files export
            # the same variable name (e.g. multiple files exporting "api").
            config_vars = {
                r["config_variable"]
                for r in worker.lb_routes
                if r.get("config_variable")
            }
            for var in sorted(config_vars):
                alias = f"_cfg_{_sanitize_fn_name(worker.resource_name)}"
                all_imports.append(
                    _make_import_line(worker.module_path, var, alias=alias)
                )
                # Store the alias so route codegen can reference it
                for r in worker.lb_routes:
                    if r.get("config_variable") == var:
                        r["_config_alias"] = alias
            for fn_name in worker.functions:
                all_imports.append(_make_import_line(worker.module_path, fn_name))

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

    # Module-level instance creation for @remote classes
    for worker in workers:
        for cls_info in worker.class_remotes:
            cls_name = cls_info["name"]
            lines.append(f"_instance_{cls_name} = {cls_name}()")
    # Add blank line if any instances were created
    if any(worker.class_remotes for worker in workers):
        lines.append("")

    # Module-level Pydantic model creation for typed Swagger UI
    model_lines: list[str] = []
    for worker in workers:
        if worker.worker_type == "QB":
            for fn in worker.functions:
                params = worker.function_params.get(fn)
                if params is None or len(params) > 0:
                    input_var = f"_{worker.resource_name}_{fn}_Input"
                    request_var = f"_{worker.resource_name}_{fn}_Request"
                    model_lines.append(
                        f'{input_var} = _make_input_model("{input_var}", {fn}) or dict'
                    )
                    model_lines.append(
                        f'{request_var} = _make_wrapped_model("{request_var}", {input_var})'
                    )
            for cls_info in worker.class_remotes:
                cls_name = cls_info["name"]
                method_params = cls_info.get("method_params", {})
                instance_var = f"_instance_{cls_name}"
                for method in cls_info["methods"]:
                    params = method_params.get(method)
                    if params is None or len(params) > 0:
                        input_var = f"_{worker.resource_name}_{cls_name}_{method}_Input"
                        request_var = (
                            f"_{worker.resource_name}_{cls_name}_{method}_Request"
                        )
                        # Use _class_type to get the original unwrapped method
                        # (RemoteClassWrapper.__getattr__ returns proxies with (*args, **kwargs))
                        class_ref = f"getattr({instance_var}, '_class_type', type({instance_var}))"
                        model_lines.append(
                            f'{input_var} = _make_input_model("{input_var}", {class_ref}.{method}) or dict'
                        )
                        model_lines.append(
                            f'{request_var} = _make_wrapped_model("{request_var}", {input_var})'
                        )
        elif worker.worker_type == "LB":
            for route in worker.lb_routes:
                method = route["method"].lower()
                if method in ("post", "put", "patch", "delete"):
                    fn_name = route["fn_name"]
                    # Skip Pydantic model for file-upload routes (handled by
                    # register_file_upload_lb_route at runtime)
                    model_var = f"_{worker.resource_name}_{fn_name}_Input"
                    model_lines.append(f"if not _has_file_params({fn_name}):")
                    model_lines.append(
                        f'    {model_var} = _make_input_model("{model_var}", {fn_name}) or dict'
                    )
    if model_lines:
        lines.extend(model_lines)
        lines.append("")

    for worker in workers:
        # Group routes by project directory in Swagger UI.
        # Nested: /03_mixed_workers/cpu_worker -> "03_mixed_workers/"
        # Root:   /worker                      -> "worker"
        prefix = worker.url_prefix.lstrip("/")
        tag = f"{prefix.rsplit('/', 1)[0]}/" if "/" in prefix else prefix
        lines.append(f"# {'─' * 60}")
        lines.append(f"# {worker.worker_type}: {worker.file_path.name}")
        lines.append(f"# {'─' * 60}")

        if worker.worker_type == "QB":
            # Total callable count: functions + sum of class methods
            total_class_methods = sum(len(c["methods"]) for c in worker.class_remotes)
            total_callables = len(worker.functions) + total_class_methods
            use_multi = total_callables > 1

            # Function-based routes
            for fn in worker.functions:
                if use_multi:
                    handler_name = _sanitize_fn_name(
                        f"{worker.resource_name}_{fn}_runsync"
                    )
                    sync_path = f"{worker.url_prefix}/{fn}/runsync"
                else:
                    handler_name = _sanitize_fn_name(f"{worker.resource_name}_runsync")
                    sync_path = f"{worker.url_prefix}/runsync"
                params = worker.function_params.get(fn)
                call_expr, needs_body = _build_call_expr(fn, params)
                if needs_body:
                    request_var = f"_{worker.resource_name}_{fn}_Request"
                    handler_sig = f"async def {handler_name}(body: {request_var}):"
                    call_expr = call_expr.replace("body)", "body.input)")
                else:
                    handler_sig = f"async def {handler_name}():"
                summary = _escape_summary(worker.function_docstrings.get(fn, fn))
                lines += [
                    f'@app.post("{sync_path}", tags=["{tag}"], summary="{summary}")',
                    handler_sig,
                    f"    result = {call_expr}",
                    '    return {"id": str(uuid.uuid4()), "status": "COMPLETED", "output": result}',
                    "",
                ]

            # Class-based routes
            for cls_info in worker.class_remotes:
                cls_name = cls_info["name"]
                methods = cls_info["methods"]
                method_params = cls_info.get("method_params", {})
                instance_var = f"_instance_{cls_name}"

                for method in methods:
                    if use_multi:
                        handler_name = _sanitize_fn_name(
                            f"{worker.resource_name}_{cls_name}_{method}_runsync"
                        )
                        sync_path = f"{worker.url_prefix}/{method}/runsync"
                    else:
                        handler_name = _sanitize_fn_name(
                            f"{worker.resource_name}_{cls_name}_runsync"
                        )
                        sync_path = f"{worker.url_prefix}/runsync"
                    params = method_params.get(method)
                    call_expr, needs_body = _build_call_expr(
                        f"{instance_var}.{method}", params
                    )
                    if needs_body:
                        request_var = (
                            f"_{worker.resource_name}_{cls_name}_{method}_Request"
                        )
                        handler_sig = f"async def {handler_name}(body: {request_var}):"
                        call_expr = call_expr.replace("body)", "body.input)")
                    else:
                        handler_sig = f"async def {handler_name}():"
                    summary = _escape_summary(
                        worker.function_docstrings.get(method, method)
                    )
                    lines += [
                        f'@app.post("{sync_path}", tags=["{tag}"], summary="{summary}")',
                        handler_sig,
                        f"    result = {call_expr}",
                        '    return {"id": str(uuid.uuid4()), "status": "COMPLETED", "output": result}',
                        "",
                    ]

        elif worker.worker_type == "LB":
            for route in worker.lb_routes:
                method = route["method"].lower()
                sub_path = route["path"].lstrip("/")
                fn_name = route["fn_name"]
                config_var = route.get("_config_alias") or route["config_variable"]
                full_path = f"{worker.url_prefix}/{sub_path}"
                handler_name = _sanitize_fn_name(
                    f"_route_{worker.resource_name}_{fn_name}"
                )
                path_params = _extract_path_params(full_path)
                has_body = method in ("post", "put", "patch", "delete")
                summary = _escape_summary(route.get("docstring") or fn_name)
                is_local = route.get("local", False)
                if is_local:
                    # local=True: execute function directly, no remote dispatch
                    if has_body:
                        lines += [
                            f"if _has_file_params({fn_name}):",
                            f'    _register_file_upload_lb_route(app, "{method}", "{full_path}", {config_var}, {fn_name}, "{tag}", "{summary}", local=True)',
                            "else:",
                        ]
                        model_var = f"_{worker.resource_name}_{fn_name}_Input"
                        if path_params:
                            param_sig = ", ".join(f"{p}: str" for p in path_params)
                            param_dict = ", ".join(f'"{p}": {p}' for p in path_params)
                            lines += [
                                f'    @app.{method}("{full_path}", tags=["{tag}"], summary="{summary}")',
                                f"    async def {handler_name}(body: {model_var}, {param_sig}):",
                                f"        return await _call_with_body({fn_name}, {{**_to_dict(body), {param_dict}}})",
                                "",
                            ]
                        else:
                            lines += [
                                f'    @app.{method}("{full_path}", tags=["{tag}"], summary="{summary}")',
                                f"    async def {handler_name}(body: {model_var}):",
                                f"        return await _call_with_body({fn_name}, _to_dict(body))",
                                "",
                            ]
                    else:
                        # GET/etc: path params + query params, local execution
                        if path_params:
                            param_sig = ", ".join(f"{p}: str" for p in path_params)
                            param_dict = ", ".join(f'"{p}": {p}' for p in path_params)
                            lines += [
                                f'@app.{method}("{full_path}", tags=["{tag}"], summary="{summary}")',
                                f"async def {handler_name}({param_sig}, request: Request):",
                                f"    return await _call_with_body({fn_name}, {{**dict(request.query_params), {param_dict}}})",
                                "",
                            ]
                        else:
                            lines += [
                                f'@app.{method}("{full_path}", tags=["{tag}"], summary="{summary}")',
                                f"async def {handler_name}(request: Request):",
                                f"    return await _call_with_body({fn_name}, dict(request.query_params))",
                                "",
                            ]
                else:
                    # Remote dispatch via lb_execute
                    if has_body:
                        # File-upload routes use runtime registration instead of
                        # inline codegen (avoids complex File()/Form() string templates)
                        lines += [
                            f"if _has_file_params({fn_name}):",
                            f'    _register_file_upload_lb_route(app, "{method}", "{full_path}", {config_var}, {fn_name}, "{tag}", "{summary}")',
                            "else:",
                        ]
                        model_var = f"_{worker.resource_name}_{fn_name}_Input"
                        # POST/PUT/PATCH/DELETE: typed body + optional path params
                        if path_params:
                            param_sig = ", ".join(f"{p}: str" for p in path_params)
                            param_dict = ", ".join(f'"{p}": {p}' for p in path_params)
                            lines += [
                                f'    @app.{method}("{full_path}", tags=["{tag}"], summary="{summary}")',
                                f"    async def {handler_name}(body: {model_var}, {param_sig}):",
                                f"        return await _lb_execute({config_var}, {fn_name}, {{**_to_dict(body), {param_dict}}})",
                                "",
                            ]
                        else:
                            lines += [
                                f'    @app.{method}("{full_path}", tags=["{tag}"], summary="{summary}")',
                                f"    async def {handler_name}(body: {model_var}):",
                                f"        return await _lb_execute({config_var}, {fn_name}, _to_dict(body))",
                                "",
                            ]
                    else:
                        # GET/etc: path params + query params (unchanged)
                        if path_params:
                            param_sig = ", ".join(f"{p}: str" for p in path_params)
                            param_dict = ", ".join(f'"{p}": {p}' for p in path_params)
                            lines += [
                                f'@app.{method}("{full_path}", tags=["{tag}"], summary="{summary}")',
                                f"async def {handler_name}({param_sig}, request: Request):",
                                f"    return await _lb_execute({config_var}, {fn_name}, {{**dict(request.query_params), {param_dict}}})",
                                "",
                            ]
                        else:
                            lines += [
                                f'@app.{method}("{full_path}", tags=["{tag}"], summary="{summary}")',
                                f"async def {handler_name}(request: Request):",
                                f"    return await _lb_execute({config_var}, {fn_name}, dict(request.query_params))",
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
    console.print(f"\n[bold green]Flash Dev Server[/bold green]  localhost:{port}")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Local path", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Type", style="yellow")

    def _truncate(text: str, max_len: int = 60) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    for worker in workers:
        if worker.worker_type == "QB":
            total_class_methods = sum(len(c["methods"]) for c in worker.class_remotes)
            total_callables = len(worker.functions) + total_class_methods
            use_multi = total_callables > 1

            for fn in worker.functions:
                desc = _truncate(worker.function_docstrings.get(fn, fn))
                if use_multi:
                    table.add_row(
                        f"POST  {worker.url_prefix}/{fn}/runsync",
                        desc,
                        "QB",
                    )
                else:
                    table.add_row(
                        f"POST  {worker.url_prefix}/runsync",
                        desc,
                        "QB",
                    )

            for cls_info in worker.class_remotes:
                methods = cls_info["methods"]
                for method in methods:
                    desc = _truncate(worker.function_docstrings.get(method, method))
                    if use_multi:
                        table.add_row(
                            f"POST  {worker.url_prefix}/{method}/runsync",
                            desc,
                            "QB",
                        )
                    else:
                        table.add_row(
                            f"POST  {worker.url_prefix}/runsync",
                            desc,
                            "QB",
                        )
        elif worker.worker_type == "LB":
            for route in worker.lb_routes:
                sub_path = route["path"].lstrip("/")
                full_path = f"{worker.url_prefix}/{sub_path}"
                desc = _truncate(route.get("docstring") or route["fn_name"])
                route_type = "LB (local)" if route.get("local") else "LB"
                table.add_row(
                    f"{route['method']}  {full_path}",
                    desc,
                    route_type,
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

    import asyncio
    import cloudpickle
    from ...core.utils.file_lock import file_lock

    # Load persisted resource state. If this fails (lock error, corruption),
    # log and return — don't let it prevent the rest of shutdown.
    try:
        with open(_RESOURCE_STATE_FILE, "rb") as f:
            with file_lock(f, exclusive=False):
                data = cloudpickle.load(f)
    except Exception as e:
        logger.warning(f"Could not read resource state for cleanup: {e}")
        return

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
    loop = asyncio.new_event_loop()
    try:
        undeployed = loop.run_until_complete(_do_cleanup())
    finally:
        loop.close()
    elapsed = time.monotonic() - t0
    console.print(
        f"  Cleanup completed: {undeployed}/{len(live_items)} "
        f"resource(s) undeployed in {elapsed:.1f}s"
    )

    # Remove live- entries from persisted state so they don't linger.
    remaining = {k: v for k, v in resources.items() if k not in live_items}
    remaining_configs = {k: v for k, v in configs.items() if k not in live_items}
    try:
        with open(_RESOURCE_STATE_FILE, "wb") as f:
            with file_lock(f, exclusive=True):
                cloudpickle.dump((remaining, remaining_configs), f)
    except Exception as e:
        logger.warning(f"Could not update resource state after cleanup: {e}")


def _is_reload() -> bool:
    """Check if running in uvicorn reload subprocess."""
    return "UVICORN_RELOADER_PID" in os.environ


def _watch_and_regenerate(project_root: Path, stop_event: threading.Event) -> None:
    """Watch project .py files and regenerate server.py when they change.

    Ignores .flash/ to avoid reacting to our own writes. Runs until
    stop_event is set.
    """
    # Suppress watchfiles' internal debug chatter (filter hits, rust timeouts).
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    watch_filter = _WatchfilesDefaultFilter(ignore_paths=[str(project_root / ".flash")])

    try:
        for changes in _watchfiles_watch(
            project_root,
            watch_filter=watch_filter,
            stop_event=stop_event,
        ):
            py_changed = [p for _, p in changes if p.endswith(".py")]
            if not py_changed:
                continue
            try:
                workers, _ = _scan_project_workers(project_root)
                _generate_flash_server(project_root, workers)
                logger.debug("server.py regenerated (%d changed)", len(py_changed))
            except Exception as e:
                logger.warning("Failed to regenerate server.py: %s", e)
    except ModuleNotFoundError as e:
        logger.warning("File watching disabled: %s", e)
    except Exception as e:
        if not stop_event.is_set():
            logger.exception("Unexpected error in file watcher: %s", e)


def _discover_resources(project_root: Path):
    """Discover deployable resources in project files.

    Imports each python file and inspects module-level objects for
    DeployableResource instances and Endpoint facades. Endpoint facades
    are unwrapped via _build_resource_config() to get the inner resource.

    Args:
        project_root: Root directory of the Flash project

    Returns:
        List of discovered DeployableResource instances
    """
    from ...core.resources.base import DeployableResource
    from ...endpoint import Endpoint

    from .build_utils.scanner import _import_module_from_file

    spec = load_ignore_patterns(project_root)
    all_files = get_file_tree(project_root, spec)
    py_files = sorted(
        f for f in all_files if f.suffix == ".py" and f.name != "__init__.py"
    )

    root_str = str(project_root)
    added_to_path = root_str not in sys.path
    if added_to_path:
        sys.path.insert(0, root_str)

    resources = []
    seen_names: set[str] = set()
    try:
        for py_file in py_files:
            try:
                module_path = file_to_module_path(py_file, project_root)
                module = _import_module_from_file(py_file, module_path)
                if module is None:
                    continue

                for name in dir(module):
                    try:
                        obj = getattr(module, name)
                    except Exception:
                        continue

                    resource = None
                    if isinstance(obj, DeployableResource):
                        resource = obj
                    elif isinstance(obj, Endpoint) and not obj.is_client:
                        resource = obj._build_resource_config()
                    elif hasattr(obj, "__remote_config__"):
                        cfg = getattr(obj, "__remote_config__", {})
                        rc = cfg.get("resource_config")
                        if isinstance(rc, Endpoint) and not rc.is_client:
                            resource = rc._build_resource_config()
                        elif isinstance(rc, DeployableResource):
                            resource = rc

                    if resource is not None:
                        res_name = getattr(resource, "name", None) or name
                        if res_name not in seen_names:
                            seen_names.add(res_name)
                            resources.append(resource)

            except Exception as e:
                logger.debug("Discovery failed for %s: %s", py_file, e)
    finally:
        if added_to_path:
            try:
                sys.path.remove(root_str)
            except ValueError:
                pass

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
    from ...core.exceptions import RunpodAPIKeyError

    console.print(f"[bold]Provisioning {len(resources)} resource(s)...[/bold]")
    orchestrator = DeploymentOrchestrator(max_concurrent=3)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(orchestrator.deploy_all(resources, show_progress=True))
    except RunpodAPIKeyError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Provisioning failed: {e}")
        console.print(
            "[dim]Resources will be provisioned on-demand at first request.[/dim]"
        )
    finally:
        loop.close()


def _discover_and_start_pods(
    project_root: Path,
) -> tuple[list[Pod], PodLifecycleManager | None, PodRegistry | None]:
    """Discover Pod definitions and start/resume them for dev session."""
    try:
        sys.path.insert(0, str(project_root))
        scanner = PodScanner()

        pods: list[Pod] = []
        for py_file in project_root.rglob("*.py"):
            if any(part.startswith((".", "__")) for part in py_file.parts):
                continue
            if py_file.name.startswith("__"):
                continue
            rel = py_file.relative_to(project_root)
            module_name = str(rel.with_suffix("")).replace(os.sep, ".")
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    pods.extend(scanner.scan(mod))
            except Exception:
                continue

        if not pods:
            return [], None, None

        api_key = get_api_key()
        if not api_key:
            console.print(
                "[yellow]Warning: No API key found. Skipping pod management.[/yellow]"
            )
            return [], None, None

        flash_dir = project_root / ".flash"
        flash_dir.mkdir(exist_ok=True)
        api_client = PodApiClient(api_key=api_key)
        tracker = PodTracker(flash_dir)
        lifecycle = PodLifecycleManager(api_client, tracker)
        registry = PodRegistry(tracker, api_client)

        started_pods: list[Pod] = []
        for pod in pods:
            entry = tracker.load(pod.name)
            try:
                if entry and entry.state == "stopped":
                    console.print(f"Resuming pod '{pod.name}'...")
                    pod._pod_id = entry.pod_id
                    pod._state = PodState.STOPPED
                    pod = asyncio.run(lifecycle.resume(pod))
                    console.print(
                        f"  Pod '{pod.name}' running at {pod._address or 'pending'}"
                    )
                elif entry and entry.state == "running":
                    pod._pod_id = entry.pod_id
                    pod._state = PodState.RUNNING
                    pod._address = entry.address
                    pod = asyncio.run(lifecycle.sync_state(pod))
                    console.print(
                        f"  Pod '{pod.name}' already running at"
                        f" {pod._address or 'pending'}"
                    )
                else:
                    console.print(f"Creating pod '{pod.name}'...")
                    pod = asyncio.run(lifecycle.provision(pod))
                    console.print(
                        f"  Pod '{pod.name}' running at {pod._address or 'pending'}"
                    )
                pod._bind_registry(registry)
                started_pods.append(pod)
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to start pod '{pod.name}': {e}[/yellow]"
                )

        return started_pods, lifecycle, registry
    except Exception as e:
        logger.debug(f"Pod discovery failed: {e}")
        return [], None, None


def _stop_pods(pods: list[Pod], lifecycle: PodLifecycleManager) -> None:
    """Stop all running pods on shutdown."""
    for pod in pods:
        if pod._state == PodState.RUNNING:
            try:
                console.print(f"Stopping pod '{pod.name}'...")
                asyncio.run(lifecycle.stop(pod))
                console.print(
                    f"  Pod '{pod.name}' stopped. Will resume on next flash run."
                )
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to stop pod '{pod.name}': {e}[/yellow]"
                )

    if pods:
        console.print(
            f"\n{len(pods)} pod(s) stopped. "
            f"Run 'flash run' to resume, or 'flash pod terminate <name>' to delete."
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

    # Auto-provision all endpoints upfront (eliminates cold-start)
    if auto_provision and not _is_reload():
        try:
            resources = _discover_resources(project_root)
            if resources:
                _provision_resources(resources)
        except (typer.Exit, SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:
            logger.error("Auto-provisioning failed", exc_info=True)
            console.print(f"[yellow]Warning:[/yellow] Auto-provisioning failed: {e}")
            console.print(
                "[dim]Resources will be provisioned on-demand at first request.[/dim]"
            )

    # Discover @remote functions
    workers, scanner = _scan_project_workers(project_root)

    if scanner.import_errors:
        console.print("\n[red bold]Failed to load:[/red bold]")
        for filename, err in scanner.import_errors.items():
            console.print(f"  [red]{filename}[/red]: {err}")
        console.print()
        raise typer.Exit(1)

    # Discover and start pods
    running_pods, pod_lifecycle, pod_registry = _discover_and_start_pods(project_root)

    if not workers:
        console.print(
            "\n[red bold]No endpoints found.[/red bold]\n"
            "\n"
            "  [dim]Queue-based:[/dim]\n"
            "    @Endpoint(name='worker', gpu=GpuGroup.ANY)\n"
            "    async def process(input_data: dict) -> dict: ...\n"
            "\n"
            "  [dim]Load-balanced:[/dim]\n"
            "    api = Endpoint(name='api', cpu='cpu3g-2-8')\n"
            "    @api.post('/compute')\n"
            "    async def compute(data: dict) -> dict: ...\n"
        )
        raise typer.Exit(1)

    # find a free port, counting up from the requested one
    actual_port = _find_available_port(host, port)
    if actual_port != port:
        console.print(
            f"[yellow]Port {port} is in use, using {actual_port} instead.[/yellow]"
        )
    port = actual_port

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
            ".flash",
            "--reload-include",
            "server.py",
        ]

    stop_event = threading.Event()
    watcher_thread = None
    if reload:
        watcher_thread = threading.Thread(
            target=_watch_and_regenerate,
            args=(project_root, stop_event),
            daemon=True,
            name="flash-watcher",
        )

    process = None
    try:
        if sys.platform == "win32":
            process = subprocess.Popen(
                cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            process = subprocess.Popen(cmd, preexec_fn=os.setsid)

        if watcher_thread is not None:
            watcher_thread.start()

        process.wait()

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping server and cleaning up...[/yellow]")

        # Stop pods before shutting down server
        if running_pods and pod_lifecycle:
            _stop_pods(running_pods, pod_lifecycle)

        stop_event.set()
        if watcher_thread is not None and watcher_thread.is_alive():
            watcher_thread.join(timeout=2)

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

        stop_event.set()
        if watcher_thread is not None and watcher_thread.is_alive():
            watcher_thread.join(timeout=2)

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
