import asyncio
import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Set

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from runpod.endpoint.runner import Job

from ..api.runpod import RunpodGraphQLClient
from ..utils.backoff import get_backoff_delay
from .base import DeployableResource
from .cloud import runpod
from .constants import CONSOLE_URL
from .environment import EnvironmentVars
from .cpu import CpuInstanceType
from .gpu import GpuGroup, GpuType
from .network_volume import NetworkVolume, DataCenter
from .template import KeyValuePair, PodTemplate
from .resource_manager import ResourceManager


# Prefix applied to endpoint names during live provisioning
LIVE_PREFIX = "live-"


# Environment variables are loaded from the .env file
def get_env_vars() -> Dict[str, str]:
    """
    Returns the environment variables from the .env file.
    {
        "KEY": "VALUE",
    }
    """
    env_vars = EnvironmentVars()
    return env_vars.get_env()


log = logging.getLogger(__name__)


def _is_prod_environment() -> bool:
    env = os.getenv("RUNPOD_ENV")
    if env:
        return env.lower() == "prod"
    api_base = os.getenv("RUNPOD_API_BASE_URL", "https://api.runpod.io")
    return "api.runpod.io" in api_base or "api.runpod.ai" in api_base


class ServerlessScalerType(Enum):
    QUEUE_DELAY = "QUEUE_DELAY"
    REQUEST_COUNT = "REQUEST_COUNT"


class ServerlessType(Enum):
    """
    Serverless endpoint execution model.

    QB (Queue-based): Traditional queue processing with automatic retries.
                      Requests are placed in queue and processed sequentially.
                      JSON input/output only. Higher latency but built-in error recovery.

    LB (Load-balancer): Direct HTTP routing to healthy workers.
                        Supports custom HTTP endpoints and any data format.
                        Lower latency but no automatic retries.
    """

    QB = "QB"
    LB = "LB"


class CudaVersion(Enum):
    V11_8 = "11.8"
    V12_0 = "12.0"
    V12_1 = "12.1"
    V12_2 = "12.2"
    V12_3 = "12.3"
    V12_4 = "12.4"
    V12_5 = "12.5"
    V12_6 = "12.6"
    V12_7 = "12.7"
    V12_8 = "12.8"


