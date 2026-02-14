"""Load balancing strategies for distributed endpoint routing."""

import asyncio
import logging
import random
from typing import TYPE_CHECKING, List, Optional

from runpod_flash.runtime.reliability_config import LoadBalancerStrategy

if TYPE_CHECKING:
    from runpod_flash.runtime.circuit_breaker import CircuitBreakerRegistry

logger = logging.getLogger(__name__)


class LoadBalancer:
    """Load balancer for selecting endpoints using various strategies."""

    def __init__(
        self, strategy: LoadBalancerStrategy = LoadBalancerStrategy.ROUND_ROBIN
    ):
        """Initialize load balancer.

        Args:
            strategy: Load balancing strategy to use
        """
        self.strategy = strategy
        self._round_robin_index = 0
        self._lock = asyncio.Lock()
        self._in_flight_requests: dict[str, int] = {}

    async def select_endpoint(
        self,
        endpoints: List[str],
        circuit_breaker_registry: Optional["CircuitBreakerRegistry"] = None,
    ) -> Optional[str]:
        """Select an endpoint using configured strategy.

        Args:
            endpoints: List of available endpoint URLs
            circuit_breaker_registry: Optional circuit breaker registry to check health

        Returns:
            Selected endpoint URL or None if all endpoints are unhealthy
        """
        if not endpoints:
            return None

        # Filter out unhealthy endpoints if circuit breaker available
        healthy_endpoints = endpoints
        if circuit_breaker_registry is not None:
            from runpod_flash.runtime.circuit_breaker import CircuitState

            healthy_endpoints = [
                url
                for url in endpoints
                if circuit_breaker_registry.get_state(url) != CircuitState.OPEN
            ]

        if not healthy_endpoints:
            logger.warning(
                f"All {len(endpoints)} endpoints are unhealthy (circuit open)"
            )
            return None

        if self.strategy == LoadBalancerStrategy.ROUND_ROBIN:
            return await self._round_robin_select(healthy_endpoints)
        elif self.strategy == LoadBalancerStrategy.LEAST_CONNECTIONS:
            return await self._least_connections_select(healthy_endpoints)
        elif self.strategy == LoadBalancerStrategy.RANDOM:
            return await self._random_select(healthy_endpoints)
        else:
            # Default to round-robin
            return await self._round_robin_select(healthy_endpoints)

    async def _round_robin_select(self, endpoints: List[str]) -> str:
        """Select endpoint using round-robin strategy.

        Args:
            endpoints: List of available endpoints

        Returns:
            Selected endpoint URL
        """
        async with self._lock:
            selected = endpoints[self._round_robin_index % len(endpoints)]
            self._round_robin_index += 1
        return selected

    async def _least_connections_select(self, endpoints: List[str]) -> str:
        """Select endpoint with fewest in-flight requests.

        Args:
            endpoints: List of available endpoints

        Returns:
            Selected endpoint URL
        """
        async with self._lock:
            # Initialize counts for endpoints
            for endpoint in endpoints:
                if endpoint not in self._in_flight_requests:
                    self._in_flight_requests[endpoint] = 0

            # Find endpoint with minimum connections
            selected = min(endpoints, key=lambda e: self._in_flight_requests.get(e, 0))

        return selected

    async def _random_select(self, endpoints: List[str]) -> str:
        """Select endpoint using random strategy.

        Args:
            endpoints: List of available endpoints

        Returns:
            Selected endpoint URL
        """
        selected = random.choice(endpoints)
        return selected

    async def record_request(self, endpoint: str) -> None:
        """Record that a request is starting on endpoint.

        Args:
            endpoint: Endpoint URL
        """
        async with self._lock:
            self._in_flight_requests[endpoint] = (
                self._in_flight_requests.get(endpoint, 0) + 1
            )

    async def record_request_complete(self, endpoint: str) -> None:
        """Record that a request completed on endpoint.

        Args:
            endpoint: Endpoint URL
        """
        async with self._lock:
            if endpoint in self._in_flight_requests:
                self._in_flight_requests[endpoint] = max(
                    0, self._in_flight_requests[endpoint] - 1
                )

    def get_stats(self) -> dict[str, int]:
        """Get current in-flight request counts.

        Returns:
            Mapping of endpoint URLs to in-flight request counts
        """
        return dict(self._in_flight_requests)
