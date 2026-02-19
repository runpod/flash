"""Helpers for the flash run dev server — loaded inside the generated server.py."""

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response

from runpod_flash.core.resources.base import DeployableResource
from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.core.utils.http import get_authenticated_httpx_client

_resource_manager = ResourceManager()


async def lb_proxy(
    resource_config: DeployableResource, path_prefix: str, request: Request
) -> Response:
    """Transparent HTTP proxy from flash run dev server to deployed LB endpoint.

    Uses ResourceManager.get_or_deploy_resource() to resolve the endpoint,
    which handles provisioning, name prefixing, and caching automatically.

    Args:
        resource_config: The resource config object (e.g. LiveLoadBalancer instance)
        path_prefix: URL prefix used by the dev server (e.g. "/api") — stripped before proxying
        request: The incoming FastAPI request to forward

    Returns:
        FastAPI Response with upstream status code and body

    Raises:
        HTTPException 503: Endpoint not deployed or has no ID
        HTTPException 504: Upstream request timed out
        HTTPException 502: Connection error reaching the upstream endpoint
    """
    try:
        deployed = await _resource_manager.get_or_deploy_resource(resource_config)
        endpoint_url = deployed.endpoint_url
    except ValueError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Endpoint '{resource_config.name}' not available: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to provision '{resource_config.name}': {e}",
        )

    target_path = request.url.path
    if path_prefix and target_path.startswith(path_prefix):
        target_path = target_path[len(path_prefix) :]
    if not target_path:
        target_path = "/"

    target_url = endpoint_url.rstrip("/") + target_path
    if request.url.query:
        target_url += "?" + request.url.query

    body = await request.body()
    skip_headers = {"host", "content-length", "transfer-encoding", "connection"}
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in skip_headers
    }

    try:
        async with get_authenticated_httpx_client(timeout=30.0) as client:
            resp = await client.request(
                request.method, target_url, content=body, headers=headers
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=f"Timeout proxying to '{resource_config.name}'.",
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Connection error proxying to '{resource_config.name}': {e}",
        )
