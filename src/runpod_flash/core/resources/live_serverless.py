# Ship serverless code as you write it. No builds, no deploys — just run.
from pydantic import model_validator

from .constants import (
    GPU_BASE_IMAGE_PYTHON_VERSION,
    get_image_name,
    local_python_version,
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

    @model_validator(mode="before")
    @classmethod
    def set_live_serverless_template(cls, data: dict):
        """Set default GPU image for Live Serverless."""
        if "imageName" not in data:
            python_version = data.get("python_version") or GPU_BASE_IMAGE_PYTHON_VERSION
            data["imageName"] = get_image_name("gpu", python_version)
        return data


class CpuLiveServerless(LiveServerlessMixin, CpuServerlessEndpoint):
    """CPU-only live serverless endpoint with automatic disk sizing."""

    @model_validator(mode="before")
    @classmethod
    def set_live_serverless_template(cls, data: dict):
        """Set default CPU image for Live Serverless."""
        if "imageName" not in data:
            python_version = data.get("python_version") or local_python_version()
            data["imageName"] = get_image_name("cpu", python_version)
        return data


class LiveLoadBalancer(LiveServerlessMixin, LoadBalancerSlsResource):
    """Live load-balanced endpoint."""

    @model_validator(mode="before")
    @classmethod
    def set_live_lb_template(cls, data: dict):
        """Set default image for Live Load-Balanced endpoint."""
        if "imageName" not in data:
            python_version = data.get("python_version") or GPU_BASE_IMAGE_PYTHON_VERSION
            data["imageName"] = get_image_name("lb", python_version)
        return data


class CpuLiveLoadBalancer(LiveServerlessMixin, CpuLoadBalancerSlsResource):
    """CPU-only live load-balanced endpoint."""

    @model_validator(mode="before")
    @classmethod
    def set_live_cpu_lb_template(cls, data: dict):
        """Set default CPU image for Live Load-Balanced endpoint."""
        if "imageName" not in data:
            python_version = data.get("python_version") or local_python_version()
            data["imageName"] = get_image_name("lb-cpu", python_version)
        return data
