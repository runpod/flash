"""sentinel dispatch on runpod.apps targets.

replaces runpod_flash.flash_sentinel QB/LB paths when the apps-dispatch
feature flag is on. resolution is server-side through the shared sentinel
(identical X-Flash-App/Environment/Endpoint contract), so these functions
only build the payload and unwrap the result.
"""

from typing import Any, Callable

from runpod.apps.targets import SentinelTarget, args_to_input

from .names import normalize_resource_name


async def apps_sentinel_qb_execute(
    app: str,
    env: str,
    resource: str,
    fn: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """dispatch a queue-based call through the apps sentinel target.

    maps positional args onto the function's parameter names (apps'
    args_to_input already substitutes {"__empty": True} for empty input),
    wraps as {"input": body}, and returns the unwrapped output.
    """
    body = args_to_input(fn, args, kwargs)
    target = SentinelTarget(app, env, normalize_resource_name(resource))
    return await target.invoke({"input": body})


async def apps_sentinel_lb_request(
    app: str,
    env: str,
    resource: str,
    method: str,
    path: str,
    body: Any = None,
    timeout: float = 60.0,
) -> Any:
    """dispatch a load-balanced HTTP call through the apps sentinel target."""
    target = SentinelTarget(app, env, normalize_resource_name(resource))
    return await target.request(method, path, body, timeout=timeout)
