import difflib
import inspect
import logging
import os
from functools import wraps
from typing import Any, List, Optional

from .core.resources import LoadBalancerSlsResource, ResourceManager, ServerlessResource
from .execute_class import create_remote_class
from .flash_context import get_flash_context
from .flash_sentinel import sentinel_qb_execute
from .stubs import stub_resource

log = logging.getLogger(__name__)


def _normalize_resource_name(name: str) -> str:
    """strip live- prefix and -fb suffix for resource name comparison."""
    if name.startswith("live-"):
        name = name[5:]
    if name.endswith("-fb"):
        name = name[:-3]
    return name




def _should_execute_locally(resource_config: ServerlessResource) -> bool:
    """determine if a @remote function should execute locally.

    on a deployed worker, compares the resource config name to
    FLASH_RESOURCE_NAME to decide if this function belongs to
    the current worker.

    returns False in local dev (not deployed) so a stub is created.
    """
    if not os.getenv("RUNPOD_ENDPOINT_ID") and not os.getenv("RUNPOD_POD_ID"):
        return False

    current = os.getenv("FLASH_RESOURCE_NAME")
    if not current:
        return True  # deployed but unknown resource, safe default

    return _normalize_resource_name(resource_config.name) == _normalize_resource_name(
        current
    )


def _reject_unknown_kwargs(extra: dict[str, Any], known: set[str]) -> None:
    """Raise TypeError for unknown kwargs with 'did you mean?' suggestions."""
    names = sorted(extra)
    parts: list[str] = []
    for name in names:
        close = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.6)
        hint = f" (Did you mean '{close[0]}'?)" if close else ""
        parts.append(f"'{name}'{hint}")

    noun = "argument" if len(names) == 1 else "arguments"
    raise TypeError(f"remote() got unknown keyword {noun}: {', '.join(parts)}")


