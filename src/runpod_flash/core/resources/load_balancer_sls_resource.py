"""
LoadBalancerSlsResource - Resource type for RunPod Load-Balanced Serverless endpoints.

Load-balanced endpoints expose HTTP servers directly to clients without the queue-based
processing model of standard serverless endpoints. They're ideal for REST APIs, webhooks,
and real-time communication patterns.

Key differences from standard serverless (QB):
- Requests route directly to healthy workers via HTTP
- No automatic retries (client responsible)
- Lower latency but less fault tolerance
- Requires HTTP application, not a function handler
- Health checks via /ping endpoint
"""

import asyncio
import logging
from typing import List, Optional

from pydantic import model_validator

from runpod_flash.core.utils.http import get_authenticated_httpx_client
from .constants import ENDPOINT_DOMAIN
from .cpu import CpuInstanceType
from .serverless import ServerlessResource, ServerlessType, ServerlessScalerType
from .serverless_cpu import CpuEndpointMixin

log = logging.getLogger(__name__)

# Configuration constants
DEFAULT_HEALTH_CHECK_RETRIES = 10
DEFAULT_HEALTH_CHECK_INTERVAL = 5  # seconds between retries
DEFAULT_PING_REQUEST_TIMEOUT = (
    15.0  # seconds (load-balanced workers need time for cold starts)
)
HEALTHY_STATUS_CODES = (200, 204)