class ServerlessResource(DeployableResource):
    """
    Base class for GPU serverless resource
    """

    _input_only = {
        "id",
        "cudaVersions",
        "datacenter",
        "env",
        "gpus",
        "flashboot",
        "flashEnvironmentId",
        "imageName",
        "networkVolume",
    }

    _hashed_fields = {
        "datacenter",
        "env",
        "gpuIds",
        "executionTimeoutMs",
        "gpuCount",
        "locations",
        "name",
        "networkVolumeId",
        "scalerType",
        "scalerValue",
        "workersMax",
        "workersMin",
        "workersPFBTarget",
        "allowedCudaVersions",
        "type",
    }

    # Fields assigned by API that shouldn't affect drift detection
    # When adding new fields to ServerlessResource, evaluate if they are:
    # 1. User-specified (include in hash)
    # 2. API-assigned/runtime (add to RUNTIME_FIELDS)
    # 3. Dynamic identifiers (already excluded via "id")
    RUNTIME_FIELDS: ClassVar[Set[str]] = {
        "template",
        "templateId",
        "aiKey",
        "userId",
        "createdAt",
        "activeBuildid",
        "computeType",
        "hubRelease",
        "repo",
    }

    EXCLUDED_HASH_FIELDS: ClassVar[Set[str]] = {"id"}

    # === Input-only Fields ===
    cudaVersions: Optional[List[CudaVersion]] = []  # for allowedCudaVersions
    env: Optional[Dict[str, str]] = Field(default_factory=get_env_vars)
    flashboot: Optional[bool] = True
    gpus: Optional[List[GpuGroup | GpuType]] = [GpuGroup.ANY]  # for gpuIds
    imageName: Optional[str] = ""  # for template.imageName
    networkVolume: Optional[NetworkVolume] = None
    datacenter: DataCenter = Field(default=DataCenter.EU_RO_1)

    # === Input Fields ===
    executionTimeoutMs: Optional[int] = 0
    gpuCount: Optional[int] = 1
    idleTimeout: Optional[int] = 5
    instanceIds: Optional[List[CpuInstanceType]] = None
    locations: Optional[str] = None
    name: str
    networkVolumeId: Optional[str] = None
    flashEnvironmentId: Optional[str] = None
    scalerType: Optional[ServerlessScalerType] = ServerlessScalerType.QUEUE_DELAY
    scalerValue: Optional[int] = 4
    templateId: Optional[str] = None
    type: Optional[ServerlessType] = ServerlessType.QB
    workersMax: Optional[int] = 1
    workersMin: Optional[int] = 0
    workersPFBTarget: Optional[int] = 0

    # === Runtime Fields ===
    activeBuildid: Optional[str] = None
    aiKey: Optional[str] = None
    allowedCudaVersions: Optional[str] = ""
    computeType: Optional[str] = None
    createdAt: Optional[str] = None  # TODO: use datetime
    gpuIds: Optional[str] = ""
    hubRelease: Optional[str] = None
    repo: Optional[str] = None
    template: Optional[PodTemplate] = None
    userId: Optional[str] = None

    @field_serializer("env")
    def serialize_env(
        self, value: Optional[Dict[str, str]]
    ) -> Optional[List[Dict[str, str]]]:
        """Transform env dict to API format: list of {key, value} objects."""
        if value is None:
            return None
        return [{"key": k, "value": v} for k, v in value.items()]

    def __str__(self) -> str:
        return f"{self.__class__.__name__}:{self.id}"

    @property
    def url(self) -> str:
        if not self.id:
            raise ValueError("Missing self.id")
        return CONSOLE_URL % self.id

    @property
    def endpoint(self) -> runpod.Endpoint:
        """
        Returns the Runpod endpoint object for this serverless resource.
        """
        if not self.id:
            raise ValueError("Missing self.id")

        # Priority: request context > env var
        from ...runtime.api_key_context import get_api_key

        api_key = get_api_key() or os.getenv("RUNPOD_API_KEY")
        return runpod.Endpoint(self.id, api_key=api_key)

    @property
    def endpoint_url(self) -> str:
        base_url = self.endpoint.rp_client.endpoint_url_base
        return f"{base_url}/{self.id}"

    @field_serializer("scalerType")
    def serialize_scaler_type(
        self, value: Optional[ServerlessScalerType]
    ) -> Optional[str]:
        """Convert ServerlessScalerType enum to string.

        Handles both enum instances and pre-stringified values that may occur
        during nested model serialization or when values are already deserialized.
        """
        if value is None:
            return None
        return value.value if isinstance(value, ServerlessScalerType) else value

    @field_serializer("type")
    def serialize_type(self, value: Optional[ServerlessType]) -> Optional[str]:
        """Convert ServerlessType enum to string.

        Handles both enum instances and pre-stringified values that may occur
        during nested model serialization or when values are already deserialized.
        """
        if value is None:
            return None
        return value.value if isinstance(value, ServerlessType) else value

    @field_validator("gpus")
    @classmethod
    def validate_gpus(cls, value: List[GpuGroup | GpuType]) -> List[GpuGroup | GpuType]:
        """Expand ANY to all GPU groups"""
        if not value:
            return value
        if GpuGroup.ANY in value or GpuType.ANY in value:
            return GpuGroup.all()
        return value

    @property
    def config_hash(self) -> str:
        """Get config hash excluding env and runtime-assigned fields.

        Prevents false drift from:
        - Dynamic env vars computed at runtime
        - Runtime-assigned fields (template, templateId, aiKey, userId, etc.)

        Only hashes user-specified configuration, not server-assigned state.
        """
        import hashlib
        import json

        resource_type = self.__class__.__name__

        # Exclude runtime fields, env, and id from hash
        exclude_fields = (
            self.__class__.RUNTIME_FIELDS | self.__class__.EXCLUDED_HASH_FIELDS
        )
        config_dict = self.model_dump(
            exclude_none=True, exclude=exclude_fields, mode="json"
        )

        # Convert to JSON string for hashing
        config_str = json.dumps(config_dict, sort_keys=True)
        hash_obj = hashlib.md5(f"{resource_type}:{config_str}".encode())
        hash_value = hash_obj.hexdigest()

        return hash_value

    @model_validator(mode="after")
    def sync_input_fields(self):
        """Sync between temporary inputs and exported fields.

        Idempotent: Can be called multiple times safely without changing the result.
        """
        # Prepend live- prefix for live provisioning context
        # Must happen BEFORE flashboot suffix to get: live-my-endpoint-fb
        is_live_provisioning = (
            os.getenv("FLASH_IS_LIVE_PROVISIONING", "").lower() == "true"
        )

        if is_live_provisioning:
            # Remove existing live- prefixes for idempotency
            while self.name.startswith(LIVE_PREFIX):
                self.name = self.name[len(LIVE_PREFIX) :]
            # Add prefix once
            self.name = f"{LIVE_PREFIX}{self.name}"

        if self.flashboot and not self.name.endswith("-fb"):
            # Remove all trailing '-fb' suffixes, then add one
            while self.name.endswith("-fb"):
                self.name = self.name[:-3]
            self.name += "-fb"

        # Sync datacenter to locations field for API (only if not already set)
        # Allow overrides in non-prod via env
        env_locations = os.getenv("RUNPOD_DEFAULT_LOCATIONS")
        env_datacenter = os.getenv("RUNPOD_DEFAULT_DATACENTER")
        if env_locations:
            self.locations = env_locations
        elif not self.locations:
            if env_datacenter:
                try:
                    self.locations = DataCenter(env_datacenter).value
                except ValueError:
                    self.locations = env_datacenter
            elif _is_prod_environment():
                self.locations = self.datacenter.value

        # Validate datacenter consistency between endpoint and network volume
        if self.networkVolume and self.networkVolume.dataCenterId != self.datacenter:
            raise ValueError(
                f"Network volume datacenter ({self.networkVolume.dataCenterId.value}) "
                f"must match endpoint datacenter ({self.datacenter.value})"
            )

        if self.networkVolume and self.networkVolume.is_created:
            # Volume already exists, use its ID
            self.networkVolumeId = self.networkVolume.id

        self._sync_input_fields_gpu()

        return self

    def _has_cpu_instances(self) -> bool:
        """Check if endpoint has CPU instances configured.

        Returns:
            True if instanceIds field is present and non-empty, False otherwise.
        """
        return (
            hasattr(self, "instanceIds")
            and self.instanceIds is not None
            and len(self.instanceIds) > 0
        )

    def _get_cpu_disk_limit(self) -> Optional[int]:
        """Calculate max disk size for CPU instances.

        Returns:
            Maximum allowed disk size in GB, or None if no CPU instances.
        """
        if not self._has_cpu_instances():
            return None

        from .cpu import get_max_disk_size_for_instances

        return get_max_disk_size_for_instances(self.instanceIds)

    def _apply_smart_disk_sizing(self, template: PodTemplate) -> None:
        """Apply smart disk sizing based on instance type detection.

        If CPU instances are detected and using the default disk size,
        auto-sizes the disk to the CPU instance limit.

        Args:
            template: PodTemplate to configure.
        """
        cpu_limit = self._get_cpu_disk_limit()

        if cpu_limit is None:
            return  # No CPU instances, keep default

        # Auto-size if using default value
        default_disk_size = PodTemplate.model_fields["containerDiskInGb"].default
        if template.containerDiskInGb == default_disk_size:
            log.debug(
                f"Auto-sizing containerDiskInGb from {default_disk_size}GB "
                f"to {cpu_limit}GB (CPU instance limit)"
            )
            template.containerDiskInGb = cpu_limit

    def _validate_cpu_disk_size(self) -> None:
        """Validate disk size doesn't exceed CPU instance limits.

        Raises:
            ValueError: If disk size exceeds CPU instance limits.
        """
        cpu_limit = self._get_cpu_disk_limit()

        if cpu_limit is None:
            return  # No CPU instances, no validation needed

        if not self.template or not self.template.containerDiskInGb:
            return

        if self.template.containerDiskInGb > cpu_limit:
            from .cpu import CPU_INSTANCE_DISK_LIMITS

            instance_limits = [
                f"{inst.value}: max {CPU_INSTANCE_DISK_LIMITS[inst]}GB"
                for inst in self.instanceIds
            ]

            raise ValueError(
                f"Container disk size {self.template.containerDiskInGb}GB exceeds "
                f"the maximum allowed for CPU instances. "
                f"Instance limits: {', '.join(instance_limits)}. "
                f"Maximum allowed: {cpu_limit}GB. "
                f"Consider using CpuServerlessEndpoint or CpuLiveServerless classes "
                f"for CPU-only deployments."
            )

    def _create_new_template(self) -> PodTemplate:
        """Create a new PodTemplate with standard configuration."""
        return PodTemplate(
            name=self.resource_id,
            imageName=self.imageName,
            env=KeyValuePair.from_dict(self.env or get_env_vars()),
        )

    def _configure_existing_template(self) -> None:
        """Configure an existing template with necessary overrides."""
        if self.template is None:
            return

        self.template.name = f"{self.resource_id}__{self.template.resource_id}"

        if self.imageName:
            self.template.imageName = self.imageName
        if self.env:
            self.template.env = KeyValuePair.from_dict(self.env)

    async def _sync_graphql_object_with_inputs(
        self, returned_endpoint: "ServerlessResource"
    ):
        for _input_field in self._input_only or set():
            if getattr(self, _input_field) is not None:
                # sync input only fields stripped from gql request back to endpoint
                setattr(returned_endpoint, _input_field, getattr(self, _input_field))

        return returned_endpoint

    def _sync_input_fields_gpu(self):
        # GPU-specific fields (idempotent - only set if not already set)
        if self.gpus and not self.gpuIds:
            # Convert gpus list to gpuIds string
            self.gpuIds = GpuGroup.to_gpu_ids_str(self.gpus)
        elif self.gpuIds and not self.gpus:
            # Convert gpuIds string to gpus list (from backend responses)
            self.gpus = GpuGroup.from_gpu_ids_str(self.gpuIds)

        if self.cudaVersions and not self.allowedCudaVersions:
            # Convert cudaVersions list to allowedCudaVersions string
            self.allowedCudaVersions = ",".join(v.value for v in self.cudaVersions)
        elif self.allowedCudaVersions and not self.cudaVersions:
            # Convert allowedCudaVersions string to cudaVersions list (from backend responses)
            version_values = [
                v.strip() for v in self.allowedCudaVersions.split(",") if v.strip()
            ]
            self.cudaVersions = [CudaVersion(value) for value in version_values]

        return self

    async def _ensure_network_volume_deployed(self) -> None:
        """
        Ensures network volume is deployed and ready if one is specified.
        Updates networkVolumeId with the deployed volume ID.
        """
        if self.networkVolumeId:
            return

        if self.networkVolume:
            deployedNetworkVolume = await self.networkVolume.deploy()
            self.networkVolumeId = deployedNetworkVolume.id

    def is_deployed(self) -> bool:
        """
        Checks if the serverless resource is deployed and available.
        """
        try:
            if not self.id:
                return False

            response = self.endpoint.health()
            return response is not None
        except Exception as e:
            log.debug(f"Error checking {self}: {e}")
            return False

    def _payload_exclude(self) -> Set[str]:
        """Return fields that should be excluded from API payload.

        Some fields are input-only (used for configuration but not sent to API),
        but certain fields like flashEnvironmentId and env need to be sent despite
        being in _input_only, so they are explicitly re-included.
        """
        exclude_fields = set(self._input_only or set())
        exclude_fields.discard("flashEnvironmentId")
        exclude_fields.discard(
            "env"
        )  # Allow env to be sent to API for container environment
        return exclude_fields

    @staticmethod
    def _build_template_update_payload(
        template: PodTemplate, template_id: str
    ) -> Dict[str, Any]:
        """Build saveTemplate payload from template model.

        Keep this to fields supported by saveTemplate to avoid passing endpoint-only
        fields to the template mutation.
        """
        template_data = template.model_dump(exclude_none=True, mode="json")
        allowed_fields = {
            "name",
            "imageName",
            "containerDiskInGb",
            "dockerArgs",
            "env",
            "readme",
        }
        payload = {
            key: value for key, value in template_data.items() if key in allowed_fields
        }
        # savetemplate mutation requires volumeInGb, but for sls this is always 0
        payload["volumeInGb"] = 0
        payload["id"] = template_id
        return payload

    def _check_makes_remote_calls(self) -> bool:
        """Check if resource makes remote calls from build manifest.

        Reads flash_manifest.json to determine if this resource config
        has makes_remote_calls=True.

        Returns:
            True if makes remote calls, False if local-only,
            True (safe default) if manifest not found.
        """
        log.warning(f"[DEBUG] {self.name}: _check_makes_remote_calls() called")
        try:
            # Deployment time: .flash/flash_manifest.json in project directory
            manifest_path = Path.cwd() / ".flash" / "flash_manifest.json"
            log.warning(f"[DEBUG] {self.name}: Checking manifest at: {manifest_path}")

            if not manifest_path.exists():
                # Fallback for build directory (during tarball creation)
                manifest_path = Path.cwd() / "flash_manifest.json"
                log.warning(
                    f"[DEBUG] {self.name}: First path not found, trying: {manifest_path}"
                )

            if not manifest_path.exists():
                # Container runtime: copied to /app during container build
                manifest_path = Path("/app/flash_manifest.json")
                log.warning(
                    f"[DEBUG] {self.name}: Second path not found, trying: {manifest_path}"
                )

            if not manifest_path.exists():
                log.warning(
                    f"[DEBUG] {self.name}: NO MANIFEST FOUND, returning True (safe default)"
                )
                log.warning(
                    "Manifest not found during API key injection check. "
                    "Searched: .flash/flash_manifest.json, flash_manifest.json, /app/flash_manifest.json. "
                    "Defaulting to makes_remote_calls=True (safe default)."
                )
                return True  # Safe default

            log.warning(f"[DEBUG] {self.name}: Found manifest at: {manifest_path}")
            log.debug(f"Reading manifest from: {manifest_path}")

            with open(manifest_path) as f:
                manifest_data = json.load(f)

            resources = manifest_data.get("resources", {})
            log.warning(
                f"[DEBUG] {self.name}: Manifest contains resources: {list(resources.keys())}"
            )

            # Strip -fb suffix and live- prefix to match manifest name
            lookup_name = self.name
            if lookup_name.endswith("-fb"):
                lookup_name = lookup_name[:-3]
            if lookup_name.startswith(LIVE_PREFIX):
                lookup_name = lookup_name[len(LIVE_PREFIX) :]

            log.warning(
                f"[DEBUG] {self.name}: Looking up resource with name: '{lookup_name}' (original: '{self.name}')"
            )

            resource_config = resources.get(lookup_name)

            if not resource_config:
                log.warning(
                    f"[DEBUG] {self.name}: Resource '{lookup_name}' NOT FOUND in manifest, returning True"
                )
                log.debug(
                    f"Resource '{lookup_name}' (from '{self.name}') not in manifest, assuming makes_remote_calls=True"
                )
                return True  # Safe default

            makes_remote_calls = resource_config.get("makes_remote_calls", True)
            log.warning(
                f"[DEBUG] {self.name}: Found resource config, makes_remote_calls={makes_remote_calls}"
            )
            log.debug(
                f"Resource '{lookup_name}' (from '{self.name}') makes_remote_calls={makes_remote_calls}"
            )
            return makes_remote_calls

        except Exception as e:
            log.warning(f"[DEBUG] {self.name}: EXCEPTION reading manifest: {e}")
            log.warning(
                f"Failed to read manifest: {e}, assuming makes_remote_calls=True"
            )
            return True  # Safe default on error

    async def _do_deploy(self) -> "DeployableResource":
        """
        Deploys the serverless resource using the provided configuration.

        For queue-based endpoints that make remote calls, injects RUNPOD_API_KEY
        into environment variables if not already set.

        For load-balanced endpoints, retrieves API key from request context
        (set by middleware) to ensure per-request API keys are available.

        Returns a DeployableResource object.
        """
        log.warning(f"[DEBUG] {self.name}: _do_deploy() called, type={self.type}")
        try:
            # If the resource is already deployed, return it
            if self.is_deployed():
                log.warning(
                    f"[DEBUG] {self.name}: Resource already deployed, returning early"
                )
                log.debug(f"{self} exists")
                return self

            log.warning(
                f"[DEBUG] {self.name}: Resource not deployed, proceeding with deployment"
            )
            log.warning(
                f"[DEBUG] {self.name}: self.env keys at deploy start: {list(self.env.keys()) if self.env else None}"
            )

            # NOTE: Environment variables (including RUNPOD_API_KEY and FLASH_ENVIRONMENT_ID)
            # are now injected in resource_factory.py:create_resource_from_manifest()
            # before _do_deploy() is called. This provides a single source of truth for all env vars.

            # Ensure network volume is deployed first
            await self._ensure_network_volume_deployed()

            # Get API key from request context for LB endpoints during request processing
            api_key = None
            if self.type == ServerlessType.LB:
                from runpod_flash.runtime.api_key_context import get_api_key

                api_key = get_api_key()
                if api_key:
                    log.debug(
                        f"{self.name}: Using API key from request context for LB deployment"
                    )

            async with RunpodGraphQLClient(api_key=api_key) as client:
                exclude_fields = self._payload_exclude()
                log.warning(
                    f"[DEBUG] {self.name}: payload_exclude fields: {exclude_fields}"
                )
                log.warning(
                    f"[DEBUG] {self.name}: self.env RIGHT BEFORE model_dump: {list(self.env.keys()) if self.env else None}"
                )
                payload = self.model_dump(
                    exclude=exclude_fields, exclude_none=True, mode="json"
                )
                # Log if env is in payload and what keys it contains
                if "env" in payload:
                    env_keys = (
                        [item["key"] for item in payload["env"]]
                        if isinstance(payload["env"], list)
                        else list(payload["env"].keys())
                        if payload["env"]
                        else []
                    )
                    log.warning(
                        f"[DEBUG] {self.name}: payload contains 'env' with keys: {env_keys}"
                    )
                else:
                    log.warning(
                        f"[DEBUG] {self.name}: payload does NOT contain 'env' field"
                    )
                result = await client.save_endpoint(payload)

            if endpoint := self.__class__(**result):
                endpoint = await self._sync_graphql_object_with_inputs(endpoint)
                self.id = endpoint.id
                self.templateId = endpoint.templateId
                return endpoint

            raise ValueError("Deployment failed, no endpoint was returned.")

        except Exception as e:
            log.error(f"{self} failed to deploy: {e}")
            raise

    async def update(self, new_config: "ServerlessResource") -> "ServerlessResource":
        """Update existing endpoint with new configuration.

        Uses saveEndpoint mutation which handles both version-triggering and
        rolling changes. Version-triggering changes (GPU, template, volumes)
        automatically increment version and trigger worker recreation server-side.

        Args:
            new_config: New configuration to apply

        Returns:
            Updated ServerlessResource instance

        Raises:
            ValueError: If endpoint not deployed or update fails
        """
        if not self.id:
            raise ValueError("Cannot update: endpoint not deployed")

        try:
            resolved_template_id = self.templateId or new_config.templateId
            # Check for version-triggering changes
            if not self._has_structural_changes(new_config):
                log.info(f"Updating endpoint '{self.name}' (ID: {self.id})")

            # Ensure network volume is deployed if specified
            await new_config._ensure_network_volume_deployed()

            # Inject API key for endpoints that make remote calls
            # Both QB and LB endpoints need API keys when calling other endpoints
            if new_config.type in (ServerlessType.QB, ServerlessType.LB):
                env_dict = new_config.env or {}

                # Check if this resource makes remote calls (from build manifest)
                makes_remote_calls = new_config._check_makes_remote_calls()

                if makes_remote_calls:
                    # Inject RUNPOD_API_KEY if not already set
                    if "RUNPOD_API_KEY" not in env_dict:
                        # Use same API key resolution as RunpodGraphQLClient
                        # Priority: request context > env var
                        from ...runtime.api_key_context import get_api_key

                        api_key = get_api_key() or os.getenv("RUNPOD_API_KEY")
                        if api_key:
                            env_dict["RUNPOD_API_KEY"] = api_key
                            log.info(
                                f"{new_config.name}: Injected RUNPOD_API_KEY for remote calls "
                                f"(makes_remote_calls=True)"
                            )
                        else:
                            log.warning(
                                f"{new_config.name}: makes_remote_calls=True but RUNPOD_API_KEY not set. "
                                f"Remote calls to other endpoints will fail."
                            )

                new_config.env = env_dict

            # Inject FLASH_ENVIRONMENT_ID for any endpoint type that needs State Manager queries
            if new_config.type in (ServerlessType.QB, ServerlessType.LB):
                env_dict = new_config.env or {}
                if "FLASH_ENVIRONMENT_ID" not in env_dict:
                    flash_env_id = os.getenv("FLASH_ENVIRONMENT_ID")
                    if flash_env_id:
                        env_dict["FLASH_ENVIRONMENT_ID"] = flash_env_id
                        log.debug(
                            f"{new_config.name}: Injected FLASH_ENVIRONMENT_ID={flash_env_id}"
                        )
                new_config.env = env_dict

            async with RunpodGraphQLClient() as client:
                # Include the endpoint ID to trigger update
                payload = new_config.model_dump(
                    exclude=new_config._payload_exclude(),
                    exclude_none=True,
                    mode="json",
                )
                payload["id"] = self.id  # Critical: include ID for update

                result = await client.save_endpoint(payload)
                resolved_template_id = (
                    result.get("templateId") or self.templateId or new_config.templateId
                )

                if new_config.template:
                    if resolved_template_id:
                        template_payload = self._build_template_update_payload(
                            new_config.template, resolved_template_id
                        )
                        await client.update_template(template_payload)
                        log.debug(
                            f"Updated template '{resolved_template_id}' for endpoint '{self.name}'"
                        )
                    else:
                        log.warning(
                            "Template provided during endpoint update but no templateId could "
                            "be resolved; skipping separate saveTemplate call"
                        )

            if updated := self.__class__(**result):
                if not updated.templateId:
                    updated.templateId = (
                        resolved_template_id or self.templateId or new_config.templateId
                    )
                # Keep local input-only state on the hydrated model. The GraphQL
                # response does not include many user-provided fields (for example
                # env, networkVolume, datacenter), and dropping them causes
                # repeated false drift on subsequent deploys.
                updated = await new_config._sync_graphql_object_with_inputs(updated)
                log.info(f"Successfully updated endpoint '{self.name}' (ID: {self.id})")
                return updated

            raise ValueError("Update failed, no endpoint was returned.")

        except Exception as e:
            log.error(f"Failed to update {self.name}: {e}")
            raise

    def _has_structural_changes(self, new_config: "ServerlessResource") -> bool:
        """Check if config changes are version-triggering.

        Version-triggering changes cause server-side version increment and
        worker recreation:
        - Image changes (imageName via templateId)
        - GPU configuration (gpus, gpuIds, allowedCudaVersions, gpuCount)
        - Hardware allocation (instanceIds, locations)
        - Storage changes (networkVolumeId)
        - Flashboot toggle

        Rolling changes (no version increment):
        - Worker scaling (workersMin, workersMax)
        - Scaler configuration (scalerType, scalerValue)
        - Timeout values (idleTimeout, executionTimeoutMs)
        - Environment variables (env)

        Note: This method is now informational for logging. The actual
        version-triggering logic runs server-side when saveEndpoint is called.

        Runtime fields (template, templateId, aiKey, userId) are excluded
        to prevent false positives when comparing deployed vs new config.

        Args:
            new_config: New configuration to compare against

        Returns:
            True if version-triggering changes detected (workers will be recreated)
        """
        structural_fields = [
            "gpus",
            "gpuIds",
            "imageName",
            "flashboot",
            "allowedCudaVersions",
            "cudaVersions",
            "instanceIds",
        ]

        for field in structural_fields:
            old_val = getattr(self, field, None)
            new_val = getattr(new_config, field, None)

            # Handle list comparison
            if isinstance(old_val, list) and isinstance(new_val, list):
                if sorted(str(v) for v in old_val) != sorted(str(v) for v in new_val):
                    return True
            # Handle other types
            elif old_val != new_val:
                return True

        return False

    async def deploy(self) -> "DeployableResource":
        resource_manager = ResourceManager()
        resource = await resource_manager.get_or_deploy_resource(self)
        # hydrate the id onto the resource so it's usable when this is called directly
        # on a config
        self.id = resource.id
        self.templateId = getattr(resource, "templateId", None)
        return self

    async def _do_undeploy(self) -> bool:
        """
        Undeploys (deletes) the serverless endpoint.

        If deletion fails, verifies the endpoint still exists. If not, treats it as
        successfully undeployed (handles cases where endpoint was deleted externally).

        Returns:
            True if successfully undeployed or endpoint doesn't exist, False otherwise
        """
        if not self.id:
            log.warning(f"{self} has no endpoint ID, cannot undeploy")
            return False

        try:
            async with RunpodGraphQLClient() as client:
                result = await client.delete_endpoint(self.id)
                success = result.get("success", False)

                if success:
                    log.debug(f"{self} successfully undeployed")
                    return True
                else:
                    log.debug(f"{self} failed to undeploy")
                    return False

        except Exception as e:
            log.debug(f"{self} failed to undeploy: {e}")

            # Deletion failed. Check if endpoint still exists.
            # If it doesn't exist, treat as successful cleanup (orphaned endpoint).
            try:
                async with RunpodGraphQLClient() as client:
                    if not await client.endpoint_exists(self.id):
                        log.debug(
                            f"{self} no longer exists on RunPod, removing from cache"
                        )
                        return True
            except Exception as check_error:
                log.warning(f"Could not verify endpoint existence: {check_error}")

            return False

    async def undeploy(self) -> Dict[str, Any]:
        resource_manager = ResourceManager()
        result = await resource_manager.undeploy_resource(self.resource_id)
        log.debug(f"undeployment result: {result}")
        return result

    async def run_sync(self, payload: Dict[str, Any]) -> "JobOutput":
        """
        Executes a serverless endpoint request with the payload.
        Returns a JobOutput object.
        """
        if not self.id:
            raise ValueError("Serverless is not deployed")

        def _fetch_job():
            return self.endpoint.rp_client.post(
                f"{self.id}/runsync", payload, timeout=60
            )

        try:
            # log.debug(f"[{self}] Payload: {payload}")

            log.debug(f"{self} | API /run_sync")
            response = await asyncio.to_thread(_fetch_job)
            return JobOutput(**response)

        except Exception as e:
            health = await asyncio.to_thread(self.endpoint.health)
            health = ServerlessHealth(**health)
            log.debug(f"{self} | Health {health.workers.status}")
            log.error(f"{self} | Exception: {e}")
            raise

    async def run(self, payload: Dict[str, Any]) -> "JobOutput":
        """
        Executes a serverless endpoint async request with the payload.
        Returns a JobOutput object.
        """
        if not self.id:
            raise ValueError("Serverless is not deployed")

        job: Optional[Job] = None

        try:
            # log.debug(f"[{self}] Payload: {payload}")

            # Create a job using the endpoint
            log.debug(f"{self} | API /run")
            job = await asyncio.to_thread(self.endpoint.run, request_input=payload)

            log_subgroup = f"Job:{job.job_id}"

            log.debug(f"{self} | Started {log_subgroup}")

            current_pace = 0
            attempt = 0
            job_status = Status.UNKNOWN
            last_status = job_status

            # Poll for job status
            while True:
                await asyncio.sleep(current_pace)

                # Check job status
                job_status = await asyncio.to_thread(job.status)

                if last_status == job_status:
                    # nothing changed, increase the gap
                    attempt += 1
                    indicator = "." * (attempt // 2) if attempt % 2 == 0 else ""
                    if indicator:
                        log.debug(f"{log_subgroup} | {indicator}")
                else:
                    # status changed, reset the gap
                    log.debug(f"{log_subgroup} | Status: {job_status}")
                    attempt = 0

                last_status = job_status

                # Adjust polling pace appropriately
                current_pace = get_backoff_delay(attempt)

                if job_status in ("COMPLETED", "FAILED", "CANCELLED"):
                    response = await asyncio.to_thread(job._fetch_job)
                    return JobOutput(**response)

        except Exception as e:
            if job and job.job_id:
                log.debug(f"{self} | Cancelling job {job.job_id}")
                await asyncio.to_thread(job.cancel)

            log.error(f"{self} | Exception: {e}")
            raise


class ServerlessEndpoint(ServerlessResource):
    """
    Represents a serverless endpoint distinct from a live serverless.
    Inherits from ServerlessResource.
    """

    @model_validator(mode="after")
    def validate_instance_mutual_exclusivity(self):
        """Ensure gpuIds and instanceIds are mutually exclusive.

        When instanceIds is specified, clears GPU configuration since CPU and GPU
        are mutually exclusive resources. Prevents mixing GPU and CPU configurations.
        """
        has_cpu = (
            hasattr(self, "instanceIds")
            and self.instanceIds is not None
            and len(self.instanceIds) > 0
        )

        if has_cpu:
            # Clear GPU configuration if CPU instances are specified
            # This makes CPU intent explicit
            self.gpus = []
            self.gpuIds = ""
            self.gpuCount = 0

        return self

    @model_validator(mode="after")
    def set_serverless_template(self):
        """Create template from imageName if not provided.

        Must run after sync_input_fields to ensure all input fields are synced.
        Applies smart disk sizing and validates configuration.
        """
        if not any([self.imageName, self.template, self.templateId]):
            raise ValueError(
                "Either imageName, template, or templateId must be provided"
            )

        if not self.templateId and not self.template:
            self.template = self._create_new_template()
            # Apply smart disk sizing to new template
            self._apply_smart_disk_sizing(self.template)
        elif self.template:
            self._configure_existing_template()
            # Apply smart disk sizing to existing template
            self._apply_smart_disk_sizing(self.template)

        # Validate CPU disk size if applicable
        self._validate_cpu_disk_size()

        return self


class JobOutput(BaseModel):
    id: str
    workerId: str
    status: str
    delayTime: int
    executionTime: int
    output: Optional[Any] = None
    error: Optional[str] = ""

    def model_post_init(self, _: Any) -> None:
        log_group = f"Worker:{self.workerId}"
        log.debug(f"{log_group} | Delay Time: {self.delayTime} ms")
        log.debug(f"{log_group} | Execution Time: {self.executionTime} ms")


class Status(str, Enum):
    READY = "READY"
    INITIALIZING = "INITIALIZING"
    THROTTLED = "THROTTLED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class WorkersHealth(BaseModel):
    idle: int
    initializing: int
    ready: int
    running: int
    throttled: int
    unhealthy: int

    @property
    def status(self) -> Status:
        if self.ready or self.idle or self.running:
            return Status.READY

        if self.initializing:
            return Status.INITIALIZING

        if self.throttled:
            return Status.THROTTLED

        if self.unhealthy:
            return Status.UNHEALTHY

        return Status.UNKNOWN


class JobsHealth(BaseModel):
    completed: int
    failed: int
    inProgress: int
    inQueue: int
    retried: int


class ServerlessHealth(BaseModel):
    workers: WorkersHealth
    jobs: JobsHealth

    @property
    def is_ready(self) -> bool:
        return self.workers.status == Status.READY
