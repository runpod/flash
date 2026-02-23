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

import asyncio
import inspect
import logging
import re
from typing import Any, Callable, Dict, get_type_hints

from fastapi import FastAPI, Request
from pydantic import BaseModel, create_model

from .api_key_context import clear_api_key, set_api_key

logger = logging.getLogger(__name__)

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def _make_input_model(
    name: str, func: Callable, exclude: set[str] | None = None
) -> type | None:
    """Create a Pydantic model from a function's signature for FastAPI body typing.

    Returns None for zero-param functions or on introspection failure.
    """
    exclude = exclude or set()
    try:
        sig = inspect.signature(func)
        hints = get_type_hints(func)
    except (ValueError, TypeError) as e:
        logger.warning(
            "Failed to introspect signature for %s: %s. "
            "Skipping input model generation.",
            name,
            e,
        )
        return None

    _SKIP_KINDS = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    fields: dict[str, Any] = {}
    for param_name, param in sig.parameters.items():
        if param_name == "self" or param_name in exclude or param.kind in _SKIP_KINDS:
            continue
        annotation = hints.get(param_name, Any)
        if param.default is not inspect.Parameter.empty:
            fields[param_name] = (annotation, param.default)
        else:
            fields[param_name] = (annotation, ...)

    if not fields:
        return None

    return create_model(name, **fields)


def _wrap_handler_with_body_model(handler: Callable, path: str) -> Callable:
    """Wrap a handler so FastAPI reads its parameters from the JSON body.

    If the handler already accepts a single Pydantic BaseModel parameter,
    or has no eligible body parameters, returns it unchanged.
    """
    try:
        sig = inspect.signature(handler)
        hints = get_type_hints(handler)
    except (ValueError, TypeError) as e:
        logger.warning(
            "Failed to introspect handler %s for body model wrapping: %s. "
            "Returning handler unwrapped.",
            getattr(handler, "__name__", "unknown"),
            e,
        )
        return handler

    path_params = set(_PATH_PARAM_RE.findall(path))

    # Check if any non-path param is already a Pydantic model
    _SKIP_KINDS = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    for pname, param in sig.parameters.items():
        if pname in path_params or pname == "self" or param.kind in _SKIP_KINDS:
            continue
        annotation = hints.get(pname, Any)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return handler

    model_name = handler.__name__.title().replace("_", "") + "Body"
    model = _make_input_model(model_name, handler, exclude=path_params)
    if model is None:
        return handler

    is_async = asyncio.iscoroutinefunction(handler)

    if path_params:
        if is_async:

            async def wrapped_with_path(body, **kwargs):  # type: ignore[valid-type]
                return await handler(**body.model_dump(), **kwargs)
        else:

            def wrapped_with_path(body, **kwargs):  # type: ignore[valid-type]
                return handler(**body.model_dump(), **kwargs)

        # Build explicit signature so FastAPI maps path params correctly
        params = [
            inspect.Parameter(
                "body", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=model
            )
        ]
        annotations = {"body": model}
        for pname in path_params:
            if pname in sig.parameters:
                ann = hints.get(pname, Any)
                params.append(
                    inspect.Parameter(
                        pname, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=ann
                    )
                )
                annotations[pname] = ann
        wrapped_with_path.__signature__ = inspect.Signature(parameters=params)
        wrapped_with_path.__annotations__ = annotations
        return wrapped_with_path
    else:
        if is_async:

            async def wrapped(body: model):  # type: ignore[valid-type]
                return await handler(**body.model_dump())
        else:

            def wrapped(body: model):  # type: ignore[valid-type]
                return handler(**body.model_dump())

        return wrapped


async def extract_api_key_middleware(request: Request, call_next):
    """Extract API key from Authorization header and set in context.

    This middleware extracts the Bearer token from the Authorization header
    and makes it available to downstream code via context variables. This
    enables load-balanced endpoints to propagate API keys to worker endpoints.

    Args:
        request: Incoming FastAPI request
        call_next: Next middleware in chain

    Returns:
        Response from downstream handlers
    """
    # Extract API key from Authorization header
    auth_header = request.headers.get("Authorization", "")
    api_key = None
    token = None

    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:].strip()  # Remove "Bearer " prefix and trim whitespace
        token = set_api_key(api_key)
        logger.debug("Extracted API key from Authorization header")

    try:
        response = await call_next(request)
        return response
    finally:
        # Clean up context after request
        if token is not None:
            clear_api_key(token)


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
        from .serialization import deserialize_args, deserialize_kwargs, serialize_arg

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

        if method_upper in _BODY_METHODS:
            handler = _wrap_handler_with_body_model(handler, path)

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
