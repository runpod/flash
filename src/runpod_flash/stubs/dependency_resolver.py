"""Dependency resolver for stacked @remote function execution.

When @remote funcA calls @remote funcB, the worker only receives funcA's source.
This module detects such dependencies, provisions their endpoints, and generates
dispatch stubs so funcB resolves correctly inside the worker's exec() namespace.
"""

import ast
import inspect
import logging
from dataclasses import dataclass
from typing import Any

from .live_serverless import get_function_source

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteDependency:
    """A resolved @remote dependency ready for stub generation."""

    name: str
    endpoint_id: str
    source: str
    dependencies: list[str]
    system_dependencies: list[str]


def detect_remote_dependencies(source: str, func_globals: dict[str, Any]) -> list[str]:
    """Find names of @remote functions called in *source*.

    Parses the source AST and checks each direct function call (ast.Name)
    against *func_globals* for the ``__remote_config__`` attribute set by
    the @remote decorator.

    Only direct calls (``await funcB(x)``) are detected.  Attribute calls
    (``obj.funcB(x)``) and indirect references (``f = funcB; f(x)``) are
    intentionally ignored (V1 limitation).

    Args:
        source: Source code string of the calling function.
        func_globals: The ``__globals__`` dict of the calling function,
            used to resolve called names.

    Returns:
        Sorted list of names that resolve to @remote-decorated objects.
    """
    tree = ast.parse(source)
    called_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)

    remote_deps = [
        name
        for name in sorted(called_names)
        if hasattr(func_globals.get(name), "__remote_config__")
    ]
    return remote_deps


async def resolve_dependencies(
    source: str, func_globals: dict[str, Any]
) -> list[RemoteDependency]:
    """Detect @remote dependencies and provision their endpoints.

    For each detected dependency:
    1. Extract resource_config from ``__remote_config__``
    2. Provision via ``ResourceManager().get_or_deploy_resource()``
    3. Return a ``RemoteDependency`` with the provisioned endpoint_id

    Args:
        source: Source code of the calling function.
        func_globals: The ``__globals__`` dict of the calling function.

    Returns:
        List of resolved dependencies with endpoint IDs.

    Raises:
        RuntimeError: If endpoint provisioning fails for any dependency.
    """
    dep_names = detect_remote_dependencies(source, func_globals)
    if not dep_names:
        return []

    from ..core.resources import ResourceManager

    resource_manager = ResourceManager()
    resolved: list[RemoteDependency] = []

    for name in dep_names:
        dep_func = func_globals[name]
        config = dep_func.__remote_config__

        resource_config = config["resource_config"]
        remote_resource = await resource_manager.get_or_deploy_resource(resource_config)

        # Get source of the dependency function
        unwrapped = inspect.unwrap(dep_func)
        dep_source, _ = get_function_source(unwrapped)

        resolved.append(
            RemoteDependency(
                name=name,
                endpoint_id=remote_resource.id,
                source=dep_source,
                dependencies=config.get("dependencies") or [],
                system_dependencies=config.get("system_dependencies") or [],
            )
        )
        log.debug(
            "Resolved dependency %s -> endpoint %s",
            name,
            remote_resource.id,
        )

    return resolved


