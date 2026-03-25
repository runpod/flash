import hashlib
import logging
from enum import Enum
from typing import Optional, Dict, Any

from pydantic import (
    ConfigDict,
    Field,
    field_validator,
    field_serializer,
    model_validator,
)

from ..api.runpod import RunpodRestClient
from .base import DeployableResource
from .constants import CONSOLE_BASE_URL
from .resource_manager import ResourceManager

log = logging.getLogger(__name__)


class DataCenter(str, Enum):
    """Enum representing available RunPod data centers."""

    # north america
    US_CA_2 = "US-CA-2"
    US_GA_2 = "US-GA-2"
    US_IL_1 = "US-IL-1"
    US_KS_2 = "US-KS-2"
    US_MD_1 = "US-MD-1"
    US_MO_1 = "US-MO-1"
    US_MO_2 = "US-MO-2"
    US_NC_1 = "US-NC-1"
    US_NC_2 = "US-NC-2"
    US_NE_1 = "US-NE-1"
    US_WA_1 = "US-WA-1"

    # europe
    EU_CZ_1 = "EU-CZ-1"
    EU_RO_1 = "EU-RO-1"
    EUR_IS_1 = "EUR-IS-1"
    EUR_NO_1 = "EUR-NO-1"

    @classmethod
    def from_string(cls, value: str) -> "DataCenter":
        """Parse a datacenter ID string into a DataCenter enum.

        Accepts the canonical form (e.g. "EU-RO-1") as well as common
        variations like lowercase or underscore-separated.
        """
        normalized = value.strip().upper().replace("_", "-")
        try:
            return cls(normalized)
        except ValueError:
            valid = ", ".join(dc.value for dc in cls)
            raise ValueError(
                f"Unknown datacenter '{value}'. Valid datacenters: {valid}"
            )


# data centers that support CPU serverless endpoints
CPU_DATACENTERS: frozenset[DataCenter] = frozenset(
    {
        DataCenter.EU_RO_1,
    }
)


