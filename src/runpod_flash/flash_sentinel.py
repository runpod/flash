"""flash sentinel HTTP transport for deployed endpoint resolution.

instead of resolving endpoint IDs locally, sends requests to a sentinel
URL with flash headers. ai-api resolves the real endpoint ID server-side
using the (app, environment, endpoint) tuple.

deployed endpoints use a plain-JSON protocol: the endpoint's generated
handler imports the user's function directly and calls it with the input
dict as kwargs. the sentinel maps positional args to named params via
inspect.signature and sends the result as the runsync input body.
"""

import base64
import inspect
import logging
import os
from typing import Any, Callable, Dict, Optional

import cloudpickle
import runpod

from .core.resources.constants import ENDPOINT_DOMAIN
from .core.utils import http as _http
from .protos.remote_execution import FunctionRequest

log = logging.getLogger(__name__)

FLASH_SENTINEL_ID = "flash"

# default timeout for sentinel requests. configurable via
# FLASH_SENTINEL_TIMEOUT env var (seconds).
DEFAULT_SENTINEL_TIMEOUT = 90


def _get_timeout(override: Optional[float] = None) -> float:
    """resolve the sentinel request timeout.

    uses the explicit override if provided, then FLASH_SENTINEL_TIMEOUT
    env var, then the default (90s).
    """
    if override is not None:
        return override
    env_val = os.environ.get("FLASH_SENTINEL_TIMEOUT")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return DEFAULT_SENTINEL_TIMEOUT


def _flash_headers(app: str, env: str, endpoint: str) -> Dict[str, str]:
    """build the flash resolution headers."""
    return {
        "X-Flash-App": app,
        "X-Flash-Environment": env,
        "X-Flash-Endpoint": endpoint,
    }


def _args_to_kwargs(func: Callable, args: tuple, kwargs: dict) -> Dict[str, Any]:
    """map positional args to named kwargs using the function's signature.

    skips 'self' and 'cls' parameters for bound/unbound methods.
    """
    sig = inspect.signature(func)
    params = [name for name in sig.parameters if name not in ("self", "cls")]
    body: Dict[str, Any] = {}
    for i, arg in enumerate(args):
        if i < len(params):
            body[params[i]] = arg
    body.update(kwargs)
    return body