def generate_stub_code(dep: RemoteDependency) -> str:
    """Generate an async stub function that dispatches to a remote endpoint.

    The stub preserves the original function's parameter names so callers
    can use ``await funcB(payload)`` naturally.  Inside the stub, arguments
    are serialized with cloudpickle and sent via aiohttp to the RunPod
    runsync endpoint.

    Args:
        dep: Resolved dependency with endpoint_id and source.

    Returns:
        Python source code string defining the async stub function.
    """
    # Parse the dependency source to extract parameter names
    tree = ast.parse(dep.source)
    params_str = "*args, **kwargs"
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == dep.name
        ):
            params_str = _extract_params(node)
            break

    # Build serialization expressions for args/kwargs
    ser_args_expr, ser_kwargs_expr = _build_serialization_exprs(tree, dep.name)

    I = "    "  # noqa: E741 — single indent level
    lines = [
        f"async def {dep.name}({params_str}):",
        f"{I}import os as _os",
        f"{I}import base64 as _b64",
        f"{I}import cloudpickle as _cp",
        f"{I}import aiohttp as _aiohttp",
        "",
        f"{I}_endpoint_id = {repr(dep.endpoint_id)}",
        f'{I}_api_key = _os.environ.get("RUNPOD_API_KEY", "")',
        f'{I}_url = f"https://api.runpod.ai/v2/{{_endpoint_id}}/runsync"',
        f'{I}_headers = {{"Content-Type": "application/json"}}',
        f"{I}if _api_key:",
        f'{I}{I}_headers["Authorization"] = f"Bearer {{_api_key}}"',
        "",
        f"{I}_func_source = {repr(dep.source)}",
        f"{I}_ser_args = {ser_args_expr}",
        f"{I}_ser_kwargs = {ser_kwargs_expr}",
        f"{I}_payload = {{",
        f'{I}{I}"input": {{',
        f'{I}{I}{I}"function_name": {repr(dep.name)},',
        f'{I}{I}{I}"function_code": _func_source,',
        f'{I}{I}{I}"args": _ser_args,',
        f'{I}{I}{I}"kwargs": _ser_kwargs,',
        f'{I}{I}{I}"dependencies": {repr(dep.dependencies)},',
        f'{I}{I}{I}"system_dependencies": {repr(dep.system_dependencies)},',
        f"{I}{I}}}",
        f"{I}}}",
        "",
        f"{I}_timeout = _aiohttp.ClientTimeout(total=300)",
        f"{I}async with _aiohttp.ClientSession(timeout=_timeout) as _sess:",
        f"{I}{I}async with _sess.post(_url, json=_payload, headers=_headers) as _resp:",
        f"{I}{I}{I}if _resp.status != 200:",
        f"{I}{I}{I}{I}_err = await _resp.text()",
        f"{I}{I}{I}{I}raise RuntimeError(",
        f'{I}{I}{I}{I}{I}f"Remote {dep.name} failed (HTTP {{_resp.status}}): {{_err}}"',
        f"{I}{I}{I}{I})",
        f"{I}{I}{I}_data = await _resp.json()",
        f'{I}{I}{I}_output = _data.get("output", _data)',
        f'{I}{I}{I}if not _output.get("success"):',
        f"{I}{I}{I}{I}raise RuntimeError(",
        f"{I}{I}{I}{I}{I}f\"Remote {dep.name} failed: {{_output.get('error')}}\"",
        f"{I}{I}{I}{I})",
        f'{I}{I}{I}return _cp.loads(_b64.b64decode(_output["result"]))',
    ]
    return "\n".join(lines) + "\n"


def build_augmented_source(original_source: str, stub_codes: list[str]) -> str:
    """Prepend stub code blocks before the original function source.

    Args:
        original_source: The calling function's source code.
        stub_codes: List of stub code strings to prepend.

    Returns:
        Combined source with stubs before the original function.
    """
    if not stub_codes:
        return original_source

    parts = stub_codes + [original_source]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_params(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Extract parameter list string from an AST function node."""
    params = [arg.arg for arg in func_node.args.args]
    return ", ".join(params) if params else "*args, **kwargs"


def _build_serialization_exprs(tree: ast.Module, func_name: str) -> tuple[str, str]:
    """Return (args_expr, kwargs_expr) for serializing function parameters.

    When the original signature has named params, we serialize each by name.
    Otherwise fall back to generic *args/**kwargs serialization.
    """
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
            param_names = [arg.arg for arg in node.args.args]
            if param_names:
                items = ", ".join(
                    f"_b64.b64encode(_cp.dumps({p})).decode()" for p in param_names
                )
                return f"[{items}]", "{}"

    # Fallback for *args, **kwargs
    return (
        "[_b64.b64encode(_cp.dumps(a)).decode() for a in args]",
        "{k: _b64.b64encode(_cp.dumps(v)).decode() for k, v in kwargs.items()}",
    )