def remote(
    resource_config: ServerlessResource,
    dependencies: Optional[List[str]] = None,
    system_dependencies: Optional[List[str]] = None,
    accelerate_downloads: bool = True,
    local: bool = False,
    method: Optional[str] = None,
    path: Optional[str] = None,
    _internal: bool = False,
    # **extra is retained (rather than removing it and relying on Python's own
    # TypeError) so we can provide "did you mean?" suggestions for typos.
    **extra,
):
    """
    .. deprecated::
        Use :class:`runpod_flash.Endpoint` instead.

    Decorator to enable dynamic resource provisioning and dependency management for serverless functions.

    This decorator allows a function to be executed in a remote serverless environment, with support for
    dynamic resource provisioning and installation of required dependencies. It can also bypass remote
    execution entirely for local testing.

    Supports both sync and async function definitions:
    - `def my_function(...)` - Regular synchronous function
    - `async def my_function(...)` - Asynchronous function

    In both cases, the decorated function returns an awaitable that must be called with `await`.

    Args:
        resource_config (ServerlessResource): Configuration object specifying the serverless resource
            to be provisioned or used. Not used when local=True.
        dependencies (List[str], optional): A list of pip package names to be installed in the remote
            environment before executing the function. Not used when local=True. Defaults to None.
        system_dependencies (List[str], optional): A list of system packages to be installed in the remote
            environment before executing the function. Not used when local=True. Defaults to None.
        accelerate_downloads (bool, optional): Enable download acceleration for dependencies and models.
            Only applies to remote execution. Defaults to True.
        local (bool, optional): Execute function/class locally instead of provisioning remote servers.
            Returns the unwrapped function/class for direct local execution. Users must ensure all required
            dependencies are already installed in their local environment. Defaults to False.
        method (str, optional): HTTP method for load-balanced endpoints (LoadBalancerSlsResource).
            Required for LoadBalancerSlsResource: "GET", "POST", "PUT", "DELETE", "PATCH".
            Ignored for queue-based endpoints. Defaults to None.
        path (str, optional): HTTP path for load-balanced endpoints (LoadBalancerSlsResource).
            Required for LoadBalancerSlsResource. Must start with "/". Example: "/api/process".
            Ignored for queue-based endpoints. Defaults to None.
        _internal (bool, optional): suppress deprecation warning when called from
            Endpoint internals. not part of the public API. Defaults to False.

    Returns:
        Callable: A decorator that wraps the target function, enabling remote execution with the specified
        resource configuration and dependencies, or returns the unwrapped function/class for local execution.

    Example:
    ```python
        # Queue-based endpoint (recommended for reliability)
        @remote(
            resource_config=LiveServerless(name="gpu_worker"),
            dependencies=["torch>=2.0.0"],
        )
        async def gpu_task(data: dict) -> dict:
            import torch
            # GPU processing here
            return {"result": "processed"}

        # Load-balanced endpoint (for low-latency APIs)
        @remote(
            resource_config=LoadBalancerSlsResource(name="api-service"),
            method="POST",
            path="/api/process",
        )
        async def api_endpoint(x: int, y: int) -> dict:
            return {"result": x + y}

        # Local execution (testing/development)
        @remote(
            resource_config=my_resource_config,
            dependencies=["numpy", "pandas"],
            local=True,
        )
        async def my_test_function(data):
            # Runs locally - dependencies must be pre-installed
            pass
    ```
    """
    if extra:
        _reject_unknown_kwargs(extra, _REMOTE_KNOWN_KWARGS)

    if not _internal:
        import warnings

        warnings.warn(
            "runpod_flash.remote is deprecated. Use runpod_flash.Endpoint instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    def decorator(func_or_class):
        # Validate HTTP routing parameters for LoadBalancerSlsResource
        is_lb_resource = isinstance(resource_config, LoadBalancerSlsResource)

        if is_lb_resource:
            if not method or not path:
                raise ValueError(
                    f"LoadBalancerSlsResource requires both 'method' and 'path' parameters. "
                    f"Got method={method}, path={path}. "
                    f"Example: @remote(resource_config, method='POST', path='/api/process')"
                )
            if not path.startswith("/"):
                raise ValueError(f"path must start with '/'. Got: {path}")
            valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH"}
            if method not in valid_methods:
                raise ValueError(
                    f"method must be one of {valid_methods}. Got: {method}"
                )
        elif method or path:
            log.warning(
                f"HTTP routing parameters (method={method}, path={path}) are only used "
                f"with LoadBalancerSlsResource, but resource_config is {type(resource_config).__name__}. "
                f"They will be ignored."
            )

        # Store routing metadata for scanner and build system
        routing_config = {
            "resource_config": resource_config,
            "method": method,
            "path": path,
            "dependencies": dependencies,
            "system_dependencies": system_dependencies,
        }

        # LB route handler passthrough — return the function unwrapped.
        #
        # When @remote is applied to an LB resource (LiveLoadBalancer,
        # CpuLiveLoadBalancer, LoadBalancerSlsResource) with method= and path=,
        # the decorated function IS the HTTP route handler. Its body executes
        # directly on the LB endpoint server; it is not dispatched to a remote
        # process. QB @remote calls inside its body still use their own stubs.
        is_lb_route_handler = is_lb_resource and method is not None and path is not None
        if is_lb_route_handler:
            routing_config["is_lb_route_handler"] = True
            func_or_class.__remote_config__ = routing_config
            func_or_class.__is_lb_route_handler__ = True
            return func_or_class

        # Local execution mode - execute without provisioning remote servers
        if local:
            func_or_class.__remote_config__ = routing_config
            func_or_class.__flash_local__ = True
            return func_or_class

        # Determine if we should execute locally or create a stub
        # Uses build-time generated configuration in deployed environments
        should_execute_local = _should_execute_locally(resource_config)

        if should_execute_local:
            # This function belongs to our resource - execute locally
            func_or_class.__remote_config__ = routing_config
            return func_or_class

        # Remote execution mode - create stub for calling other endpoints

        if inspect.isclass(func_or_class):
            # Handle class decoration
            wrapped_class = create_remote_class(
                func_or_class,
                resource_config,
                dependencies,
                system_dependencies,
                accelerate_downloads,
            )
            wrapped_class.__remote_config__ = routing_config
            return wrapped_class
        else:
            # Handle function decoration
            @wraps(func_or_class)
            async def wrapper(*args, **kwargs):
                ctx = get_flash_context()
                if ctx:
                    # sentinel path: call deployed endpoint via flash headers
                    app_name, env_name = ctx
                    return await sentinel_qb_execute(
                        app_name,
                        env_name,
                        resource_config.name,
                        func_or_class,
                        *args,
                        **kwargs,
                    )

                # live path: provision ephemeral endpoint
                resource_manager = ResourceManager()
                remote_resource = await resource_manager.get_or_deploy_resource(
                    resource_config
                )

                stub = stub_resource(remote_resource)
                return await stub(
                    func_or_class,
                    dependencies,
                    system_dependencies,
                    accelerate_downloads,
                    *args,
                    **kwargs,
                )

            # Store routing metadata on wrapper for scanner
            wrapper.__remote_config__ = routing_config
            return wrapper

    return decorator


# Derived from remote()'s signature so it stays in sync automatically.
_REMOTE_KNOWN_KWARGS = {
    p.name
    for p in inspect.signature(remote).parameters.values()
    if p.kind != inspect.Parameter.VAR_KEYWORD
}
