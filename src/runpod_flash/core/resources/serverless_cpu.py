"""
CPU-specific serverless endpoint classes.

This module contains all CPU-related serverless functionality, separate from GPU serverless.
"""

import hashlib
import json
from typing import List, Optional

from pydantic import field_serializer, model_validator

from .cpu import (
    CpuInstanceType,
    CPU_INSTANCE_DISK_LIMITS,
    get_max_disk_size_for_instances,
)
from .serverless import ServerlessEndpoint, get_env_vars
from .template import KeyValuePair, PodTemplate


class CpuEndpointMixin:
    """Mixin class that provides CPU-specific functionality for serverless endpoints."""

    instanceIds: Optional[List[CpuInstanceType]]

    def _is_cpu_endpoint(self) -> bool:
        """Check if this is a CPU endpoint (has instanceIds)."""
        return (
            hasattr(self, "instanceIds")
            and self.instanceIds is not None
            and len(self.instanceIds) > 0
        )

    def _get_cpu_container_disk_size(self) -> Optional[int]:
        """Get the appropriate container disk size for CPU instances."""
        if not self._is_cpu_endpoint():
            return None
        return get_max_disk_size_for_instances(self.instanceIds)

    def _apply_cpu_disk_sizing(self, template: PodTemplate) -> None:
        """Apply CPU disk sizing to a template if it's using the default size."""
        if not self._is_cpu_endpoint():
            return

        # Only auto-size if template is using the default value
        default_disk_size = PodTemplate.model_fields["containerDiskInGb"].default
        if template.containerDiskInGb == default_disk_size:
            cpu_disk_size = self._get_cpu_container_disk_size()
            if cpu_disk_size is not None:
                template.containerDiskInGb = cpu_disk_size

    def validate_cpu_container_disk_size(self) -> None:
        """
        Validate that container disk size doesn't exceed limits for CPU instances.

        Raises:
            ValueError: If container disk size exceeds the limit for any CPU instance
        """
        if (
            not self._is_cpu_endpoint()
            or not hasattr(self, "template")
            or not self.template
            or not self.template.containerDiskInGb
        ):
            return

        max_allowed_disk_size = self._get_cpu_container_disk_size()
        if max_allowed_disk_size is None:
            return

        if self.template.containerDiskInGb > max_allowed_disk_size:
            instance_limits = []
            for instance_type in self.instanceIds:
                limit = CPU_INSTANCE_DISK_LIMITS[instance_type]
                instance_limits.append(f"{instance_type.value}: max {limit}GB")

            raise ValueError(
                f"Container disk size {self.template.containerDiskInGb}GB exceeds the maximum "
                f"allowed for CPU instances. Instance limits: {', '.join(instance_limits)}. "
                f"Maximum allowed: {max_allowed_disk_size}GB"
            )

    def _sync_cpu_fields(self):
        """Sync CPU-specific fields, overriding GPU defaults."""
        # Override GPU-specific fields for CPU
        if hasattr(self, "gpuCount"):
            self.gpuCount = 0
        if hasattr(self, "allowedCudaVersions"):
            self.allowedCudaVersions = ""
        if hasattr(self, "gpuIds"):
            self.gpuIds = ""

    @field_serializer("instanceIds")
    def serialize_instance_ids(
        self, value: Optional[List[CpuInstanceType]]
    ) -> Optional[List[str]]:
        """Convert CpuInstanceType enums to strings."""
        if value is None:
            return None
        return [item.value if hasattr(item, "value") else str(item) for item in value]


class CpuServerlessEndpoint(CpuEndpointMixin, ServerlessEndpoint):
    """
    CPU-only serverless endpoint with automatic disk sizing and validation.
    Represents a CPU-only serverless endpoint distinct from a live serverless.
    """

    # CPU endpoints don't use GPU-specific fields, so exclude them from API payload
    # This prevents the RunPod GraphQL API from rejecting CPU endpoints with GPU-specific fields
    # Note: instanceIds is NOT in _input_only, so it will be sent to the API
    _input_only = {
        "id",
        "cudaVersions",  # GPU-specific, exclude from API payload
        "datacenter",
        "env",
        "gpus",  # Inherited from parent, but always None for CPU endpoints
        "gpuIds",  # GPU-specific API field, exclude from payload
        "gpuCount",  # GPU-specific API field, exclude from payload
        "allowedCudaVersions",  # GPU-specific API field, exclude from payload
        "flashboot",
        "flashEnvironmentId",
        "imageName",
        "networkVolume",
        "python_version",
    }

    # Override GPU field from parent to None for CPU endpoints
    gpus: Optional[List] = None
    instanceIds: Optional[List[CpuInstanceType]] = [CpuInstanceType.CPU3G_2_8]

    @property
    def config_hash(self) -> str:
        """Get hash of current configuration excluding GPU-specific fields.

        CPU endpoints need GPU fields in _input_only to exclude them from API payload,
        but these fields should not be included in config_hash to avoid false drift
        detection. This override computes the hash using only CPU-relevant fields.
        """
        # CPU-relevant fields for config hash, excluding 'env' to prevent false drift
        # (env is dynamically computed from .env file at initialization time)
        cpu_fields = {
            "datacenter",
            "flashboot",
            "flashEnvironmentId",
            "imageName",
            "gpus",
            "networkVolume",
        }
        config_dict = self.model_dump(
            exclude_none=True, include=cpu_fields, mode="json"
        )
        config_str = json.dumps(config_dict, sort_keys=True)
        hash_obj = hashlib.md5(f"{self.__class__.__name__}:{config_str}".encode())
        return hash_obj.hexdigest()

    def _create_new_template(self) -> PodTemplate:
        """Create a new PodTemplate with CPU-appropriate disk sizing."""
        template = PodTemplate(
            name=self.resource_id,
            imageName=self.imageName,
            env=KeyValuePair.from_dict(self.env or get_env_vars()),
        )
        # Apply CPU-specific disk sizing
        self._apply_cpu_disk_sizing(template)
        return template

    def _configure_existing_template(self) -> None:
        """Configure an existing template with necessary overrides and CPU sizing."""
        if self.template is None:
            return

        self.template.name = f"{self.resource_id}__{self.template.resource_id}"

        if self.imageName:
            self.template.imageName = self.imageName
        if self.env:
            self.template.env = KeyValuePair.from_dict(self.env)

        # Apply CPU-specific disk sizing
        self._apply_cpu_disk_sizing(self.template)

    @model_validator(mode="after")
    def set_serverless_template(self):
        # Sync CPU-specific fields first
        self._sync_cpu_fields()

        if not any([self.imageName, self.template, self.templateId]):
            raise ValueError(
                "Either imageName, template, or templateId must be provided"
            )

        if not self.templateId and not self.template:
            self.template = self._create_new_template()
        elif self.template:
            self._configure_existing_template()

        # Validate container disk size for CPU instances
        self.validate_cpu_container_disk_size()

        return self
