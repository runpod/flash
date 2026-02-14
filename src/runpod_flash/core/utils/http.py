"""HTTP utilities for RunPod API communication."""

from typing import Optional

import httpx
import requests

from runpod_flash.core.credentials import get_api_key


def get_authenticated_httpx_client(
    timeout: Optional[float] = None,
    api_key_override: Optional[str] = None,
) -> httpx.AsyncClient:
    """Create httpx AsyncClient with RunPod authentication and User-Agent.

    Automatically includes:
    - User-Agent header identifying flash client and version
    - Authorization header if an api key is available

    This provides a centralized place to manage authentication headers for
    all RunPod HTTP requests, avoiding repetitive manual header addition.

    Args:
        timeout: Request timeout in seconds. Defaults to 30.0.
        api_key_override: Optional API key to use instead of RUNPOD_API_KEY env var.
                         Used for propagating API keys from load-balanced to worker endpoints.

    Returns:
        Configured httpx.AsyncClient with User-Agent and Authorization headers

    Example:
        async with get_authenticated_httpx_client() as client:
            response = await client.post(url, json=data)

        # With custom timeout
        async with get_authenticated_httpx_client(timeout=60.0) as client:
            response = await client.get(url)

        # With API key override (for propagation)
        async with get_authenticated_httpx_client(api_key_override=context_key) as client:
            response = await client.post(url, json=data)
    """
    from .user_agent import get_user_agent

    headers = {
        "User-Agent": get_user_agent(),
        "Content-Type": "application/json",
    }
    api_key = api_key_override or get_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout_config = timeout if timeout is not None else 30.0
    return httpx.AsyncClient(timeout=timeout_config, headers=headers)


def get_authenticated_requests_session(
    api_key_override: Optional[str] = None,
) -> requests.Session:
    """Create requests Session with RunPod authentication and User-Agent.

    Automatically includes:
    - User-Agent header identifying flash client and version
    - Authorization header if an api key is available

    Provides a centralized place to manage authentication headers for
    synchronous RunPod HTTP requests.

    Args:
        api_key_override: Optional API key to use instead of RUNPOD_API_KEY env var.
                         Used for propagating API keys from load-balanced to worker endpoints.

    Returns:
        Configured requests.Session with User-Agent and Authorization headers

    Example:
        session = get_authenticated_requests_session()
        response = session.post(url, json=data, timeout=30.0)
        # Remember to close: session.close()

        # Or use as context manager
        import contextlib
        with contextlib.closing(get_authenticated_requests_session()) as session:
            response = session.post(url, json=data)

        # With API key override (for propagation)
        with contextlib.closing(get_authenticated_requests_session(api_key_override=context_key)) as session:
            response = session.post(url, json=data)
    """
    from .user_agent import get_user_agent

    session = requests.Session()
    session.headers["User-Agent"] = get_user_agent()
    session.headers["Content-Type"] = "application/json"

    api_key = api_key_override or get_api_key()
    if api_key:
        session.headers["Authorization"] = f"Bearer {api_key}"

    return session
