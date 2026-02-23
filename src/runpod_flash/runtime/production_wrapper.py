"""Production wrapper for cross-endpoint function routing."""

import inspect
import logging
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

import httpx

from runpod_flash.core.resources.serverless import ServerlessResource
from runpod_flash.core.utils.http import get_authenticated_httpx_client

from .exceptions import RemoteExecutionError
from .service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


class ProductionWrapper:
    """Wrapper that routes function execution between endpoints.

    Intercepts stub execution and determines if the call is local (execute
    directly) or remote (call via HTTP to another endpoint).
    """

    def __init__(self, service_registry: ServiceRegistry):
        """Initialize production wrapper.

        Args:
            service_registry: Service registry for routing decisions.
        """
        self.service_registry = service_registry

    async def wrap_function_execution(
        self,
        original_stub_func: Callable,
        func: Callable,
        dependencies: Optional[list],
        system_dependencies: Optional[list],
        accelerate_downloads: bool,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Route function execution to local or remote endpoint.

        Args:
            original_stub_func: The original stubbed_resource function.
            func: The decorated function being called.
            dependencies: Pip dependencies (for local execution).
            system_dependencies: System dependencies (for local execution).
            accelerate_downloads: Download acceleration flag (for local).
            *args: Function positional arguments.
            **kwargs: Function keyword arguments.

        Returns:
            Function execution result.

        Raises:
            Exception: If execution fails.
        """
        function_name = func.__name__

        # Determine routing via manifest
        try:
            routing_info = await self.service_registry.get_routing_info(function_name)
        except ValueError as e:
            # Function not in manifest, execute locally
            logger.debug(
                f"Function {function_name} not in manifest: {e}, executing locally"
            )
            return await original_stub_func(
                func,
                dependencies,
                system_dependencies,
                accelerate_downloads,
                *args,
                **kwargs,
            )

        # Local execution
        if routing_info is None:
            logger.debug(f"Executing local function: {function_name}")
            return await original_stub_func(
                func,
                dependencies,
                system_dependencies,
                accelerate_downloads,
                *args,
                **kwargs,
            )

        # Remote execution -- dispatch based on QB vs LB target
        logger.debug(f"Routing function {function_name} to remote endpoint")

        if routing_info["is_load_balanced"]:
            return await self._execute_remote_lb(
                endpoint_url=routing_info["endpoint_url"],
                http_method=routing_info.get("http_method", "POST"),
                http_path=routing_info.get("http_path", "/"),
                args=args,
                kwargs=kwargs,
                function_name=function_name,
            )

        return await self._execute_remote_qb(
            routing_info=routing_info,
            func=func,
            args=args,
            kwargs=kwargs,
        )

    async def wrap_class_method_execution(
        self,
        original_method_func: Callable,
        request: Any,
    ) -> Any:
        """Route class method execution to local or remote endpoint.

        Args:
            original_method_func: The original execute_class_method function.
            request: FunctionRequest containing class and method info.

        Returns:
            Method execution result.

        Raises:
            Exception: If execution fails.
        """
        class_name = getattr(request, "class_name", None)

        if not class_name:
            return await original_method_func(request)

        # Determine routing
        try:
            routing_info = await self.service_registry.get_routing_info(class_name)
        except ValueError:
            logger.debug(f"Class {class_name} not in manifest, executing locally")
            return await original_method_func(request)

        if routing_info is None:
            logger.debug(f"Executing local class method: {class_name}")
            return await original_method_func(request)

        # Remote execution -- classes are always QB targets
        logger.debug(f"Routing class {class_name} to remote endpoint")
        payload = self._build_class_payload(request)
        return await self._execute_remote_qb_raw(
            routing_info=routing_info,
            payload=payload["input"],
        )

    async def _execute_remote_qb(
        self,
        routing_info: dict,
        func: Callable,
        args: tuple,
        kwargs: dict,
    ) -> Any:
        """Execute function on remote QB endpoint with plain JSON.

        Maps positional args to keyword args using the function's signature,
        then sends as plain JSON kwargs via runsync.

        Args:
            routing_info: Routing metadata from get_routing_info().
            func: The decorated function (used for signature introspection).
            args: Positional arguments.
            kwargs: Keyword arguments.

        Returns:
            Execution result.

        Raises:
            RemoteExecutionError: If remote execution fails.
        """
        # Map positional args to named kwargs using function signature
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        body: dict[str, Any] = {}
        for i, arg in enumerate(args):
            if i < len(params):
                body[params[i]] = arg
        body.update(kwargs)

        return await self._execute_remote_qb_raw(
            routing_info=routing_info,
            payload=body,
        )

    async def _execute_remote_qb_raw(
        self,
        routing_info: dict,
        payload: dict,
    ) -> Any:
        """Send a pre-built payload to a remote QB endpoint.

        Args:
            routing_info: Routing metadata from get_routing_info().
            payload: The dict to send as {"input": payload}.

        Returns:
            Execution result.

        Raises:
            RemoteExecutionError: If remote execution fails.
        """
        endpoint_url = routing_info.get("endpoint_url")
        resource_name = routing_info.get("resource_name", "unknown")

        if not endpoint_url:
            raise RemoteExecutionError(
                f"No endpoint URL for resource '{resource_name}'"
            )

        # Extract endpoint ID from URL
        parsed = urlparse(endpoint_url)
        path_parts = parsed.path.rstrip("/").split("/")
        endpoint_id = path_parts[-1] if path_parts else ""

        if not endpoint_id:
            raise RemoteExecutionError(f"Invalid endpoint URL format: {endpoint_url}")

        resource = ServerlessResource(name=f"remote_{resource_name}")
        resource.id = endpoint_id

        result = await resource.runsync({"input": payload})

        if result.error:
            raise RemoteExecutionError(
                f"Remote execution on '{resource_name}' failed: {result.error}"
            )

        return result.output

    async def _execute_remote_lb(
        self,
        endpoint_url: str,
        http_method: str,
        http_path: str,
        args: tuple,
        kwargs: dict,
        function_name: str,
    ) -> Any:
        """Execute function on remote LB endpoint via direct HTTP.

        Sends plain JSON body to the endpoint's HTTP route.

        Args:
            endpoint_url: Base URL of the LB endpoint.
            http_method: HTTP method (GET, POST, etc.).
            http_path: Path on the endpoint (e.g., /api/process).
            args: Positional arguments (sent as "args" key if non-empty).
            kwargs: Keyword arguments (merged into body).
            function_name: For error messages.

        Returns:
            Parsed JSON response.

        Raises:
            RemoteExecutionError: If HTTP call fails.
        """
        if not endpoint_url:
            raise RemoteExecutionError(
                f"No endpoint URL for LB function '{function_name}'"
            )

        url = f"{endpoint_url.rstrip('/')}{http_path}"
        body: dict[str, Any] = {}
        if args:
            body["args"] = list(args)
        body.update(kwargs)

        try:
            async with get_authenticated_httpx_client() as client:
                response = await client.request(
                    http_method, url, json=body if body else None
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            response_body = e.response.text[:500] if e.response else "no response body"
            raise RemoteExecutionError(
                f"Remote LB call to {function_name} ({http_method} {url}) "
                f"returned {e.response.status_code}: {response_body}"
            ) from e
        except httpx.TimeoutException as e:
            raise RemoteExecutionError(
                f"Remote LB call to {function_name} ({http_method} {url}) timed out: {e}"
            ) from e
        except Exception as e:
            raise RemoteExecutionError(
                f"Remote LB call to {function_name} ({http_method} {url}) failed: {e}"
            ) from e

    def _build_class_payload(self, request: Any) -> Dict[str, Any]:
        """Build payload from FunctionRequest for class execution.

        Args:
            request: FunctionRequest object.

        Returns:
            RunPod-format payload dict.
        """
        # Extract request data - handle both dict and object access patterns
        if isinstance(request, dict):
            data = request
        else:
            data = (
                request.model_dump(exclude_none=True)
                if hasattr(request, "model_dump")
                else {}
            )

        # Extract class execution data
        payload = {
            "input": {
                "function_name": data.get("class_name"),
                "execution_type": "class",
                "args": data.get("args", []),
                "kwargs": data.get("kwargs", {}),
                "method_name": data.get("method_name"),
            }
        }

        return payload


# Singleton instance management
_wrapper_instance: Optional[ProductionWrapper] = None


def create_production_wrapper(
    service_registry: Optional[ServiceRegistry] = None,
) -> ProductionWrapper:
    """Create or get singleton ProductionWrapper instance.

    Args:
        service_registry: Service registry. Creates if not provided.

    Returns:
        ProductionWrapper instance.
    """
    global _wrapper_instance

    if _wrapper_instance is None:
        # Create components if not provided
        if service_registry is None:
            service_registry = ServiceRegistry()

        _wrapper_instance = ProductionWrapper(service_registry)

    return _wrapper_instance


def reset_wrapper() -> None:
    """Reset singleton wrapper (mainly for testing)."""
    global _wrapper_instance
    _wrapper_instance = None
