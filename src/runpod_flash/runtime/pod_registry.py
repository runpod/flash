"""Pod service discovery registry for runtime address resolution.

Resolves pod names to base URLs by querying the PodTracker cache
and refreshing from the Runpod API when entries are stale.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from runpod_flash.core.exceptions import PodNotFoundError, PodNotRunningError
from runpod_flash.core.resources.pod import API_STATUS_MAP, PodState

if TYPE_CHECKING:
    from runpod_flash.core.api.pod_client import PodApiClient
    from runpod_flash.core.resources.pod_lifecycle import PodTracker

CACHE_TTL_SECONDS = 30


@dataclass(slots=True)
class PodRegistryEntry:
    """Mutable cache entry for a resolved pod address."""

    address: str | None
    state: PodState
    resolved_at: float

    @property
    def is_stale(self) -> bool:
        """True if the entry is older than CACHE_TTL_SECONDS."""
        return (time.monotonic() - self.resolved_at) > CACHE_TTL_SECONDS


class PodRegistry:
    """Resolves pod names to base URLs with caching.

    Uses PodTracker for pod identity lookup and PodApiClient for
    live status queries. Caches results to avoid repeated API calls.

    Args:
        tracker: PodTracker for pod identity persistence.
        api_client: Async Runpod pod API client.
    """

    def __init__(self, tracker: PodTracker, api_client: PodApiClient) -> None:
        self._tracker = tracker
        self._api = api_client
        self._cache: dict[str, PodRegistryEntry] = {}

    async def resolve(self, pod_name: str) -> str:
        """Resolve a pod name to its base URL.

        Checks the in-memory cache first. If the entry is fresh and
        the pod is running, returns the cached address. If stale or
        missing, queries the API to refresh.

        Args:
            pod_name: Name of the pod to resolve.

        Returns:
            Base URL string like "https://ip:port".

        Raises:
            PodNotFoundError: If the pod is not tracked.
            PodNotRunningError: If the pod is not in RUNNING state.
        """
        cached = self._cache.get(pod_name)
        if cached is not None and not cached.is_stale:
            if cached.state == PodState.RUNNING and cached.address is not None:
                return cached.address
            raise PodNotRunningError(pod_name, cached.state)

        tracked = self._tracker.load(pod_name)
        if tracked is None:
            raise PodNotFoundError(pod_name)

        response = await self._api.get(tracked.pod_id)

        state = API_STATUS_MAP.get(response.desired_status, PodState.PROVISIONING)

        address: str | None = None
        if response.ports:
            first = next(iter(response.ports.values()))
            address = f"https://{first.host_ip}:{first.host_port}"

        entry = PodRegistryEntry(
            address=address,
            state=state,
            resolved_at=time.monotonic(),
        )
        self._cache[pod_name] = entry

        if state != PodState.RUNNING or address is None:
            raise PodNotRunningError(pod_name, state)

        return address