class LoadBalancerSlsResource(ServerlessResource):
    """
    Resource configuration for RunPod Load-Balanced Serverless endpoints.

    Load-balanced endpoints expose HTTP servers directly, making them suitable for:
    - REST APIs
    - WebSocket servers
    - Real-time streaming
    - Custom HTTP protocols

    Configuration example:
        lb = LoadBalancerSlsResource(
            name="my_lb",
            imageName="my-lb:latest",
            env={"FLASH_APP": "my_app"},
            workersMin=1,
            workersMax=3,
        )
        await lb.deploy()
    """

    # Override default type to LB
    type: Optional[ServerlessType] = ServerlessType.LB

    def __init__(self, **data):
        """Initialize LoadBalancerSlsResource with LB-specific defaults."""
        # Ensure type is always LB
        data["type"] = ServerlessType.LB

        # LB endpoints shouldn't use queue-based scaling
        if "scalerType" not in data:
            data["scalerType"] = ServerlessScalerType.REQUEST_COUNT

        super().__init__(**data)

    @model_validator(mode="after")
    def set_serverless_template(self):
        """Create template from imageName if not provided.

        Must run after sync_input_fields to ensure all input fields are synced.
        """
        if not any([self.imageName, self.template, self.templateId]):
            raise ValueError(
                "Either imageName, template, or templateId must be provided"
            )

        if not self.templateId and not self.template:
            self.template = self._create_new_template()
        elif self.template:
            self._configure_existing_template()

        return self

    @property
    def endpoint_url(self) -> str:
        """Get the endpoint URL for load-balanced endpoints.

        Load-balanced endpoints use a different URL format than standard
        serverless endpoints. They use: https://{endpoint_id}.{ENDPOINT_DOMAIN}

        Returns:
            The endpoint URL for health checks and direct HTTP requests

        Raises:
            ValueError: If endpoint ID not set
        """
        if not self.id:
            raise ValueError("Endpoint ID not set. Cannot determine endpoint URL.")
        return f"https://{self.id}.{ENDPOINT_DOMAIN}"

    def _validate_lb_configuration(self) -> None:
        """
        Validate LB-specific configuration constraints.

        Raises:
            ValueError: If configuration violates LB requirements
        """
        # LB must use REQUEST_COUNT scaler, not QUEUE_DELAY
        if self.scalerType == ServerlessScalerType.QUEUE_DELAY:
            raise ValueError(
                f"LoadBalancerSlsResource requires REQUEST_COUNT scaler, "
                f"not {self.scalerType.value}. "
                "Load-balanced endpoints don't support queue-based scaling."
            )

        # Type must always be LB
        if self.type != ServerlessType.LB:
            raise ValueError(
                f"LoadBalancerSlsResource type must be LB, got {self.type.value}"
            )

    async def is_deployed_async(self) -> bool:
        """
        Check if LB endpoint is deployed and /ping endpoint is responding.

        For LB endpoints, we verify:
        1. Endpoint ID exists (created in RunPod)
        2. /ping endpoint returns 200 or 204
        3. Endpoint is in healthy state

        Returns:
            True if endpoint is deployed and healthy, False otherwise
        """
        try:
            if not self.id:
                return False

            # Use async health check for LB endpoints
            return await self._check_ping_endpoint()

        except Exception as e:
            log.debug(f"Error checking {self}: {e}")
            return False

    async def _check_ping_endpoint(self) -> bool:
        """
        Check if /ping endpoint is accessible and healthy.

        RunPod load-balancer endpoints require a /ping endpoint that returns:
        - 200 OK: Worker is healthy and ready
        - 204 No Content: Worker is initializing
        - Other status: Worker is unhealthy

        Returns:
            True if /ping endpoint responds with 200 or 204
        """
        try:
            if not self.id:
                return False

            ping_url = f"{self.endpoint_url}/ping"

            async with get_authenticated_httpx_client(
                timeout=DEFAULT_PING_REQUEST_TIMEOUT
            ) as client:
                response = await client.get(ping_url)
                return response.status_code in HEALTHY_STATUS_CODES
        except Exception as e:
            log.debug(f"Ping check failed for {self.name}: {e}")
            return False

    async def _wait_for_health(
        self,
        max_retries: int = DEFAULT_HEALTH_CHECK_RETRIES,
        retry_interval: int = DEFAULT_HEALTH_CHECK_INTERVAL,
    ) -> bool:
        """
        Poll /ping endpoint until endpoint is healthy or timeout.

        Args:
            max_retries: Number of health check attempts
            retry_interval: Seconds between health check attempts

        Returns:
            True if endpoint became healthy, False if timeout

        Raises:
            ValueError: If endpoint ID not set
        """
        if not self.id:
            raise ValueError("Cannot wait for health: endpoint not deployed")

        log.debug(
            f"Waiting for LB endpoint {self.name} ({self.id}) to become healthy... "
            f"(max {max_retries} retries, {retry_interval}s interval)"
        )

        for attempt in range(max_retries):
            try:
                if await self._check_ping_endpoint():
                    log.debug(
                        f"LB endpoint {self.name} is healthy (attempt {attempt + 1})"
                    )
                    return True

                log.debug(
                    f"Health check attempt {attempt + 1}/{max_retries} - "
                    f"endpoint not ready yet"
                )

            except Exception as e:
                log.debug(f"Health check attempt {attempt + 1} failed: {e}")

            # Wait before next attempt (except on last attempt)
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_interval)

        log.debug(
            f"LB endpoint {self.name} failed to become healthy after "
            f"{max_retries} attempts"
        )
        return False

    async def _do_deploy(self) -> "LoadBalancerSlsResource":
        """
        Deploy LB endpoint without blocking on health checks.

        Deployment flow:
        1. Validate LB configuration
        2. Call parent deploy (creates endpoint in RunPod)
        3. Return deployed resource immediately

        Returns:
            Deployed LoadBalancerSlsResource instance

        Raises:
            ValueError: If LB configuration invalid or deployment fails
        """
        # Validate before deploying
        self._validate_lb_configuration()

        # Check if already deployed
        if self.is_deployed():
            log.debug(f"{self} already deployed")
            return self

        try:
            # Mark this endpoint as load-balanced (triggers auto-provisioning on boot).
            # Injected into template.env (not self.env) to avoid false config drift.
            self._inject_template_env("FLASH_ENDPOINT_TYPE", "lb")

            # Call parent deploy (creates endpoint via RunPod API)
            log.debug(f"Deploying LB endpoint: {self.name}")
            deployed = await super()._do_deploy()

            log.debug(f"Deployed: {self.name} ({deployed.url})")
            return deployed

        except Exception as e:
            log.debug(f"Failed to deploy LB endpoint {self.name}: {e}")
            raise

    def is_deployed(self) -> bool:
        """
        Override is_deployed to use async health check.

        Note: This is a synchronous wrapper around the async health check.
        Prefer is_deployed_async() in async contexts.

        Returns:
            True if endpoint is deployed and /ping responds
        """
        if not self.id:
            return False

        try:
            # Try the RunPod SDK health check (works for basic connectivity)
            response = self.endpoint.health()
            return response is not None
        except Exception as e:
            log.debug(f"RunPod health check failed for {self.name}: {e}")
            return False


