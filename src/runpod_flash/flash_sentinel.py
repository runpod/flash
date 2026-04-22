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
from typing import Any, Callable, Dict, Optional

import cloudpickle
import runpod

from .core.resources.constants import ENDPOINT_DOMAIN
from .core.utils import http as _http
from .protos.remote_execution import FunctionRequest

log = logging.getLogger(__name__)

FLASH_SENTINEL_ID = "flash"


def _flash_headers(app: str, env: str, endpoint: str) -> Dict[str, str]:
    """build the flash resolution headers."""
    return {
        "X-Flash-App": app,
        "X-Flash-Environment": env,
        "X-Flash-Endpoint": endpoint,
    }


def _args_to_kwargs(func: Callable, args: tuple, kwargs: dict) -> Dict[str, Any]:
    """map positional args to named kwargs using the function's signature."""
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
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
    timeout: float = 300,
) -> Dict[str, Any]:
    """post a payload to the sentinel runsync URL and return the raw response dict."""
    url = f"{runpod.endpoint_url_base}/{FLASH_SENTINEL_ID}/runsync"
    headers = _flash_headers(app, env, endpoint_name)

    log.debug("sentinel QB -> %s/%s/%s", app, env, endpoint_name)

    async with _http.get_authenticated_httpx_client(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code == 404:
            raise RuntimeError(
                f"endpoint '{endpoint_name}' not found in app '{app}' "
                f"environment '{env}'. deploy it first with 'flash deploy'."
            )
        response.raise_for_status()
        return response.json()


def _handle_sentinel_response(data: Dict[str, Any]) -> Any:
    """extract the result from a sentinel response or raise on failure."""
    if data.get("status") == "FAILED" or data.get("error"):
        err = data.get("error") or data.get("output", {}).get("error", "unknown")
        raise RuntimeError(f"remote execution failed: {err}")

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
    timeout: float = 60,
) -> Any:
    """execute a method on a deployed class-based QB endpoint via flash sentinel.

    translates the cloudpickle-encoded FunctionRequest into the plain-JSON
    format expected by deployed class handlers. the deployed handler
    dispatches on a "method" key in the input and receives kwargs directly.

    args:
        app: flash app name
        env: flash environment name
        endpoint_name: target endpoint name (resource config name)
        request: FunctionRequest with execution_type="class" and method info
        timeout: request timeout in seconds

    returns:
        the deserialized method result

    raises:
        RuntimeError: if remote execution fails
    """
    body: Dict[str, Any] = {"method": request.method_name}

    # decode cloudpickle-encoded kwargs back to plain python values
    if request.kwargs:
        for k, v in request.kwargs.items():
            body[k] = _decode_arg(v)

    # positional args are encoded as a list of cloudpickle blobs
    if request.args:
        body["args"] = [_decode_arg(a) for a in request.args]

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

    async with _http.get_authenticated_httpx_client(timeout=timeout) as client:
        response = await client.request(method, url, json=body, headers=headers)
        if response.status_code == 404:
            raise RuntimeError(
                f"endpoint '{endpoint_name}' not found in app '{app}' "
                f"environment '{env}'. deploy it first with 'flash deploy'."
            )
        response.raise_for_status()
        return response.json()
