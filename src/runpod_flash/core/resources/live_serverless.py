# Ship serverless code as you write it. No builds, no deploys — just run.
from typing import ClassVar

from pydantic import model_validator

from .constants import (
    GPU_BASE_IMAGE_PYTHON_VERSION,
    get_image_name,
    local_python_version,
)
from .load_balancer_sls_resource import (
    CpuLoadBalancerSlsResource,
    LoadBalancerSlsResource,
)
from .serverless import ServerlessEndpoint
from .serverless_cpu import CpuServerlessEndpoint


class LiveServerlessMixin:
    """Common mixin for live serverless endpoints that locks the image."""

    _image_type: ClassVar[str] = (
        ""  # Override in subclasses: 'gpu', 'cpu', 'lb', 'lb-cpu'
    )
    _GPU_IMAGE_TYPES: ClassVar[frozenset[str]] = frozenset({"gpu", "lb"})

    @property
    def _live_image(self) -> str:
        python_version = getattr(self, "python_version", None)
        if not python_version:
            if self._image_type in self._GPU_IMAGE_TYPES:
                python_version = GPU_BASE_IMAGE_PYTHON_VERSION
            else:
                python_version = local_python_version()
        return get_image_name(self._image_type, python_version)

    @property
    def imageName(self):
        return self._live_image

    @imageName.setter
    def imageName(self, value):
        pass


class LiveServerless(LiveServerlessMixin, ServerlessEndpoint):
    """GPU-only live serverless endpoint."""

    _image_type: ClassVar[str] = "gpu"

    @model_validator(mode="before")
    @classmethod
    def set_live_serverless_template(cls, data: dict):
        """Set default GPU image for Live Serverless."""
        python_version = data.get("python_version") or GPU_BASE_IMAGE_PYTHON_VERSION
        data["imageName"] = get_image_name("gpu", python_version)
        return data


class CpuLiveServerless(LiveServerlessMixin, CpuServerlessEndpoint):
    """CPU-only live serverless endpoint with automatic disk sizing."""

    _image_type: ClassVar[str] = "cpu"

    @model_validator(mode="before")
    @classmethod
    def set_live_serverless_template(cls, data: dict):
        """Set default CPU image for Live Serverless."""
        python_version = data.get("python_version") or local_python_version()
        data["imageName"] = get_image_name("cpu", python_version)
        return data


class LiveLoadBalancer(LiveServerlessMixin, LoadBalancerSlsResource):
    """Live load-balanced endpoint."""

    _image_type: ClassVar[str] = "lb"

    @model_validator(mode="before")
    @classmethod
    def set_live_lb_template(cls, data: dict):
        """Set default image for Live Load-Balanced endpoint."""
        python_version = data.get("python_version") or GPU_BASE_IMAGE_PYTHON_VERSION
        data["imageName"] = get_image_name("lb", python_version)
        return data


class CpuLiveLoadBalancer(LiveServerlessMixin, CpuLoadBalancerSlsResource):
    """CPU-only live load-balanced endpoint."""

    _image_type: ClassVar[str] = "lb-cpu"

    @model_validator(mode="before")
    @classmethod
    def set_live_cpu_lb_template(cls, data: dict):
        """Set default CPU image for Live Load-Balanced endpoint."""
        python_version = data.get("python_version") or local_python_version()
        data["imageName"] = get_image_name("lb-cpu", python_version)
        return data