class CpuLoadBalancerSlsResource(CpuEndpointMixin, LoadBalancerSlsResource):
    """CPU-only load-balanced endpoint with automatic disk sizing.

    Similar to LoadBalancerSlsResource but configured for CPU instances
    instead of GPUs. Inherits CPU-specific functionality from CpuEndpointMixin
    for automatic disk sizing and validation.

    Defaults to CPU_ANY instance type if not specified.

    Implementation Note - Field List Coupling:
    This class overrides config_hash() with a CPU-specific field list instead of
    inheriting the base ServerlessResource implementation. This is intentional to
    exclude GPU fields while maintaining drift detection for CPU-specific fields.

    When adding new fields to ServerlessResource:
    1. Evaluate if the field applies to CPU endpoints
    2. If yes, add it to the cpu_fields set in config_hash()
    3. If it's API-assigned, verify it's in ServerlessResource.RUNTIME_FIELDS
    4. Test drift detection with new field changes

    Configuration example:
        cpu_lb = CpuLoadBalancerSlsResource(
            name="my_cpu_lb",
            imageName="my-cpu-lb:latest",
            env={"FLASH_APP": "my_app"},
            instanceIds=[CpuInstanceType.CPU3G_1_4],
            workersMin=1,
            workersMax=3,
        )
        await cpu_lb.deploy()
    """

    instanceIds: Optional[List[CpuInstanceType]] = [CpuInstanceType.CPU3G_2_8]

    # CPU endpoints exclude GPU-specific fields from API payload
    # This prevents the RunPod GraphQL API from rejecting CPU endpoints with GPU-specific fields
    _input_only = {
        "id",
        "cudaVersions",
        "datacenter",
        "env",
        "flashboot",
        "flashEnvironmentId",
        "gpus",
        "gpuIds",
        "gpuCount",
        "allowedCudaVersions",
        "imageName",
        "networkVolume",
    }

    def _setup_cpu_template(self) -> None:
        """Setup template with CPU-appropriate disk sizing."""
        if not any([self.imageName, self.template, self.templateId]):
            raise ValueError(
                "Either imageName, template, or templateId must be provided"
            )

        if not self.templateId and not self.template:
            self.template = self._create_new_template()
        elif self.template:
            self._configure_existing_template()

        # Apply CPU-specific disk sizing
        if self.template:
            self._apply_cpu_disk_sizing(self.template)

    @model_validator(mode="after")
    def set_serverless_template(self):
        """Create template from imageName if not provided.

        Overrides parent to call _sync_cpu_fields first to ensure GPU defaults
        are overridden for CPU endpoints.
        """
        # Sync CPU-specific fields first (override GPU defaults)
        self._sync_cpu_fields()

        # Setup template with validation and creation
        self._setup_cpu_template()

        return self

    @property
    def config_hash(self) -> str:
        """Get hash excluding GPU fields and runtime fields.

        CPU load-balanced endpoints only hash CPU-relevant fields:
        - Instance types (instanceIds)
        - Scaling parameters (workers, scaler)
        - Deployment type (type, locations)
        - Environment variables (env)

        Excludes:
        - GPU fields (to avoid false drift)
        - Runtime fields (template, templateId, aiKey, etc.)
        """
        import hashlib
        import json

        # CPU-relevant fields for drift detection
        cpu_fields = {
            "datacenter",
            "env",
            "flashboot",
            "flashEnvironmentId",
            "imageName",
            "networkVolume",
            "instanceIds",  # CPU-specific
            "workersMin",  # Scaling
            "workersMax",
            "scalerType",
            "scalerValue",
            "type",  # LB vs QB
            "idleTimeout",
            "executionTimeoutMs",
            "locations",
        }

        config_dict = self.model_dump(
            exclude_none=True, include=cpu_fields, mode="json"
        )

        config_str = json.dumps(config_dict, sort_keys=True)
        hash_obj = hashlib.md5(f"{self.__class__.__name__}:{config_str}".encode())
        return hash_obj.hexdigest()