class NetworkVolume(DeployableResource):
    """
    NetworkVolume resource for creating and managing Runpod network volumes.

    This class handles the creation, deployment, and management of network volumes
    that can be attached to serverless resources. Supports idempotent deployment
    where multiple volumes with the same name will reuse existing volumes.

    """

    _hashed_fields = {
        "dataCenterId",
        "size",
        "name",
    }

    model_config = ConfigDict(extra="forbid")

    # public alias -- users pass datacenter=, which syncs to dataCenterId for the API
    datacenter: Optional[DataCenter] = Field(default=None, exclude=True)
    dataCenterId: DataCenter = Field(default=DataCenter.EU_RO_1)

    id: Optional[str] = Field(default=None)
    name: Optional[str] = None
    size: Optional[int] = Field(default=100, gt=0, le=4096)  # Size in GB

    @field_validator("name")
    @classmethod
    def validate_name_not_empty(cls, value: Optional[str]) -> Optional[str]:
        """Reject empty/whitespace-only volume names."""
        if value is None:
            return value
        if not value.strip():
            raise ValueError("name must not be empty or whitespace-only")
        return value

    @model_validator(mode="before")
    @classmethod
    def sync_datacenter_alias(cls, data):
        """Allow datacenter= as a user-friendly alias for dataCenterId."""
        if isinstance(data, dict):
            dc = data.pop("datacenter", None)
            if dc is not None and "dataCenterId" not in data:
                data["dataCenterId"] = dc
        return data

    @model_validator(mode="after")
    def require_name_or_id(self):
        """Either name or id must be provided."""
        if not self.name and not self.id:
            raise ValueError("either 'name' or 'id' must be provided")
        return self

    def __str__(self) -> str:
        return f"{self.__class__.__name__}:{self.id}"

    @property
    def resource_id(self) -> str:
        """Unique resource ID based on name and datacenter for idempotent behavior."""
        resource_type = self.__class__.__name__
        if self.name:
            config_key = f"{self.name}:{self.dataCenterId.value}"
        else:
            config_key = f"id:{self.id}"
        hash_obj = hashlib.md5(f"{resource_type}:{config_key}".encode())
        return f"{resource_type}_{hash_obj.hexdigest()}"

    @field_serializer("dataCenterId")
    def serialize_data_center_id(self, value: Optional[DataCenter]) -> Optional[str]:
        """Convert DataCenter enum to string."""
        return value.value if value is not None else None

    @property
    def is_created(self) -> bool:
        "Returns True if the network volume already exists."
        return self.id is not None

    @property
    def url(self) -> str:
        """
        Returns the URL for the network volume resource.
        """
        if not self.id:
            raise ValueError("Network volume ID is not set")
        return f"{CONSOLE_BASE_URL}/user/storage"

    async def is_deployed(self) -> bool:
        """
        Checks if the network volume resource is deployed and available.
        """
        return self.id is not None

    def _normalize_volumes_response(self, volumes_response) -> list:
        """Normalize API response to list format."""
        if isinstance(volumes_response, list):
            return volumes_response
        return volumes_response.get("networkVolumes", [])

    def _find_matching_volume(self, existing_volumes: list) -> Optional[dict]:
        """Find existing volume matching name and datacenter."""
        for volume_data in existing_volumes:
            if (
                volume_data.get("name") == self.name
                and volume_data.get("dataCenterId") == self.dataCenterId.value
            ):
                return volume_data
        return None

    async def _find_existing_volume(self, client) -> Optional["NetworkVolume"]:
        """Check for existing volume with same name and datacenter."""
        if not self.name:
            return None

        log.debug(f"Checking for existing network volume with name: {self.name}")
        volumes_response = await client.list_network_volumes()
        existing_volumes = self._normalize_volumes_response(volumes_response)

        if matching_volume := self._find_matching_volume(existing_volumes):
            log.debug(
                f"Found existing network volume: {matching_volume.get('id')} with name '{self.name}'"
            )
            # Update our instance with the existing volume's ID
            self.id = matching_volume.get("id")
            return self

        return None

    async def _create_new_volume(self, client) -> "NetworkVolume":
        """Create a new network volume."""
        log.debug(f"Creating new network volume: {self.name or 'unnamed'}")
        payload = self.model_dump(exclude_none=True)
        result = await client.create_network_volume(payload)

        if volume := self.__class__(**result):
            return volume

        raise ValueError("Deployment failed, no volume was created.")

    async def _do_deploy(self) -> "DeployableResource":
        """
        Deploys the network volume resource using the provided configuration.
        Returns a DeployableResource object.
        """
        try:
            # If the resource is already deployed, return it
            if await self.is_deployed():
                log.debug(f"{self} exists")
                return self

            async with RunpodRestClient() as client:
                # Check for existing volume first
                if existing_volume := await self._find_existing_volume(client):
                    return existing_volume

                # No existing volume found, create a new one
                return await self._create_new_volume(client)

        except Exception as e:
            log.error(f"{self} failed to deploy: {e}")
            raise

    async def deploy(self) -> "DeployableResource":
        resource_manager = ResourceManager()
        resource = await resource_manager.get_or_deploy_resource(self)
        # hydrate the id onto the resource so it's usable when this is called directly
        # on a config
        self.id = resource.id
        return self

    async def undeploy(self) -> Dict[str, Any]:
        """
        Undeploy network volume.

        Returns:
            True if successfully undeployed, False otherwise

        Raises:
            NotImplementedError: NetworkVolume undeploy is not yet supported
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} undeploy is not yet supported. "
            "Network volumes must be manually deleted via RunPod UI or API."
        )

    async def _do_undeploy(self) -> bool:
        """
        Undeploy network volume.

        Returns:
            True if successfully undeployed, False otherwise

        Raises:
            NotImplementedError: NetworkVolume undeploy is not yet supported
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} undeploy is not yet supported. "
            "Network volumes must be manually deleted via RunPod UI or API."
        )
