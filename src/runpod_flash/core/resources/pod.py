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
