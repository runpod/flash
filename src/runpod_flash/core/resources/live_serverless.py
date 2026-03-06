# Ship serverless code as you write it. No builds, no deploys -- just run.
from typing import Any, ClassVar

from pydantic import model_validator

from .constants import (
    DEFAULT_PYTHON_VERSION,
    get_image_name,
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
    """Common mixin for live serverless endpoints.

    Treats the Flash runtime image as a *default*: if the caller passes an
    ``imageName`` (e.g. via ``Endpoint(image=...)`` in client mode), that
    value wins. Otherwise the Flash runtime image for this resource type is
    used so decorator-mode workloads continue to deploy the Flash wrapper.

    The default is applied via the ``@model_validator(mode="before")`` on each
    concrete subclass (see ``_apply_default_live_image``); reads and writes of
    ``imageName`` go through the normal Pydantic field machinery so model
    serialization, drift detection, and ``setattr`` all stay consistent.
    """Configures process injection via dockerArgs for any base image.

    Sets a default base image (user can override via imageName) and generates
    dockerArgs to download, extract, and run the flash-worker tarball at container
    start time. QB vs LB mode is determined by FLASH_ENDPOINT_TYPE env var at
    runtime, not by the Docker image.
    """

    _image_type: ClassVar[str] = (
        ""  # override in subclasses: 'gpu', 'cpu', 'lb', 'lb-cpu'
    )

    @property
    def _live_image(self) -> str:
        python_version = getattr(self, "python_version", None) or DEFAULT_PYTHON_VERSION
        return get_image_name(self._image_type, python_version)


def _apply_default_live_image(data: Any, image_type: str):
    """Set the Flash runtime image as a default if the caller didn't supply one.

    ``data`` is annotated ``Any`` because Pydantic's ``@model_validator(mode="before")``
    can receive either the raw input dict or an already-constructed model instance
    (on revalidation). The ``isinstance(data, dict)`` guard handles the latter.
    """
    if not isinstance(data, dict):
        return data
    if not data.get("imageName"):
        python_version = data.get("python_version") or DEFAULT_PYTHON_VERSION
        data["imageName"] = get_image_name(image_type, python_version)
    return data

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

    _image_type: ClassVar[str] = "gpu"

    @model_validator(mode="before")
    @classmethod
    def set_live_serverless_template(cls, data: dict):
        """Default to the GPU Flash runtime image when none is supplied."""
        return _apply_default_live_image(data, "gpu")


class CpuLiveServerless(LiveServerlessMixin, CpuServerlessEndpoint):
    """CPU-only live serverless endpoint with automatic disk sizing."""

    _image_type: ClassVar[str] = "cpu"

    @model_validator(mode="before")
    @classmethod
    def set_live_serverless_template(cls, data: dict):
        """Default to the CPU Flash runtime image when none is supplied."""
        return _apply_default_live_image(data, "cpu")


class LiveLoadBalancer(LiveServerlessMixin, LoadBalancerSlsResource):
    """Live load-balanced endpoint."""

    _image_type: ClassVar[str] = "lb"

    @model_validator(mode="before")
    @classmethod
    def set_live_lb_template(cls, data: dict):
        """Default to the LB Flash runtime image when none is supplied."""
        return _apply_default_live_image(data, "lb")


class CpuLiveLoadBalancer(LiveServerlessMixin, CpuLoadBalancerSlsResource):
    """CPU-only live load-balanced endpoint."""

    _image_type: ClassVar[str] = "lb-cpu"

    @model_validator(mode="before")
    @classmethod
    def set_live_cpu_lb_template(cls, data: dict):
        """Default to the CPU LB Flash runtime image when none is supplied."""
        return _apply_default_live_image(data, "lb-cpu")
