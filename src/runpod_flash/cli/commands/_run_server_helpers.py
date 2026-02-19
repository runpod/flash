"""Helpers for the flash run dev server — loaded inside the generated server.py."""

import inspect

from fastapi import HTTPException

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
