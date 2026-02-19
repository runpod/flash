"""Helpers for the flash run dev server — loaded inside the generated server.py."""

from fastapi import HTTPException, Request

from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub

_resource_manager = ResourceManager()


async def lb_execute(resource_config, func, request: Request):
    """Execute LB function on deployed endpoint via LoadBalancerSlsStub.

    Uses the same /execute dispatch path that works on main — provisions
    the endpoint, serializes the function via cloudpickle, and POSTs to
    /execute on the deployed container.
    """
    try:
        deployed = await _resource_manager.get_or_deploy_resource(resource_config)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to provision '{resource_config.name}': {e}",
        )

    stub = LoadBalancerSlsStub(deployed)

    # Parse HTTP request into function kwargs
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            kwargs = await request.json()
            if not isinstance(kwargs, dict):
                kwargs = {"input": kwargs}
        except Exception:
            kwargs = {}
    else:
        kwargs = dict(request.query_params)

    try:
        return await stub(func, None, None, False, **kwargs)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
