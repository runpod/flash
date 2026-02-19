"""LoadBalancerSlsStub - Stub for load-balanced serverless execution.

Enables @remote decorator to work with LoadBalancerSlsResource endpoints
via direct HTTP calls instead of queue-based job submission.
"""

import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

import httpx

from runpod_flash.core.utils.http import get_authenticated_httpx_client
from runpod_flash.runtime.api_key_context import get_api_key
from runpod_flash.runtime.serialization import (
    deserialize_arg,
    serialize_args,
    serialize_kwargs,
)
from .live_serverless import get_function_source

log = logging.getLogger(__name__)


class LoadBalancerSlsStub:
    """HTTP-based stub for load-balanced serverless endpoint execution.

    Implements the stub interface for @remote decorator with LoadBalancerSlsResource,
    providing direct HTTP-based function execution instead of queue-based processing.

    Key differences from LiveServerlessStub:
    - Direct HTTP POST to /execute endpoint (not queue-based)
    - No job ID polling - synchronous HTTP response
    - Same function serialization pattern (cloudpickle + base64)
    - Lower latency but no automatic retries

    Architecture:
        1. User calls @remote decorated function
        2. Decorator dispatches to this stub via singledispatch
        3. Stub serializes function code and arguments
        4. Stub POSTs to endpoint /execute with serialized data
        5. Endpoint deserializes, executes, and returns result
        6. Stub deserializes result and returns to user

    Example:
        stub = LoadBalancerSlsStub(lb_resource)
        result = await stub(my_func, deps, sys_deps, accel, arg1, arg2)
    """

    DEFAULT_TIMEOUT = 30.0  # Default timeout in seconds

    def __init__(self, server: Any, timeout: Optional[float] = None) -> None:
        """Initialize stub with LoadBalancerSlsResource server.

        Args:
            server: LoadBalancerSlsResource instance with endpoint_url configured
            timeout: Request timeout in seconds (default: 30.0)
        """
        self.server = server
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT

    def _should_use_execute_endpoint(self, func: Callable[..., Any]) -> bool:
        """Determine if /execute endpoint should be used for this function.

        The /execute endpoint (which accepts arbitrary function code) is only used for:
        - LiveLoadBalancer (local development)
        - Functions without routing metadata (backward compatibility)

        For deployed LoadBalancerSlsResource endpoints with routing metadata,
        the stub translates @remote calls into HTTP requests to user-defined routes.

        Args:
            func: Function being called

        Returns:
            True if /execute should be used, False if user route should be used
        """
        from ..core.resources.live_serverless import LiveServerlessMixin

        # Always use /execute for live resources (local development)
        if isinstance(self.server, LiveServerlessMixin):
            log.debug(f"Using /execute endpoint for LiveLoadBalancer: {func.__name__}")
            return True

        # Check if function has routing metadata
        routing_config = getattr(func, "__remote_config__", None)
        if not routing_config:
            log.debug(f"No routing config for {func.__name__}, using /execute fallback")
            return True

        # Check if routing metadata is complete
        if not routing_config.get("method") or not routing_config.get("path"):
            log.debug(
                f"Incomplete routing config for {func.__name__}, using /execute fallback"
            )
            return True

        # Use user-defined route for deployed endpoints with complete routing metadata
        log.debug(
            f"Using user route for deployed endpoint: {func.__name__} "
            f"{routing_config['method']} {routing_config['path']}"
        )
        return False

    async def __call__(
        self,
        func: Callable[..., Any],
        dependencies: Optional[List[str]],
        system_dependencies: Optional[List[str]],
        accelerate_downloads: bool,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute function on load-balanced endpoint.

        Behavior depends on endpoint type:
        - LiveLoadBalancer: Uses /execute endpoint (local development)
        - Deployed LoadBalancerSlsResource: Uses user-defined route via HTTP

        Args:
            func: Function to execute
            dependencies: Pip dependencies required
            system_dependencies: System dependencies required
            accelerate_downloads: Whether to accelerate downloads
            *args: Function positional arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            Exception: If endpoint returns error or HTTP call fails
        """
        # Determine execution path based on resource type and routing metadata
        if self._should_use_execute_endpoint(func):
            # Local development or backward compatibility: use /execute endpoint
            request = self._prepare_request(
                func,
                dependencies,
                system_dependencies,
                accelerate_downloads,
                *args,
                **kwargs,
            )
            response = await self._execute_function(request)
            return self._handle_response(response)
        else:
            # Deployed endpoint: use user-defined route
            routing_config = func.__remote_config__
            return await self._execute_via_user_route(
                func,
                routing_config["method"],
                routing_config["path"],
                *args,
                **kwargs,
            )

    def _prepare_request(
        self,
        func: Callable[..., Any],
        dependencies: Optional[List[str]],
        system_dependencies: Optional[List[str]],
        accelerate_downloads: bool,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Prepare HTTP request payload.

        Extracts function source code and serializes arguments using cloudpickle.

        Args:
            func: Function to serialize
            dependencies: Pip dependencies
            system_dependencies: System dependencies
            accelerate_downloads: Download acceleration flag
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Request dictionary with serialized function and arguments
        """
        source, _ = get_function_source(func)
        log.debug(f"Extracted source for {func.__name__} ({len(source)} bytes)")

        request = {
            "function_name": func.__name__,
            "function_code": source,
            "dependencies": dependencies or [],
            "system_dependencies": system_dependencies or [],
            "accelerate_downloads": accelerate_downloads,
        }

        # Serialize arguments using cloudpickle + base64
        if args:
            request["args"] = serialize_args(args)
            log.debug(f"Serialized {len(args)} positional args for {func.__name__}")

        if kwargs:
            request["kwargs"] = serialize_kwargs(kwargs)
            log.debug(f"Serialized {len(kwargs)} keyword args for {func.__name__}")

        return request

    async def _execute_function(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Execute function via direct HTTP POST to endpoint.

        Posts serialized function and arguments to /execute endpoint.
        No job ID polling - waits for synchronous HTTP response.

        Args:
            request: Request dictionary with function_code, args, kwargs

        Returns:
            Response dictionary with success flag and result

        Raises:
            httpx.HTTPError: If HTTP request fails
            ValueError: If endpoint_url not available
        """
        if not self.server.endpoint_url:
            raise ValueError(
                "Endpoint URL not available - endpoint may not be deployed"
            )

        execute_url = f"{self.server.endpoint_url}/execute"

        try:
            # Get API key from context (if available) for propagation
            context_api_key = get_api_key()
            async with get_authenticated_httpx_client(
                timeout=self.timeout, api_key_override=context_api_key
            ) as client:
                response = await client.post(execute_url, json=request)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Execution timeout on {self.server.name} after {self.timeout}s: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            # Truncate response body to prevent huge error messages
            response_text = e.response.text
            if len(response_text) > 500:
                response_text = response_text[:500] + "... (truncated)"
            raise RuntimeError(
                f"HTTP error from endpoint {self.server.name}: "
                f"{e.response.status_code} - {response_text}"
            ) from e
        except httpx.RequestError as e:
            raise ConnectionError(
                f"Failed to connect to endpoint {self.server.name} ({execute_url}): {e}"
            ) from e

    async def _execute_via_user_route(
        self,
        func: Callable[..., Any],
        method: str,
        path: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute function by calling user-defined HTTP route.

        Maps function arguments to JSON request body and makes HTTP request
        to the user-defined route. The response is parsed as JSON and returned directly.

        Args:
            func: Function being called (used for signature inspection)
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            path: URL path (e.g., /api/process)
            *args: Function positional arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result (parsed from JSON response)

        Raises:
            ValueError: If endpoint_url not available
            TimeoutError: If request times out
            RuntimeError: If HTTP error occurs
            ConnectionError: If connection fails
        """
        if not self.server.endpoint_url:
            raise ValueError(
                "Endpoint URL not available - endpoint may not be deployed"
            )

        # Get function signature to map args to parameter names
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Map positional args to parameter names
        body = {}
        for i, arg in enumerate(args):
            if i < len(params):
                body[params[i]] = arg
        body.update(kwargs)

        # Construct full URL
        url = f"{self.server.endpoint_url}{path}"
        log.debug(f"Executing via user route: {method} {url}")

        try:
            # Get API key from context (if available) for propagation
            context_api_key = get_api_key()
            async with get_authenticated_httpx_client(
                timeout=self.timeout, api_key_override=context_api_key
            ) as client:
                response = await client.request(method, url, json=body)
                response.raise_for_status()
                result = response.json()
                log.debug(
                    f"User route execution successful (type={type(result).__name__})"
                )
                return result
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Execution timeout on {self.server.name} after {self.timeout}s: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            # Truncate response body to prevent huge error messages
            response_text = e.response.text
            if len(response_text) > 500:
                response_text = response_text[:500] + "... (truncated)"
            raise RuntimeError(
                f"HTTP error from endpoint {self.server.name}: "
                f"{e.response.status_code} - {response_text}"
            ) from e
        except httpx.RequestError as e:
            raise ConnectionError(
                f"Failed to connect to endpoint {self.server.name} ({url}): {e}"
            ) from e

    def _handle_response(self, response: Dict[str, Any]) -> Any:
        """Deserialize and validate response.

        Args:
            response: Response dictionary from endpoint

        Returns:
            Deserialized function result

        Raises:
            ValueError: If response format is invalid
            Exception: If response indicates error
        """
        if not isinstance(response, dict):
            raise ValueError(f"Invalid response type: {type(response)}")

        if response.get("success"):
            result_b64 = response.get("result")
            if result_b64 is None:
                raise ValueError("Response marked success but result is None")

            try:
                result = deserialize_arg(result_b64)
                log.debug(
                    f"Successfully deserialized response result (type={type(result).__name__})"
                )
                return result
            except Exception as e:
                raise ValueError(f"Failed to deserialize result: {e}") from e
        else:
            error = response.get("error", "Unknown error")
            log.warning(f"Remote execution failed: {error}")
            raise Exception(f"Remote execution failed: {error}")
