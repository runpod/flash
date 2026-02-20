"""Helpers for the flash run dev server — loaded inside the generated server.py."""

import inspect
from typing import Any, get_type_hints

from fastapi import HTTPException
from pydantic import create_model

from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub

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

    try:
        return await stub(func, None, None, False, **kwargs)
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
