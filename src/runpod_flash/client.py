import os
import inspect
import logging
from functools import wraps
from typing import Any, List, Optional

from .core.resources import LoadBalancerSlsResource, ResourceManager, ServerlessResource
from .execute_class import create_remote_class
from .stubs import stub_resource

log = logging.getLogger(__name__)


def _should_execute_locally(func_name: str) -> bool:
    """Determine if a @remote function should execute locally or create a stub.

    Uses build-time generated configuration to make this decision.

    Args:
        func_name: Name of the function being decorated

    Returns:
        True if function should execute locally, False if stub should be created
    """
    # Check if we're in a deployed environment
    runpod_endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID")
    runpod_pod_id = os.getenv("RUNPOD_POD_ID")

    if not runpod_endpoint_id and not runpod_pod_id:
        # Local development - create stub for remote execution via ResourceManager
        return False

    # In deployed environment - check build-time generated configuration
    try:
        from .runtime._flash_resource_config import is_local_function

        result = is_local_function(func_name)
        return result
    except ImportError as e:
        # Configuration not generated (shouldn't happen in deployed env)
        # Fall back to safe default: execute locally
        log.warning(
            f"Resource configuration import failed for {func_name}: {e}, defaulting to local execution"
        )
        return True


_service_registry: Any = None


async def _resolve_deployed_endpoint_id(func_name: str) -> Optional[str]:
    """Look up pre-deployed endpoint ID for a function from the manifest.

    Only active in deployed environments (RUNPOD_ENDPOINT_ID or RUNPOD_POD_ID set).
    Returns None in local dev or on any failure, allowing fallback to ResourceManager.
    """
    global _service_registry

    if not os.getenv("RUNPOD_ENDPOINT_ID") and not os.getenv("RUNPOD_POD_ID"):
        return None

    try:
        from .runtime.service_registry import ServiceRegistry

        if _service_registry is None:
            _service_registry = ServiceRegistry()

        endpoint_url = await _service_registry.get_endpoint_for_function(func_name)
        if not endpoint_url:
            return None

        from urllib.parse import urlparse

        path_parts = urlparse(endpoint_url).path.rstrip("/").split("/")
        endpoint_id = path_parts[-1] if path_parts else ""
        if not endpoint_id:
            log.warning(f"Could not extract endpoint ID from URL: {endpoint_url}")
            return None

        log.debug(f"Resolved {func_name} to deployed endpoint {endpoint_id}")
        return endpoint_id

    except ImportError:
        log.debug("ServiceRegistry not available, skipping manifest lookup")
        return None
    except ValueError as e:
        log.debug(f"Function {func_name} not in manifest: {e}")
        return None
    except Exception as e:
        log.error(
            f"Manifest lookup failed for {func_name}, falling back to "
            f"ResourceManager (may trigger dynamic provisioning): {e}",
            exc_info=True,
        )
        return None


def remote(
    resource_config: ServerlessResource,
    dependencies: Optional[List[str]] = None,
    system_dependencies: Optional[List[str]] = None,
    accelerate_downloads: bool = True,
    local: bool = False,
    method: Optional[str] = None,
    path: Optional[str] = None,
    **extra,
):
    """
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
        extra (dict, optional): Additional parameters for the execution of the resource. Defaults to an empty dict.

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
            return func_or_class

        # Determine if we should execute locally or create a stub
        # Uses build-time generated configuration in deployed environments
        func_name = (
            func_or_class.__name__
            if not inspect.isclass(func_or_class)
            else func_or_class.__name__
        )
        should_execute_local = _should_execute_locally(func_name)

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
                extra,
            )
            wrapped_class.__remote_config__ = routing_config
            return wrapped_class
        else:
            # Handle function decoration
            @wraps(func_or_class)
            async def wrapper(*args, **kwargs):
                endpoint_id = await _resolve_deployed_endpoint_id(func_name)
                if endpoint_id:
                    remote_resource = resource_config.model_copy(
                        update={"id": endpoint_id}
                    )
                else:
                    resource_manager = ResourceManager()
                    remote_resource = await resource_manager.get_or_deploy_resource(
                        resource_config
                    )

                stub = stub_resource(remote_resource, **extra)
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