async def _sentinel_qb_post(
    app: str,
    env: str,
    endpoint_name: str,
    payload: Dict[str, Any],
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """post a payload to the sentinel runsync URL and return the raw response dict."""
    url = f"{runpod.endpoint_url_base}/{FLASH_SENTINEL_ID}/runsync"
    headers = _flash_headers(app, env, endpoint_name)
    effective_timeout = _get_timeout(timeout)

    log.debug("sentinel QB -> %s/%s/%s", app, env, endpoint_name)

    try:
        async with _http.get_authenticated_httpx_client(
            timeout=effective_timeout
        ) as client:
            response = await client.post(url, json=payload, headers=headers)
    except Exception as exc:
        if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
            raise RuntimeError(
                f"request to endpoint '{endpoint_name}' timed out after "
                f"{effective_timeout}s. the endpoint may not be deployed or "
                f"the worker is still starting. deploy with 'flash deploy' "
                f"or increase timeout with FLASH_SENTINEL_TIMEOUT env var."
            ) from exc
        raise

    if response.status_code == 404:
        raise RuntimeError(
            f"endpoint '{endpoint_name}' not found in app '{app}' "
            f"environment '{env}'. deploy it first with 'flash deploy'."
        )
    response.raise_for_status()
    return response.json()


def _handle_sentinel_response(data: Dict[str, Any]) -> Any:
    """extract the result from a sentinel response or raise on failure.

    expects a RunPod runsync response with at least a "status" key.
    raises RuntimeError on FAILED status, error fields, or unexpected
    response shapes.
    """
    if data.get("status") == "FAILED" or data.get("error"):
        err = data.get("error") or data.get("output", {}).get("error", "unknown")
        raise RuntimeError(f"remote execution failed: {err}")

    if "output" not in data and "status" not in data:
        raise RuntimeError(
            f"unexpected response from sentinel (no 'output' or 'status' key): {data}"
        )

    output = data.get("output", data)

    # deployed handlers return {"error": "..."} on exception
    if isinstance(output, dict) and "error" in output:
        raise RuntimeError(f"remote execution failed: {output['error']}")

    return output


async def sentinel_qb_execute(
    app: str,
    env: str,
    endpoint_name: str,
    func: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """execute a function on a deployed QB endpoint via flash sentinel.

    maps positional args to named params using the function's signature
    and sends the merged kwargs as the runsync input body.

    args:
        app: flash app name
        env: flash environment name
        endpoint_name: target endpoint name (resource config name)
        func: function being called (used only for signature introspection)
        *args: positional arguments to the function
        **kwargs: keyword arguments to the function

    returns:
        the deserialized function result (plain JSON)

    raises:
        RuntimeError: if remote execution fails
    """
    body = _args_to_kwargs(func, args, kwargs)
    # runpod strips empty input dicts from jobs, which breaks the worker's
    # job polling ("Job has missing field(s): id or input."). always include
    # at least one field so the input dict is preserved.
    if not body:
        body = {"__empty": True}
    payload = {"input": body}

    data = await _sentinel_qb_post(app, env, endpoint_name, payload)
    return _handle_sentinel_response(data)


def _decode_arg(value: Any) -> Any:
    """decode a cloudpickle+base64 argument back to its python value."""
    if isinstance(value, str):
        try:
            return cloudpickle.loads(base64.b64decode(value))
        except Exception:
            return value
    return value


async def sentinel_qb_class_execute(
    app: str,
    env: str,
    endpoint_name: str,
    request: FunctionRequest,
    timeout: Optional[float] = None,
    method_ref: Optional[Callable] = None,
) -> Any:
    """execute a method on a deployed class-based QB endpoint via flash sentinel.

    translates the cloudpickle-encoded FunctionRequest into the plain-JSON
    format expected by deployed class handlers. the deployed handler
    dispatches on a "method" key in the input and receives kwargs directly.

    when method_ref is provided, positional args are mapped to named params
    using the method's signature so the handler can unpack them as **kwargs.

    args:
        app: flash app name
        env: flash environment name
        endpoint_name: target endpoint name (resource config name)
        request: FunctionRequest with execution_type="class" and method info
        timeout: request timeout in seconds
        method_ref: optional reference to the method for signature introspection

    returns:
        the deserialized method result

    raises:
        RuntimeError: if remote execution fails
    """
    body: Dict[str, Any] = {"method": request.method_name}

    # decode cloudpickle-encoded values
    decoded_kwargs = {}
    if request.kwargs:
        for k, v in request.kwargs.items():
            decoded_kwargs[k] = _decode_arg(v)

    decoded_args: list = []
    if request.args:
        decoded_args = [_decode_arg(a) for a in request.args]

    # map positional args to named params using the method signature
    if decoded_args and method_ref is not None:
        mapped = _args_to_kwargs(method_ref, tuple(decoded_args), decoded_kwargs)
        body.update(mapped)
    else:
        body.update(decoded_kwargs)
        if decoded_args:
            body["args"] = decoded_args

    if not body or (len(body) == 1 and "method" in body):
        body["__empty"] = True

    payload = {"input": body}

    data = await _sentinel_qb_post(app, env, endpoint_name, payload, timeout=timeout)
    return _handle_sentinel_response(data)


async def sentinel_lb_request(
    app: str,
    env: str,
    endpoint_name: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 60,
) -> Any:
    """make an HTTP request to a deployed LB endpoint via flash sentinel.

    args:
        app: flash app name
        env: flash environment name
        endpoint_name: target endpoint name (resource config name)
        method: HTTP method (GET, POST, etc.)
        path: URL path (e.g. /api/compute)
        body: optional JSON body
        timeout: request timeout in seconds

    returns:
        parsed JSON response
    """
    url = f"https://{FLASH_SENTINEL_ID}.{ENDPOINT_DOMAIN}{path}"
    headers = _flash_headers(app, env, endpoint_name)

    log.debug("sentinel LB -> %s %s/%s/%s%s", method, app, env, endpoint_name, path)

    try:
        async with _http.get_authenticated_httpx_client(timeout=timeout) as client:
            response = await client.request(method, url, json=body, headers=headers)
    except Exception as exc:
        if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
            raise RuntimeError(
                f"request to endpoint '{endpoint_name}' timed out after {timeout}s. "
                f"the endpoint may not be deployed or the worker is still starting. "
                f"deploy with 'flash deploy' or increase timeout with "
                f"FLASH_SENTINEL_TIMEOUT env var."
            ) from exc
        raise

    if response.status_code == 404:
        raise RuntimeError(
            f"endpoint '{endpoint_name}' not found in app '{app}' "
            f"environment '{env}'. deploy it first with 'flash deploy'."
        )
    response.raise_for_status()
    return response.json()
