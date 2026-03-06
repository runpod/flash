# Ship serverless code as you write it. No builds, no deploys -- just run.
from pydantic import model_validator

from .constants import (
    FLASH_CPU_BASE_IMAGE,
    FLASH_CPU_IMAGE,
    FLASH_CPU_LB_IMAGE,
    FLASH_GPU_BASE_IMAGE,
    FLASH_GPU_IMAGE,
    FLASH_LB_IMAGE,
)
from .injection import build_injection_cmd
from .load_balancer_sls_resource import (
    CpuLoadBalancerSlsResource,
    LoadBalancerSlsResource,
)
from .serverless import ServerlessEndpoint
from .serverless_cpu import CpuServerlessEndpoint
from .template import PodTemplate


class LiveServerlessMixin:
    """Configures process injection via dockerArgs for any base image.

    Sets a default base image (user can override via imageName) and generates
    dockerArgs to download, extract, and run the flash-worker tarball at container
    start time. QB vs LB mode is determined by FLASH_ENDPOINT_TYPE env var at
    runtime, not by the Docker image.
    """

    @property
    def _default_base_image(self) -> str:
        raise NotImplementedError("Subclasses must define _default_base_image")

    @property
    def _legacy_image(self) -> str:
        """Legacy Docker Hub image for preview mode."""
        raise NotImplementedError("Subclasses must define _legacy_image")

    def _create_new_template(self) -> PodTemplate:
        """Create template with dockerArgs for process injection."""
        template = super()._create_new_template()  # type: ignore[misc]
        template.dockerArgs = build_injection_cmd()
        return template

    def _configure_existing_template(self) -> None:
        """Configure existing template, adding dockerArgs for injection if not user-set."""
        super()._configure_existing_template()  # type: ignore[misc]
        if self.template is not None and not self.template.dockerArgs:  # type: ignore[attr-defined]
            self.template.dockerArgs = build_injection_cmd()  # type: ignore[attr-defined]


class LiveServerless(LiveServerlessMixin, ServerlessEndpoint):
    """GPU-only live serverless endpoint."""

    @property
    def _default_base_image(self) -> str:
        return FLASH_GPU_BASE_IMAGE

    @property
    def _legacy_image(self) -> str:
        return FLASH_GPU_IMAGE

    @model_validator(mode="before")
    @classmethod
    def set_live_serverless_template(cls, data: dict):
        """Set default GPU base image for Live Serverless."""
        if not data.get("imageName"):
            data["imageName"] = FLASH_GPU_BASE_IMAGE
        return data


class CpuLiveServerless(LiveServerlessMixin, CpuServerlessEndpoint):
    """CPU-only live serverless endpoint with automatic disk sizing."""

    @property
    def _default_base_image(self) -> str:
        return FLASH_CPU_BASE_IMAGE

    @property
    def _legacy_image(self) -> str:
        return FLASH_CPU_IMAGE

    @model_validator(mode="before")
    @classmethod
    def set_live_serverless_template(cls, data: dict):
        """Set default CPU base image for Live Serverless."""
        if not data.get("imageName"):
            data["imageName"] = FLASH_CPU_BASE_IMAGE
        return data


class LiveLoadBalancer(LiveServerlessMixin, LoadBalancerSlsResource):
    """Live load-balanced endpoint for local development and testing.

    Similar to LiveServerless but for HTTP-based load-balanced endpoints.
    Enables local testing of @remote decorated functions with LB endpoints
    before deploying to production.

    Usage:
        from runpod_flash import LiveLoadBalancer, remote

        api = LiveLoadBalancer(name="api-service")

        @remote(api, method="POST", path="/api/process")
        async def process_data(x: int, y: int):
            return {"result": x + y}
    """

    @property
    def _default_base_image(self) -> str:
        return FLASH_GPU_BASE_IMAGE

    @property
    def _legacy_image(self) -> str:
        return FLASH_LB_IMAGE

    @model_validator(mode="before")
    @classmethod
    def set_live_lb_template(cls, data: dict):
        """Set default image for Live Load-Balanced endpoint."""
        if not data.get("imageName"):
            data["imageName"] = FLASH_GPU_BASE_IMAGE
        return data


class CpuLiveLoadBalancer(LiveServerlessMixin, CpuLoadBalancerSlsResource):
    """CPU-only live load-balanced endpoint for local development and testing.

    Similar to LiveLoadBalancer but configured for CPU instances with
    automatic disk sizing and validation.

    Usage:
        from runpod_flash import CpuLiveLoadBalancer, remote

        api = CpuLiveLoadBalancer(name="api-service")

        @remote(api, method="POST", path="/api/process")
        async def process_data(x: int, y: int):
            return {"result": x + y}
    """

    @property
    def _default_base_image(self) -> str:
        return FLASH_CPU_BASE_IMAGE

    @property
    def _legacy_image(self) -> str:
        return FLASH_CPU_LB_IMAGE

    @model_validator(mode="before")
    @classmethod
    def set_live_cpu_lb_template(cls, data: dict):
        """Set default CPU image for Live Load-Balanced endpoint."""
        if not data.get("imageName"):
            data["imageName"] = FLASH_CPU_BASE_IMAGE
        return data
