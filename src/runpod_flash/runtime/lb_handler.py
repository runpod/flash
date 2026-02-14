"""Factory for creating FastAPI load-balanced handlers.

This module provides the factory function for generating FastAPI applications
that handle load-balanced serverless endpoints. It supports:
- User-defined HTTP routes
- /execute endpoint for @remote function execution (LiveLoadBalancer only)

Security Model:
    The /execute endpoint accepts and executes serialized function code. This is
    secure because:
    1. The function code originates from the client's @remote decorator
    2. The client (user) controls what function gets sent
    3. This mirrors the trusted client model of LiveServerlessStub
    4. In production, API authentication should protect the /execute endpoint

    Users should NOT expose the /execute endpoint to untrusted clients.
"""

import inspect
import logging
from typing import Any, Callable, Dict

from fastapi import FastAPI, Request

from .api_key_context import clear_api_key, set_api_key
from .serialization import (
    deserialize_args,
    deserialize_kwargs,
    serialize_arg,
)

logger = logging.getLogger(__name__)


async def extract_api_key_middleware(request: Request, call_next):
    """Extract API key from Authorization header and set in context.

    This middleware extracts the Bearer token from the Authorization header
    and makes it available to downstream code via context variables and request state.
    This enables mothership endpoints to propagate API keys to worker endpoints and
    State Manager queries.

    The API key is stored in both:
    1. contextvars for async functions that respect context propagation
    2. request.state for explicit access to per-request API key

    Args:
        request: Incoming FastAPI request
        call_next: Next middleware in chain

    Returns:
        Response from downstream handlers

    Raises:
        Any exceptions from downstream handlers are re-raised
    """
    # Extract API key from Authorization header
    auth_header = request.headers.get("Authorization", "")
    api_key = None
    token = None

    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:].strip()
        token = set_api_key(api_key)
        request.state.api_key = api_key
        logger.debug("Extracted API key from Authorization header")
    else:
        # No Bearer token - request.state.api_key will be undefined
        # Downstream code should check hasattr(request.state, 'api_key')
        logger.debug(f"No Bearer token in Authorization header for {request.url.path}")

    try:
        response = await call_next(request)
        return response
    finally:
        # Clean up context after request
        if token is not None:
            clear_api_key(token)
            logger.debug("Cleared API key from context after request")


def create_lb_handler(
    route_registry: Dict[tuple[str, str], Callable],
    include_execute: bool = False,
    lifespan: Callable = None,
) -> FastAPI:
    """Create FastAPI app with routes from registry.

    Args:
        route_registry: Mapping of (HTTP_METHOD, path) -> handler_function
                       Example: {("GET", "/api/health"): health_check}
        include_execute: Whether to register /execute endpoint for @remote execution.
                        Only used for LiveLoadBalancer (local development).
                        Deployed endpoints should not expose /execute for security.
        lifespan: Optional lifespan context manager for startup/shutdown hooks.

    Returns:
        Configured FastAPI application with routes registered.
    """
    app = FastAPI(title="Flash Load-Balanced Handler", lifespan=lifespan)

    # Add API key extraction middleware
    app.middleware("http")(extract_api_key_middleware)

    # Register /execute endpoint for @remote stub execution (if enabled)
    if include_execute:

        @app.post("/execute")
        async def execute_remote_function(request: Request) -> Dict[str, Any]:
            """Framework endpoint for @remote decorator execution.

            WARNING: This endpoint is INTERNAL to the Flash framework. It should only be
            called by the @remote stub from runpod_flash.stubs.load_balancer_sls. Exposing
            this endpoint to untrusted clients could allow arbitrary code execution.

            Accepts serialized function code and arguments, executes them,
            and returns serialized result.

            Request body:
                {
                    "function_name": "process_data",
                    "function_code": "def process_data(x, y): return x + y",
                    "args": [base64_encoded_arg1, base64_encoded_arg2],
                    "kwargs": {"key": base64_encoded_value}
                }

            Returns:
                {
                    "success": true,
                    "result": base64_encoded_result
                }
                or
                {
                    "success": false,
                    "error": "error message"
                }
            """
            try:
                body = await request.json()
            except Exception as e:
                logger.error(f"Failed to parse request body: {e}")
                return {"success": False, "error": f"Invalid request body: {e}"}

            try:
                # Extract function metadata
                function_name = body.get("function_name")
                function_code = body.get("function_code")

                if not function_name or not function_code:
                    return {
                        "success": False,
                        "error": "Missing function_name or function_code in request",
                    }

                # Deserialize arguments
                try:
                    args = deserialize_args(body.get("args", []))
                    kwargs = deserialize_kwargs(body.get("kwargs", {}))
                except Exception as e:
                    logger.error(f"Failed to deserialize arguments: {e}")
                    return {
                        "success": False,
                        "error": f"Failed to deserialize arguments: {e}",
                    }

                # Execute function in isolated namespace
                namespace: Dict[str, Any] = {}
                try:
                    exec(function_code, namespace)
                except SyntaxError as e:
                    logger.error(f"Syntax error in function code: {e}")
                    return {
                        "success": False,
                        "error": f"Syntax error in function code: {e}",
                    }
                except Exception as e:
                    logger.error(f"Error executing function code: {e}")
                    return {
                        "success": False,
                        "error": f"Error executing function code: {e}",
                    }

                # Get function from namespace
                if function_name not in namespace:
                    return {
                        "success": False,
                        "error": f"Function '{function_name}' not found in executed code",
                    }

                func = namespace[function_name]

                # Execute function
                try:
                    result = func(*args, **kwargs)

                    # Handle async functions
                    if inspect.iscoroutine(result):
                        result = await result
                except Exception as e:
                    logger.error(f"Function execution failed: {e}")
                    return {
                        "success": False,
                        "error": f"Function execution failed: {e}",
                    }

                # Serialize result
                try:
                    result_b64 = serialize_arg(result)
                    return {"success": True, "result": result_b64}
                except Exception as e:
                    logger.error(f"Failed to serialize result: {e}")
                    return {
                        "success": False,
                        "error": f"Failed to serialize result: {e}",
                    }

            except Exception as e:
                logger.error(f"Unexpected error in /execute endpoint: {e}")
                return {"success": False, "error": f"Unexpected error: {e}"}

    # Register user-defined routes from registry
    for (method, path), handler in route_registry.items():
        method_upper = method.upper()

        if method_upper == "GET":
            app.get(path)(handler)
        elif method_upper == "POST":
            app.post(path)(handler)
        elif method_upper == "PUT":
            app.put(path)(handler)
        elif method_upper == "DELETE":
            app.delete(path)(handler)
        elif method_upper == "PATCH":
            app.patch(path)(handler)
        else:
            logger.warning(
                f"Unsupported HTTP method '{method}' for path '{path}'. Skipping."
            )

    return app
