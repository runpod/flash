"""Helpers for the flash run dev server — loaded inside the generated server.py."""

import inspect
import logging
import re
from typing import Any, get_type_hints

from fastapi import File, Form, HTTPException
from pydantic import create_model

from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub

log = logging.getLogger(__name__)

_resource_manager = ResourceManager()


def _map_body_to_params(func, body):
    """Map an HTTP request body to function parameters.

    If the body is a dict whose keys match the function's parameter names,
    spread it as kwargs.  Otherwise pass the whole body as the value of the
    first parameter (mirrors how FastAPI maps a JSON body to a single param).
    """
    sig = inspect.signature(func)
    param_names = set(sig.parameters.keys())

    if isinstance(body, dict) and body.keys() <= param_names:
        return body

    first_param = next(iter(sig.parameters), None)
    if first_param is None:
        return {}
    return {first_param: body}


def make_wrapped_model(name: str, inner_model: type) -> type:
    """Wrap a Pydantic model in an 'input' envelope for RunPod API consistency."""
    return create_model(name, input=(inner_model, ...))


def make_input_model(name: str, func) -> type | None:
    """Create a Pydantic model from a function's signature for FastAPI body typing.

    Returns None for zero-param functions or on failure (caller uses ``or dict``).
    """
    try:
        sig = inspect.signature(func)
        hints = get_type_hints(func)
    except (ValueError, TypeError):
        return None

    _SKIP_KINDS = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    fields: dict[str, Any] = {}
    for param_name, param in sig.parameters.items():
        if param_name == "self" or param.kind in _SKIP_KINDS:
            continue
        annotation = hints.get(param_name, Any)
        # Exclude bytes params -- they become File() uploads, not JSON fields
        if annotation is bytes:
            continue
        if param.default is not inspect.Parameter.empty:
            fields[param_name] = (annotation, param.default)
        else:
            fields[param_name] = (annotation, ...)

    if not fields:
        return None

    return create_model(name, **fields)


async def call_with_body(func, body):
    """Call func with body kwargs, handling Pydantic models and dicts."""
    if hasattr(body, "model_dump"):
        return await func(**body.model_dump())
    raw = body.get("input", body) if isinstance(body, dict) else body
    kwargs = _map_body_to_params(func, raw)
    return await func(**kwargs)


def to_dict(body) -> dict:
    """Convert Pydantic model or dict to plain dict."""
    return body.model_dump() if hasattr(body, "model_dump") else body


async def lb_execute(resource_config, func, body: dict):
    """Dispatch an LB route to the deployed endpoint via LoadBalancerSlsStub.

    Provisions the endpoint via ResourceManager, maps the HTTP body to
    function kwargs, then dispatches through the stub's /execute path
    which serializes the function via cloudpickle to the remote container.

    Args:
        resource_config: The resource config object (e.g. LiveLoadBalancer instance).
        func: The @remote LB route handler function.
        body: Parsed request body (from FastAPI's automatic JSON parsing).
    """
    try:
        deployed = await _resource_manager.get_or_deploy_resource(resource_config)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to provision '{resource_config.name}': {e}",
        )

    stub = LoadBalancerSlsStub(deployed)
    kwargs = _map_body_to_params(func, body)

    routing = getattr(func, "__remote_config__", None)
    route_label = (
        f"{routing['method']} {routing['path']}"
        if routing and routing.get("method")
        else func.__name__
    )
    log.info(f"{resource_config} | {route_label}")

    try:
        result = await stub(func, None, None, False, **kwargs)
        log.info(f"{resource_config} | Execution complete")
        return result
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def has_file_params(func) -> bool:
    """Check if any function parameter is annotated as bytes (file upload)."""
    try:
        hints = get_type_hints(func)
    except (ValueError, TypeError):
        return False
    return any(ann is bytes for name, ann in hints.items() if name != "return")


_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def register_file_upload_lb_route(
    app, method, path, config_var, func, tag, summary, *, local=False
):
    """Register an LB route with File() and Form() params for multipart upload.

    Introspects the function signature, builds a wrapper with File(...) for
    bytes params and Form(...) for non-file/non-path params, then registers
    the route on the FastAPI app.

    When local=True, the wrapper calls the function directly instead of
    dispatching via lb_execute().
    """
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    path_param_names = set(_PATH_PARAM_RE.findall(path))

    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}

    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        ann = hints.get(pname, Any)

        if pname in path_param_names:
            params.append(
                inspect.Parameter(
                    pname, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=ann
                )
            )
        elif ann is bytes:
            default = (
                File(...)
                if param.default is inspect.Parameter.empty
                else File(param.default)
            )
            params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default,
                    annotation=bytes,
                )
            )
        else:
            default = (
                Form(...)
                if param.default is inspect.Parameter.empty
                else Form(param.default)
            )
            params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default,
                    annotation=ann,
                )
            )
        annotations[pname] = ann

    async def handler(**kwargs):
        if local:
            return await func(**kwargs)
        return await lb_execute(config_var, func, kwargs)

    handler.__signature__ = inspect.Signature(parameters=params)
    handler.__annotations__ = annotations
    handler.__name__ = func.__name__
    handler.__doc__ = func.__doc__

    getattr(app, method)(path, tags=[tag], summary=summary)(handler)
