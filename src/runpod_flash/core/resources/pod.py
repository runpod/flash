"""Pod resource models for Runpod pod management.

Defines the core data structures for pod lifecycle: state machine,
configuration, and the Pod class itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import httpx

from runpod_flash.core.exceptions import PodRequestError


class PodState(str, Enum):
    """Lifecycle states for a Runpod pod."""

    DEFINED = "defined"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    RESUMING = "resuming"
    TERMINATING = "terminating"
    TERMINATED = "terminated"


VALID_TRANSITIONS: dict[PodState, set[PodState]] = {
    PodState.DEFINED: {PodState.PROVISIONING},
    PodState.PROVISIONING: {PodState.RUNNING, PodState.TERMINATED},
    PodState.RUNNING: {PodState.STOPPING, PodState.TERMINATING},
    PodState.STOPPING: {PodState.STOPPED, PodState.TERMINATED},
    PodState.STOPPED: {PodState.RESUMING, PodState.TERMINATING},
    PodState.RESUMING: {PodState.RUNNING, PodState.TERMINATED},
    PodState.TERMINATING: {PodState.TERMINATED},
    PodState.TERMINATED: set(),
}

API_STATUS_MAP: dict[str, PodState] = {
    "RUNNING": PodState.RUNNING,
    "EXITED": PodState.STOPPED,
    "TERMINATED": PodState.TERMINATED,
    "CREATED": PodState.PROVISIONING,
}


@dataclass(frozen=True, slots=True)
class PodResponse:
    """Immutable response from a Pod HTTP request.

    Wraps raw HTTP response data with convenience accessors.
    """

    status_code: int
    headers: dict[str, str]
    body: bytes
    json_data: Any | None

    @property
    def ok(self) -> bool:
        """True when status code indicates success (2xx)."""
        return 200 <= self.status_code < 300

    def raise_for_status(self) -> None:
        """Raise PodRequestError if the response status is not 2xx."""
        if not self.ok:
            raise PodRequestError(self.status_code, self.body)


@dataclass(frozen=True, slots=True)
class PodConfig:
    """Immutable configuration matching runpod SDK create_pod() parameters.

    All fields have sensible defaults so callers only specify what they need.
    """

    gpu_count: int = 1
    cloud_type: str = "ALL"
    container_disk_in_gb: int = 10
    volume_in_gb: int = 0
    volume_mount_path: str = "/runpod-volume"
    network_volume_id: str | None = None
    ports: list[str] | None = field(default=None)
    docker_args: str = ""
    start_ssh: bool = True
    support_public_ip: bool = True
    data_center_id: str | None = None
    country_code: str | None = None
    min_vcpu_count: int = 1
    min_memory_in_gb: int = 1
    allowed_cuda_versions: list[str] | None = field(default=None)
    min_download: int | None = None
    min_upload: int | None = None
    instance_id: str | None = None
    template_id: str | None = None

    @property
    def ports_str(self) -> str | None:
        """Join ports list into comma-separated string for SDK compatibility."""
        if self.ports is None:
            return None
        return ",".join(self.ports)


class Pod:
    """A Runpod pod resource.

    Holds identity, image, GPU selection, environment, and immutable config.
    Tracks runtime state (pod_id, state, address) separately from config.

    Args:
        name: Unique pod name.
        image: Docker image to run.
        gpu: GPU type identifier (string or GpuType enum).
        env: Environment variables injected into the pod.
        config: Explicit PodConfig. Mutually exclusive with **kwargs.
        **kwargs: Forwarded to PodConfig constructor if config is not provided.
    """

    def __init__(
        self,
        name: str,
        image: str,
        gpu: Any | None = None,
        env: dict[str, str] | None = None,
        config: PodConfig | None = None,
        **kwargs: Any,
    ) -> None:
        if config is not None and kwargs:
            msg = "Cannot provide both 'config' and keyword arguments to Pod"
            raise ValueError(msg)

        self.name = name
        self.image = image
        self.gpu = gpu
        self.env: dict[str, str] = env if env is not None else {}
        self.config: PodConfig = config if config is not None else PodConfig(**kwargs)

        # Runtime state -- mutated during lifecycle, not part of config hash
        self._pod_id: str | None = None
        self._state: PodState = PodState.DEFINED
        self._address: str | None = None

    @property
    def config_hash(self) -> str:
        """MD5 hash of identity + config for drift detection.

        Returns:
            Hex digest string.
        """
        payload = json.dumps(
            {
                "name": self.name,
                "image": self.image,
                "gpu": str(self.gpu) if self.gpu is not None else None,
                "env": self.env,
                "config": asdict(self.config),
            },
            sort_keys=True,
        )
        return hashlib.md5(payload.encode()).hexdigest()  # noqa: S324

    # -- Registry binding for address resolution --

    def _bind_registry(self, registry: Any) -> None:
        """Inject PodRegistry for address resolution. Called by Flash runtime."""
        self._registry = registry

    # -- HTTP convenience methods --

    async def get(self, path: str, **kwargs: Any) -> PodResponse:
        """Send a GET request to the pod."""
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> PodResponse:
        """Send a POST request to the pod."""
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> PodResponse:
        """Send a PUT request to the pod."""
        return await self._request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> PodResponse:
        """Send a DELETE request to the pod."""
        return await self._request("DELETE", path, **kwargs)

    async def _request(self, method: str, path: str, **kwargs: Any) -> PodResponse:
        """Send an HTTP request to the pod via registry-resolved address.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: URL path relative to the pod's base address.
            **kwargs: Forwarded to httpx.AsyncClient.request.

        Returns:
            PodResponse with status, headers, body, and parsed JSON (if applicable).

        Raises:
            RuntimeError: If no registry is bound to this pod.
        """
        if not hasattr(self, "_registry") or self._registry is None:
            raise RuntimeError(
                f"Pod '{self.name}' has no registry bound. "
                "Ensure the pod is used within a Flash runtime context."
            )
        base_url = await self._registry.resolve(self.name)
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, **kwargs)

        content_type = response.headers.get("content-type", "")
        json_data = None
        if "application/json" in content_type:
            try:
                json_data = response.json()
            except Exception:  # noqa: BLE001
                pass

        return PodResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
            json_data=json_data,
        )
