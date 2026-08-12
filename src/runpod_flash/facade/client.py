"""raw-id queue client and an EndpointJob-compatible shim on apps.

apps' Queue/Api stubs require app=+name=; flash's Endpoint(id=) is a bare
endpoint id. until the upstream id-only stub (gap G3) lands, the facade
owns a raw-id QueueClient with plain auth headers.
"""

from typing import Any, Optional

from runpod.apps.targets import QueueClient, _headers

_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"})


def apps_qb_client(endpoint_id: str) -> QueueClient:
    """a queue data-plane client for a raw endpoint id (no app/env)."""
    return QueueClient(endpoint_id, _headers)


class AppsEndpointJob:
    """EndpointJob-compatible view over an apps QueueClient job.

    mirrors runpod_flash.endpoint.EndpointJob's public surface so the
    flash facade can return it unchanged to callers.
    """

    def __init__(self, data: dict, client: QueueClient):
        self._data = dict(data)
        self._client = client

    @property
    def id(self) -> str:
        return self._data.get("id", "")

    @property
    def output(self) -> Any:
        return self._data.get("output")

    @property
    def error(self) -> Optional[str]:
        return self._data.get("error")

    @property
    def done(self) -> bool:
        return self._data.get("status", "UNKNOWN") in _TERMINAL_STATUSES

    async def status(self) -> str:
        self._data = await self._client.status(self.id)
        return self._data.get("status", "UNKNOWN")

    async def cancel(self) -> "AppsEndpointJob":
        self._data.update(await self._client.cancel(self.id))
        return self

    async def wait(self, timeout: Optional[float] = None) -> "AppsEndpointJob":
        import asyncio
        import time

        deadline = (time.monotonic() + timeout) if timeout is not None else None
        interval = 0.25
        while not self.done:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"job {self.id} did not complete within {timeout}s "
                    f"(last status: {self._data.get('status', 'UNKNOWN')})"
                )
            await asyncio.sleep(interval)
            await self.status()
            interval = min(interval * 1.5, 5.0)
        return self
