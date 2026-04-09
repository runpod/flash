"""
Unit tests for ServerlessResource and related classes.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict

from runpod_flash.core.resources.serverless import (
    ServerlessResource,
    ServerlessEndpoint,
    ServerlessScalerType,
    ServerlessType,
    CudaVersion,
    JobOutput,
    WorkersHealth,
    JobsHealth,
    ServerlessHealth,
    Status,
)
from runpod_flash.core.resources.serverless_cpu import CpuServerlessEndpoint
from runpod_flash.core.resources.gpu import GpuGroup
from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.network_volume import NetworkVolume, DataCenter
from runpod_flash.core.resources.request_logs import (
    QBRequestLogBatch,
    QBRequestLogPhase,
)
from runpod_flash.core.resources.worker_availability_diagnostic import (
    WorkerAvailabilityResult,
)
from runpod_flash.core.resources.template import KeyValuePair, PodTemplate


class TestServerlessResource:
    """Test ServerlessResource base class functionality."""

    @pytest.fixture
    def basic_serverless_config(self) -> Dict[str, Any]:
        """Basic serverless configuration for testing."""
        return {
            "name": "test-serverless",
            "gpuCount": 1,
            "workersMax": 3,
            "workersMin": 0,
        }

    @pytest.fixture
    def mock_runpod_client(self):
        """Mock RunpodGraphQLClient."""
        client = AsyncMock()
        client.save_endpoint = AsyncMock()
        client.update_template = AsyncMock()
        return client

    def test_serverless_resource_initialization(self, basic_serverless_config):
        """Test basic initialization of ServerlessResource."""
        serverless = ServerlessResource(**basic_serverless_config)

        assert serverless.name == "test-serverless"
        assert serverless.flashBootType == "FLASHBOOT"
        assert serverless.gpuCount == 1
        assert serverless.workersMax == 3
        assert serverless.workersMin == 0
        assert serverless.scalerType == ServerlessScalerType.QUEUE_DELAY
        assert serverless.scalerValue == 4
        assert serverless.flashboot is True

    def test_str_representation(self, basic_serverless_config):
        """Test string representation of ServerlessResource."""
        serverless = ServerlessResource(**basic_serverless_config)
        serverless.id = "test-id-123"

        assert str(serverless) == "ServerlessResource:test-id-123"

    def test_url_property_with_id(self, basic_serverless_config):
        """Test URL property when ID is set."""
        serverless = ServerlessResource(**basic_serverless_config)
        serverless.id = "test-id-123"

        assert "test-id-123" in serverless.url

    def test_url_property_without_id_raises_error(self, basic_serverless_config):
        """Test URL property raises error when ID is not set."""
        serverless = ServerlessResource(**basic_serverless_config)

        with pytest.raises(ValueError, match="Missing self.id"):
            _ = serverless.url

    def test_endpoint_property_with_id(self, basic_serverless_config):
        """Test endpoint property when ID is set."""
        serverless = ServerlessResource(**basic_serverless_config)
        serverless.id = "test-id-123"

        # Patch runpod.Endpoint since runpod is now lazy-loaded
        with patch("runpod.Endpoint") as mock_endpoint:
            endpoint = serverless.endpoint
            assert endpoint is not None
            mock_endpoint.assert_called_once_with("test-id-123")

    def test_endpoint_property_without_id_raises_error(self, basic_serverless_config):
        """Test endpoint property raises error when ID is not set."""
        serverless = ServerlessResource(**basic_serverless_config)

        with pytest.raises(ValueError, match="Missing self.id"):
            _ = serverless.endpoint

    def test_resource_id_changes_only_for_hashed_fields(self):
        """Ensure resource_id is stable based on _hashed_fields config.

        resource_id is computed from _hashed_fields which exclude runtime/server-assigned fields.
        Create new instances with same env to test different configs.
        """
        # Fixed env to ensure consistency
        env = {"FLASH_IMAGE_TAG": "test-123"}

        # Original config
        serverless1 = ServerlessResource(name="hash-test", flashboot=False, env=env)
        id1 = serverless1.resource_id

        # Same config except runtime field shouldn't change resource_id
        serverless2 = ServerlessResource(name="hash-test", flashboot=False, env=env)
        serverless2.activeBuildid = "build-123"  # runtime field (not in _hashed_fields)
        id2 = serverless2.resource_id
        assert id1 == id2

        # Different hashed field should produce different resource_id
        serverless3 = ServerlessResource(
            name="hash-test", flashboot=False, workersMax=4, env=env
        )
        id3 = serverless3.resource_id
        assert id1 != id3


class TestServerlessResourceNetworkVolume:
    """Test network volume integration in ServerlessResource."""

    @pytest.fixture
    def serverless_with_volume(self):
        """ServerlessResource with a network volume."""
        volume = NetworkVolume(name="test-volume", size=50)
        return ServerlessResource(
            name="test-serverless",
            networkVolume=volume,
        )

    @pytest.fixture
    def mock_network_volume(self):
        """Mock NetworkVolume for testing."""
        volume = AsyncMock(spec=NetworkVolume)
        volume.deploy = AsyncMock()
        volume.is_created = False
        volume.id = None
        return volume

    def test_sync_input_fields_with_created_volume(self):
        """Test sync_input_fields sets networkVolumeId when volume is created."""
        volume = NetworkVolume(name="test-volume", size=50)
        volume.id = "vol-123"
        # Use the actual property that checks is_created
        with patch.object(
            type(volume), "is_created", new_callable=lambda: property(lambda self: True)
        ):
            serverless = ServerlessResource(
                name="test-serverless",
                networkVolume=volume,
            )

            # The model validator should have set the networkVolumeId
            assert serverless.networkVolumeId == "vol-123"

    @pytest.mark.asyncio
    async def test_ensure_network_volume_deployed_with_existing_id(self):
        """Test _ensure_network_volume_deployed returns early if networkVolumeId exists."""
        serverless = ServerlessResource(
            name="test-serverless",
            networkVolumeId="vol-existing-123",
        )

        await serverless._ensure_network_volume_deployed()

        # Should return early, no volume creation
        assert serverless.networkVolumeId == "vol-existing-123"

    @pytest.mark.asyncio
    async def test_ensure_network_volume_deployed_no_volume_does_nothing(self):
        """Test _ensure_network_volume_deployed does nothing when no volume provided."""
        serverless = ServerlessResource(name="test-serverless")

        await serverless._ensure_network_volume_deployed()

        # Should not set any network volume ID since no volume was provided
        assert serverless.networkVolumeId is None
        assert serverless.networkVolume is None

    @pytest.mark.asyncio
    async def test_ensure_network_volume_deployed_uses_existing_volume(self):
        """Test _ensure_network_volume_deployed uses existing volume."""
        volume = NetworkVolume(name="existing-volume", size=50)
        serverless = ServerlessResource(
            name="test-serverless",
            networkVolume=volume,
        )

        with patch.object(NetworkVolume, "deploy") as mock_deploy:
            deployed_volume = NetworkVolume(name="existing-volume", size=50)
            deployed_volume.id = "vol-existing-456"
            mock_deploy.return_value = deployed_volume

            await serverless._ensure_network_volume_deployed()

            assert serverless.networkVolumeId == "vol-existing-456"
            mock_deploy.assert_called_once()


class TestMultiVolumeDeployPath:
    """Test _ensure_network_volume_deployed with multiple volumes and payload injection."""

    @pytest.mark.asyncio
    async def test_multi_volume_deploys_all_and_collects_ids(self):
        vol_a = NetworkVolume(name="vol-a", size=50, dataCenterId=DataCenter.EU_RO_1)
        vol_b = NetworkVolume(name="vol-b", size=50, dataCenterId=DataCenter.US_GA_2)

        serverless = ServerlessResource(
            name="test",
            networkVolumes=[vol_a, vol_b],
            datacenter=[DataCenter.EU_RO_1, DataCenter.US_GA_2],
        )

        async def fake_deploy(self_vol):
            self_vol.id = {"vol-a": "vol-aaa", "vol-b": "vol-bbb"}[self_vol.name]
            return self_vol

        with patch.object(NetworkVolume, "deploy", fake_deploy):
            await serverless._ensure_network_volume_deployed()

        assert serverless._deployed_volume_ids == ["vol-aaa", "vol-bbb"]
        assert serverless.networkVolumeId == "vol-aaa"

    @pytest.mark.asyncio
    async def test_multi_volume_skips_already_created(self):
        vol_a = NetworkVolume(name="vol-a", size=50, dataCenterId=DataCenter.EU_RO_1)
        vol_a.id = "vol-aaa"
        vol_b = NetworkVolume(name="vol-b", size=50, dataCenterId=DataCenter.US_GA_2)

        serverless = ServerlessResource(
            name="test",
            networkVolumes=[vol_a, vol_b],
            datacenter=[DataCenter.EU_RO_1, DataCenter.US_GA_2],
        )

        deploy_calls = []

        async def fake_deploy(self_vol):
            deploy_calls.append(self_vol.name)
            self_vol.id = "vol-bbb"
            return self_vol

        with patch.object(NetworkVolume, "deploy", fake_deploy):
            await serverless._ensure_network_volume_deployed()

        # vol_a already had an id, so deploy should only be called for vol_b
        assert deploy_calls == ["vol-b"]
        assert "vol-aaa" in serverless._deployed_volume_ids
        assert "vol-bbb" in serverless._deployed_volume_ids

    @pytest.mark.asyncio
    async def test_multi_volume_dedup_with_existing_volume_id(self):
        """Existing networkVolumeId is not duplicated in _deployed_volume_ids."""
        vol_a = NetworkVolume(name="vol-a", size=50, dataCenterId=DataCenter.EU_RO_1)
        vol_a.id = "vol-aaa"

        serverless = ServerlessResource(
            name="test",
            networkVolumeId="vol-aaa",
            networkVolumes=[vol_a],
            datacenter=[DataCenter.EU_RO_1],
        )

        await serverless._ensure_network_volume_deployed()

        assert serverless._deployed_volume_ids == ["vol-aaa"]

    def test_deploy_payload_injects_network_volume_ids(self):
        """When >1 deployed volume, payload has networkVolumeIds and no networkVolumeId."""
        serverless = ServerlessResource(name="test")
        serverless._deployed_volume_ids = ["vol-aaa", "vol-bbb"]

        payload = serverless.model_dump(
            exclude=serverless._payload_exclude(), exclude_none=True, mode="json"
        )

        # simulate the injection logic from _do_deploy
        deployed_ids = serverless._deployed_volume_ids
        if len(deployed_ids) > 1:
            payload["networkVolumeIds"] = [
                {"networkVolumeId": vid} for vid in deployed_ids
            ]
            payload.pop("networkVolumeId", None)

        assert payload["networkVolumeIds"] == [
            {"networkVolumeId": "vol-aaa"},
            {"networkVolumeId": "vol-bbb"},
        ]
        assert "networkVolumeId" not in payload

    def test_single_volume_payload_uses_singular_field(self):
        """When 1 deployed volume, payload uses networkVolumeId (no networkVolumeIds)."""
        serverless = ServerlessResource(
            name="test",
            networkVolumeId="vol-aaa",
        )
        serverless._deployed_volume_ids = ["vol-aaa"]

        payload = serverless.model_dump(
            exclude=serverless._payload_exclude(), exclude_none=True, mode="json"
        )

        deployed_ids = serverless._deployed_volume_ids
        if len(deployed_ids) > 1:
            payload["networkVolumeIds"] = [
                {"networkVolumeId": vid} for vid in deployed_ids
            ]
            payload.pop("networkVolumeId", None)

        assert payload["networkVolumeId"] == "vol-aaa"
        assert "networkVolumeIds" not in payload

    def test_multi_volume_drift_detection(self):
        """Changing networkVolumes changes the config hash."""
        vol_a = NetworkVolume(name="vol-a", size=50, dataCenterId=DataCenter.EU_RO_1)
        vol_b = NetworkVolume(name="vol-b", size=50, dataCenterId=DataCenter.US_GA_2)

        s1 = ServerlessResource(
            name="test",
            networkVolumes=[vol_a],
            datacenter=[DataCenter.EU_RO_1],
        )
        s2 = ServerlessResource(
            name="test",
            networkVolumes=[vol_a, vol_b],
            datacenter=[DataCenter.EU_RO_1, DataCenter.US_GA_2],
        )

        assert s1.config_hash != s2.config_hash

    def test_volume_id_does_not_affect_config_hash(self):
        """Runtime-assigned volume id does not cause false drift."""
        vol_pre = NetworkVolume(name="vol-a", size=50, dataCenterId=DataCenter.EU_RO_1)
        vol_post = NetworkVolume(
            name="vol-a", size=50, dataCenterId=DataCenter.EU_RO_1, id="vol-aaa"
        )

        s1 = ServerlessResource(
            name="test",
            networkVolumes=[vol_pre],
            datacenter=[DataCenter.EU_RO_1],
        )
        s2 = ServerlessResource(
            name="test",
            networkVolumes=[vol_post],
            datacenter=[DataCenter.EU_RO_1],
        )

        assert s1.config_hash == s2.config_hash


class TestServerlessResourceValidation:
    """Test field validation and serialization."""

    def test_workers_min_cannot_exceed_workers_max(self):
        with pytest.raises(
            ValueError,
            match=r"workersMin \(5\) cannot be greater than workersMax \(1\)",
        ):
            ServerlessResource(name="test", workersMin=5, workersMax=1)

    @pytest.mark.parametrize("idle_timeout", [0, -1, 3601])
    def test_idle_timeout_must_be_between_1_and_3600(self, idle_timeout):
        with pytest.raises(
            ValueError,
            match="idleTimeout must be between 1 and 3600 seconds",
        ):
            ServerlessResource(name="test", idleTimeout=idle_timeout)

    @pytest.mark.parametrize("idle_timeout", [1, 3600])
    def test_idle_timeout_accepts_valid_boundaries(self, idle_timeout):
        serverless = ServerlessResource(name="test", idleTimeout=idle_timeout)

        assert serverless.idleTimeout == idle_timeout

    def test_scaler_type_serialization(self):
        """Test ServerlessScalerType enum serialization."""
        serverless = ServerlessResource(
            name="test",
            scalerType=ServerlessScalerType.REQUEST_COUNT,
        )

        # Test the field serializer
        serialized = serverless.model_dump()
        assert serialized["scalerType"] == "REQUEST_COUNT"

    def test_instance_ids_serialization(self):
        """Test CpuInstanceType serialization."""
        serverless = CpuServerlessEndpoint(
            name="test",
            imageName="test/image:v1",
            instanceIds=[CpuInstanceType.CPU3G_2_8, CpuInstanceType.CPU3G_4_16],
        )

        # Test the field serializer
        serialized = serverless.model_dump()
        assert "cpu3g-2-8" in serialized["instanceIds"]
        assert "cpu3g-4-16" in serialized["instanceIds"]

    def test_gpus_validation_with_any(self):
        """Test GPU validation expands ANY to all GPU groups."""
        serverless = ServerlessResource(
            name="test",
            gpus=[GpuGroup.ANY],
        )

        # The validator should expand ANY to all GPU groups
        assert serverless.gpus is not None
        assert len(serverless.gpus) > 1
        assert GpuGroup.ANY not in serverless.gpus

    def test_gpus_validation_with_specific_gpus(self):
        """Test GPU validation preserves specific GPU selections."""
        specific_gpus = [GpuGroup.AMPERE_48, GpuGroup.AMPERE_24]
        serverless = ServerlessResource(
            name="test",
            gpus=specific_gpus,
        )

        assert serverless.gpus == specific_gpus

    def test_flashboot_does_not_append_to_name(self):
        """Test flashboot=True does not append '-fb' to name."""
        serverless = ServerlessResource(
            name="test-serverless",
            flashboot=True,
        )

        assert serverless.name == "test-serverless"

    def test_flashboot_sets_flashBootType(self):
        """Test flashboot=True sets flashBootType="FLASHBOOT"."""
        serverless = ServerlessResource(
            name="test-serverless",
            flashboot=True,
        )

        assert serverless.flashBootType == "FLASHBOOT"

    def test_datacenter_defaults_to_none(self):
        """Test datacenter defaults to None (all datacenters)."""
        serverless = ServerlessResource(name="test")

        assert serverless.datacenter is None

    def test_datacenter_single_value(self):
        """Test datacenter accepts a single DataCenter and normalizes to list."""
        serverless = ServerlessResource(name="test", datacenter=DataCenter.EU_RO_1)

        assert serverless.datacenter == [DataCenter.EU_RO_1]

    def test_datacenter_multiple_values(self):
        """Test datacenter accepts a list of DataCenter values."""
        serverless = ServerlessResource(
            name="test",
            datacenter=[DataCenter.EU_RO_1, DataCenter.US_GA_2],
        )
        assert serverless.datacenter == [DataCenter.EU_RO_1, DataCenter.US_GA_2]

    def test_datacenter_string_value(self):
        """Test datacenter accepts string values."""
        serverless = ServerlessResource(name="test", datacenter="EU-RO-1")
        assert serverless.datacenter == [DataCenter.EU_RO_1]

    def test_datacenter_string_list(self):
        """Test datacenter accepts list of strings."""
        serverless = ServerlessResource(name="test", datacenter=["EU-RO-1", "US-GA-2"])
        assert serverless.datacenter == [DataCenter.EU_RO_1, DataCenter.US_GA_2]

    def test_datacenter_invalid_string_raises(self):
        """Test that an invalid datacenter string raises ValueError."""
        with pytest.raises(ValueError, match="Unknown datacenter"):
            ServerlessResource(name="test", datacenter="INVALID-DC")

    def test_locations_synced_from_datacenter(self):
        """Test locations field gets synced from datacenter."""
        serverless = ServerlessResource(name="test", datacenter=DataCenter.EU_RO_1)
        assert serverless.locations == "EU-RO-1"

    def test_locations_synced_from_multi_datacenter(self):
        """Test locations field gets synced from multiple datacenters."""
        serverless = ServerlessResource(
            name="test",
            datacenter=[DataCenter.EU_RO_1, DataCenter.US_GA_2],
        )
        assert serverless.locations == "EU-RO-1,US-GA-2"

    def test_no_datacenter_no_locations(self):
        """Test that no datacenter means no locations restriction."""
        serverless = ServerlessResource(name="test")
        assert serverless.locations is None

    def test_explicit_locations_not_overridden(self):
        """Test explicit locations field is not overridden."""
        serverless = ServerlessResource(name="test", locations="US-GA-2")

        assert serverless.locations == "US-GA-2"

    def test_datacenter_validation_matching_datacenters(self):
        """Test that matching datacenters between endpoint and volume work."""
        volume = NetworkVolume(name="test-volume", dataCenterId=DataCenter.EU_RO_1)
        serverless = ServerlessResource(
            name="test", datacenter=DataCenter.EU_RO_1, networkVolume=volume
        )

        assert serverless.datacenter == [DataCenter.EU_RO_1]
        assert serverless.networkVolume.dataCenterId == DataCenter.EU_RO_1

    def test_datacenter_validation_volume_not_in_dc_list(self):
        """Test that a volume DC not in endpoint's DC list raises an error."""
        volume = NetworkVolume(name="test-volume", dataCenterId=DataCenter.US_GA_2)
        with pytest.raises(
            ValueError,
            match="Network volume datacenter.*is not in the endpoint's datacenter list",
        ):
            ServerlessResource(
                name="test", datacenter=DataCenter.EU_RO_1, networkVolume=volume
            )

    def test_volume_dc_allowed_when_no_datacenter_set(self):
        """Test that any volume DC is allowed when no datacenter restriction is set."""
        volume = NetworkVolume(name="test-volume", dataCenterId=DataCenter.US_GA_2)
        serverless = ServerlessResource(name="test", networkVolume=volume)
        assert serverless.networkVolume.dataCenterId == DataCenter.US_GA_2

    def test_no_flashboot_keeps_name(self):
        """Test flashboot=False keeps original name."""
        serverless = ServerlessResource(
            name="test-serverless",
            flashboot=False,
        )

        assert serverless.name == "test-serverless"


class TestServerlessResourceSyncFields:
    """Test model validator sync_input_fields method."""

    def test_sync_input_fields_gpu_mode(self):
        """Test sync_input_fields in GPU mode."""
        serverless = ServerlessResource(
            name="test",
            gpus=[GpuGroup.AMPERE_48, GpuGroup.AMPERE_24],
            cudaVersions=[CudaVersion.V12_1, CudaVersion.V11_8],
        )

        # Check GPU fields are properly set
        assert serverless.gpuIds is not None
        assert "AMPERE_48" in serverless.gpuIds
        assert "AMPERE_24" in serverless.gpuIds
        assert serverless.allowedCudaVersions is not None
        assert "12.1" in serverless.allowedCudaVersions
        assert "11.8" in serverless.allowedCudaVersions

    def test_sync_input_fields_cpu_mode(self):
        """Test sync_input_fields in CPU mode."""
        serverless = CpuServerlessEndpoint(
            name="test",
            imageName="test/image:v1",
            instanceIds=[CpuInstanceType.CPU3G_2_8],
        )

        # Check CPU mode overrides GPU fields
        assert serverless.gpuCount == 0
        assert serverless.allowedCudaVersions == ""
        assert serverless.minCudaVersion is None
        assert serverless.gpuIds == ""

    def test_reverse_sync_gpuids_to_gpus(self):
        """Test reverse sync from gpuIds string to gpus list."""
        serverless = ServerlessResource(
            name="test",
            gpuIds="AMPERE_48,AMPERE_24",
        )

        # Should convert gpuIds string back to gpus list
        assert serverless.gpus is not None
        assert GpuGroup.AMPERE_48 in serverless.gpus
        assert GpuGroup.AMPERE_24 in serverless.gpus

    def test_sync_input_fields_normalizes_gpuids_order(self):
        serverless = ServerlessResource(
            name="test",
            gpuIds="-NVIDIA GeForce RTX 3090,AMPERE_24,NVIDIA L4",
        )

        assert serverless.gpuIds == "AMPERE_24,NVIDIA L4,-NVIDIA GeForce RTX 3090"

    def test_reverse_sync_cuda_versions(self):
        """Test reverse sync from allowedCudaVersions string to cudaVersions list."""
        serverless = ServerlessResource(
            name="test",
            allowedCudaVersions="12.1,11.8",
        )

        # Should convert allowedCudaVersions string back to cudaVersions list
        assert serverless.cudaVersions is not None
        assert CudaVersion.V12_1 in serverless.cudaVersions
        assert CudaVersion.V11_8 in serverless.cudaVersions


class TestMultiVolumeValidation:
    """Test multiple network volume support."""

    def test_single_volume_compat(self):
        """Test single networkVolume still works."""
        vol = NetworkVolume(name="v1", dataCenterId=DataCenter.EU_RO_1)
        s = ServerlessResource(name="test", networkVolume=vol)
        assert s.networkVolume is vol
        assert s.networkVolumes == [vol]

    def test_multiple_volumes_via_list(self):
        """Test networkVolumes accepts multiple volumes."""
        v1 = NetworkVolume(name="v1", dataCenterId=DataCenter.EU_RO_1)
        v2 = NetworkVolume(name="v2", dataCenterId=DataCenter.US_GA_2)
        s = ServerlessResource(name="test", networkVolumes=[v1, v2])
        assert len(s.networkVolumes) == 2
        assert s.networkVolume is v1

    def test_duplicate_dc_raises(self):
        """Test two volumes in the same DC raises."""
        v1 = NetworkVolume(name="v1", dataCenterId=DataCenter.EU_RO_1)
        v2 = NetworkVolume(name="v2", dataCenterId=DataCenter.EU_RO_1)
        with pytest.raises(ValueError, match="Multiple volumes in datacenter EU-RO-1"):
            ServerlessResource(name="test", networkVolumes=[v1, v2])

    def test_volumes_dc_outside_endpoint_dc_raises(self):
        """Test volume DC not in endpoint's DC list raises."""
        vol = NetworkVolume(name="v1", dataCenterId=DataCenter.US_GA_2)
        with pytest.raises(
            ValueError,
            match="is not in the endpoint's datacenter list",
        ):
            ServerlessResource(
                name="test",
                datacenter=DataCenter.EU_RO_1,
                networkVolumes=[vol],
            )

    def test_volumes_dc_within_endpoint_dc_list(self):
        """Test volume DCs all within endpoint DC list works."""
        v1 = NetworkVolume(name="v1", dataCenterId=DataCenter.EU_RO_1)
        v2 = NetworkVolume(name="v2", dataCenterId=DataCenter.US_GA_2)
        s = ServerlessResource(
            name="test",
            datacenter=[DataCenter.EU_RO_1, DataCenter.US_GA_2],
            networkVolumes=[v1, v2],
        )
        assert len(s.networkVolumes) == 2


class TestCpuDatacenterValidation:
    """Test CPU datacenter validation."""

    def test_cpu_endpoint_in_supported_dc(self):
        """Test CPU endpoint in supported datacenter works."""
        endpoint = CpuServerlessEndpoint(
            name="test-cpu",
            imageName="test/cpu:latest",
            datacenter=DataCenter.EU_RO_1,
        )
        assert endpoint.datacenter == [DataCenter.EU_RO_1]

    def test_cpu_endpoint_in_unsupported_dc_raises(self):
        """Test CPU endpoint in unsupported datacenter raises."""
        with pytest.raises(ValueError, match="CPU endpoints are not available in"):
            CpuServerlessEndpoint(
                name="test-cpu",
                imageName="test/cpu:latest",
                datacenter=DataCenter.US_GA_2,
            )

    def test_cpu_endpoint_mixed_dcs_raises(self):
        """Test CPU endpoint with mix of supported/unsupported DCs raises."""
        with pytest.raises(ValueError, match="CPU endpoints are not available in"):
            CpuServerlessEndpoint(
                name="test-cpu",
                imageName="test/cpu:latest",
                datacenter=[DataCenter.EU_RO_1, DataCenter.US_GA_2],
            )

    def test_cpu_endpoint_no_datacenter_ok(self):
        """Test CPU endpoint with no datacenter (all DCs) is allowed."""
        endpoint = CpuServerlessEndpoint(
            name="test-cpu",
            imageName="test/cpu:latest",
        )
        assert endpoint.datacenter is None

    def test_gpu_endpoint_any_dc_ok(self):
        """Test GPU endpoint in any datacenter is allowed."""
        serverless = ServerlessResource(
            name="test-gpu",
            datacenter=DataCenter.US_GA_2,
        )
        assert serverless.datacenter == [DataCenter.US_GA_2]


class TestMinCudaVersion:
    """Test minCudaVersion field defaults and behavior."""

    def test_gpu_endpoint_defaults_to_12_8(self):
        serverless = ServerlessResource(name="test")
        assert serverless.minCudaVersion == CudaVersion.V12_8

    def test_gpu_endpoint_custom_min_cuda(self):
        serverless = ServerlessResource(
            name="test",
            minCudaVersion=CudaVersion.V12_4.value,
        )
        assert serverless.minCudaVersion == CudaVersion.V12_4

    def test_min_cuda_version_in_hashed_fields(self):
        attr = getattr(ServerlessResource, "_hashed_fields")
        fields = attr.default if hasattr(attr, "default") else attr
        assert "minCudaVersion" in fields

    def test_min_cuda_version_included_in_payload(self):
        serverless = ServerlessResource(name="test")
        assert "minCudaVersion" not in serverless._input_only

    def test_cpu_endpoint_clears_min_cuda(self):
        cpu = CpuServerlessEndpoint(
            name="test",
            imageName="test/image:v1",
            instanceIds=[CpuInstanceType.CPU3G_2_8],
        )
        assert cpu.minCudaVersion is None

    def test_min_cuda_version_affects_config_hash(self):
        s1 = ServerlessResource(name="test", minCudaVersion="12.8")
        s2 = ServerlessResource(name="test", minCudaVersion="12.4")
        assert s1.config_hash != s2.config_hash

    def test_min_cuda_version_structural_change(self):
        s1 = ServerlessResource(name="test", minCudaVersion="12.8")
        s2 = ServerlessResource(name="test", minCudaVersion="12.4")
        assert s1._has_structural_changes(s2) is True

    def test_min_cuda_version_no_structural_change(self):
        s1 = ServerlessResource(name="test", minCudaVersion="12.8")
        s2 = ServerlessResource(name="test", minCudaVersion="12.8")
        assert s1._has_structural_changes(s2) is False

    def test_invalid_min_cuda_version_raises(self):
        with pytest.raises(ValueError, match="is not a valid CudaVersion"):
            ServerlessResource(name="test", minCudaVersion="99.9")

    def test_invalid_min_cuda_version_string_raises(self):
        with pytest.raises(ValueError, match="is not a valid CudaVersion"):
            ServerlessResource(name="test", minCudaVersion="not-a-version")


class TestJobOutput:
    """Test JobOutput model."""

    @pytest.fixture
    def job_output_data(self):
        """Sample job output data."""
        return {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1500,
            "executionTime": 3000,
            "output": {"result": "success"},
            "error": "",
        }

    def test_job_output_initialization(self, job_output_data):
        """Test JobOutput initialization."""
        job_output = JobOutput(**job_output_data)

        assert job_output.id == "job-123"
        assert job_output.workerId == "worker-456"
        assert job_output.status == "COMPLETED"
        assert job_output.delayTime == 1500
        assert job_output.executionTime == 3000
        assert job_output.output == {"result": "success"}
        assert job_output.error == ""

    def test_job_output_with_error(self):
        """Test JobOutput with error."""
        job_output = JobOutput(
            id="job-123",
            workerId="worker-456",
            status="FAILED",
            delayTime=1000,
            executionTime=500,
            error="Something went wrong",
        )

        assert job_output.status == "FAILED"
        assert job_output.error == "Something went wrong"
        assert job_output.output is None


class TestServerlessResourceDeployment:
    """Test deployment and execution workflows."""

    @pytest.fixture
    def mock_runpod_client(self):
        """Mock RunpodGraphQLClient."""
        client = AsyncMock()
        client.save_endpoint = AsyncMock()
        return client

    @pytest.fixture
    def deployment_response(self):
        """Mock deployment response from RunPod API."""
        return {
            "id": "endpoint-123",
            "name": "test-serverless",
            "gpuIds": "RTX4090",
            "allowedCudaVersions": "12.1",
            "networkVolumeId": "vol-456",
            "flashBootType": "FLASHBOOT",
        }

    @pytest.mark.asyncio
    async def test_is_deployed_false_when_no_id(self):
        """Test is_deployed returns False when no ID is set."""
        serverless = ServerlessResource(name="test")

        assert await serverless.is_deployed() is False

    @pytest.mark.asyncio
    async def test_is_deployed_skips_health_check_during_live_provisioning(
        self, monkeypatch
    ):
        """During flash run, is_deployed returns True based on ID alone."""
        monkeypatch.setenv("FLASH_IS_LIVE_PROVISIONING", "true")
        serverless = ServerlessResource(name="test")
        serverless.id = "ep-live-123"

        assert await serverless.is_deployed() is True

    @pytest.mark.asyncio
    async def test_is_deployed_uses_health_check_outside_live_provisioning(
        self, monkeypatch
    ):
        """Outside flash run, is_deployed falls back to health check."""
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)
        serverless = ServerlessResource(name="test")
        serverless.id = "ep-123"

        mock_endpoint = MagicMock()
        mock_endpoint.health.return_value = {"workers": {}}

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            assert await serverless.is_deployed() is True
            mock_endpoint.health.assert_called_once()

    @pytest.mark.asyncio
    async def test_deploy_already_deployed(self):
        """Test deploy returns early when already deployed."""
        serverless = ServerlessResource(name="test")
        serverless.id = "existing-123"

        with patch.object(
            ServerlessResource, "is_deployed", new_callable=AsyncMock, return_value=True
        ):
            result = await serverless.deploy()

            assert result == serverless

    @pytest.mark.asyncio
    async def test_deploy_success_with_network_volume(
        self, mock_runpod_client, deployment_response
    ):
        """Test successful deployment with network volume integration."""
        serverless = ServerlessResource(
            name="test-serverless",
            gpus=[GpuGroup.AMPERE_48],
            cudaVersions=[CudaVersion.V12_1],
            datacenter=DataCenter.EU_RO_1,
        )

        mock_runpod_client.save_endpoint.return_value = deployment_response

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_runpod_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource, "_ensure_network_volume_deployed"
            ) as mock_ensure_volume:
                with patch.object(
                    ServerlessResource,
                    "is_deployed",
                    new_callable=AsyncMock,
                    return_value=False,
                ):
                    result = await serverless.deploy()

        # Should call network volume deployment
        mock_ensure_volume.assert_called_once()

        # Should call save_endpoint
        mock_runpod_client.save_endpoint.assert_called_once()

        # Should return new instance with deployment data
        assert result.id == "endpoint-123"
        # Validator does not append "-fb"
        assert hasattr(result, "name") and result.name == "test-serverless"
        assert hasattr(result, "flashBootType") and result.flashBootType == "FLASHBOOT"
        # Verify locations was set from datacenter
        assert hasattr(result, "locations") and result.locations == "EU-RO-1"

    @pytest.mark.asyncio
    async def test_do_deploy_restores_input_only_fields(self, mock_runpod_client):
        """_do_deploy should merge input-only fields back into returned endpoint."""
        volume = NetworkVolume(name="persist-me", size=50)
        volume.id = "vol-input-only"

        serverless = ServerlessResource(
            name="input-sync",
            env={"FOO": "BAR"},
            networkVolume=volume,
        )

        deployment_response = {
            "id": "endpoint-sync",
            "name": "input-sync",
            "gpuIds": "AMPERE_48",
            "allowedCudaVersions": "",
            "flashBootType": "FLASHBOOT",
        }

        mock_runpod_client.save_endpoint = AsyncMock(return_value=deployment_response)

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_runpod_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                with patch.object(
                    ServerlessResource,
                    "is_deployed",
                    new_callable=AsyncMock,
                    return_value=False,
                ):
                    result = await serverless._do_deploy()

        assert result.env == serverless.env
        assert result.networkVolume == serverless.networkVolume
        assert serverless.id == "endpoint-sync"

    @pytest.mark.asyncio
    async def test_deploy_syncs_template_id_to_caller(self, mock_runpod_client):
        """deploy should hydrate templateId onto the caller object."""
        serverless = ServerlessResource(name="template-sync", flashboot=False)

        mock_runpod_client.save_endpoint = AsyncMock(
            return_value={
                "id": "endpoint-template-sync",
                "name": "template-sync",
                "templateId": "tpl-123",
                "gpuIds": "",
                "allowedCudaVersions": "",
            }
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_runpod_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "is_deployed",
                new_callable=AsyncMock,
                return_value=False,
            ):
                with patch.object(
                    ServerlessResource,
                    "_ensure_network_volume_deployed",
                    new=AsyncMock(),
                ):
                    result = await serverless.deploy()

        assert result.id == "endpoint-template-sync"
        assert serverless.templateId == "tpl-123"

    @pytest.mark.asyncio
    async def test_update_restores_input_only_fields(self, mock_runpod_client):
        """update should preserve input-only fields absent from GraphQL response."""
        existing = ServerlessResource(name="update-source", flashboot=False)
        existing.id = "endpoint-existing"

        volume = NetworkVolume(name="vol-update", size=50)
        volume.id = "vol-update-id"
        new_config = ServerlessResource(
            name="update-source",
            flashboot=False,
            env={"UPDATED": "true"},
            networkVolume=volume,
        )

        # API response does not include input-only fields like env/networkVolume
        mock_runpod_client.save_endpoint = AsyncMock(
            return_value={
                "id": "endpoint-existing",
                "name": "update-source",
                "gpuIds": "",
                "allowedCudaVersions": "",
            }
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_runpod_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                result = await existing.update(new_config)

        # id must be included to update in place rather than create
        payload = mock_runpod_client.save_endpoint.call_args.args[0]
        assert payload["id"] == "endpoint-existing"

        # Input-only state from new_config should be restored after update
        assert result.env == new_config.env
        assert result.networkVolume == new_config.networkVolume

    @pytest.mark.asyncio
    async def test_update_calls_save_template_with_resolved_template_id(
        self, mock_runpod_client
    ):
        """update should call saveTemplate separately when template is provided."""
        existing = ServerlessResource(name="update-template", flashboot=False)
        existing.id = "endpoint-existing"
        existing.templateId = "template-existing"

        new_config = ServerlessResource(
            name="update-template",
            flashboot=False,
            template=PodTemplate(name="tpl", imageName="image:v2", dockerArgs="--flag"),
        )

        mock_runpod_client.save_endpoint = AsyncMock(
            return_value={
                "id": "endpoint-existing",
                "name": "update-template",
                "templateId": "template-existing",
                "gpuIds": "",
                "allowedCudaVersions": "",
            }
        )
        mock_runpod_client.update_template = AsyncMock(
            return_value={
                "id": "template-existing",
                "name": "tpl",
                "imageName": "image:v2",
            }
        )
        mock_runpod_client.get_template = AsyncMock(return_value={"env": []})

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_runpod_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                updated = await existing.update(new_config)

        mock_runpod_client.save_endpoint.assert_called_once()
        mock_runpod_client.update_template.assert_called_once()
        template_payload = mock_runpod_client.update_template.call_args.args[0]
        assert template_payload["id"] == "template-existing"
        assert template_payload["imageName"] == "image:v2"
        assert template_payload["volumeInGb"] == 0
        assert updated.templateId == "template-existing"

    @pytest.mark.asyncio
    async def test_deploy_failure_raises_exception(self, mock_runpod_client):
        """Test deployment failure raises exception."""
        serverless = ServerlessResource(name="test")

        mock_runpod_client.save_endpoint.side_effect = Exception("API Error")

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_runpod_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "is_deployed",
                new_callable=AsyncMock,
                return_value=False,
            ):
                with patch.object(
                    ServerlessResource, "_ensure_network_volume_deployed"
                ):
                    with patch.dict("os.environ", {"RUNPOD_API_KEY": "test-api-key"}):
                        with pytest.raises(Exception, match="API Error"):
                            await serverless.deploy()

    @pytest.mark.asyncio
    async def test_run_sync_success(self):
        """Test run_sync successful execution."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"

        mock_endpoint = MagicMock()
        mock_endpoint.rp_client.post.return_value = {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": {"result": "success"},
        }

        payload = {"input": "test data"}

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            result = await serverless.runsync(payload)

        assert isinstance(result, JobOutput)
        assert result.id == "job-123"
        assert result.status == "COMPLETED"
        mock_endpoint.rp_client.post.assert_called_once_with(
            "endpoint-123/runsync", payload, timeout=60
        )

    @pytest.mark.asyncio
    async def test_run_sync_no_id_raises_error(self):
        """Test run_sync raises error when no ID is set."""
        serverless = ServerlessResource(name="test")

        with pytest.raises(ValueError, match="Serverless is not deployed"):
            await serverless.runsync({"input": "test"})

    @pytest.mark.asyncio
    async def test_run_async_success(self):
        """Test run async execution success."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.status.side_effect = ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"]
        mock_job._fetch_job.return_value = {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": {"result": "success"},
        }

        mock_endpoint = MagicMock()
        mock_endpoint.run.return_value = mock_job

        payload = {"input": "test data"}

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with patch("asyncio.sleep"):  # Mock sleep to speed up test
                result = await serverless.run(payload)

        assert isinstance(result, JobOutput)
        assert result.id == "job-123"
        assert result.status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_run_async_dedupes_stdout_against_streamed_pod_logs(self):
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"
        serverless.type = ServerlessType.QB
        serverless.aiKey = "endpoint-ai-key"

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.status.side_effect = ["IN_QUEUE", "COMPLETED"]
        mock_job._fetch_job.return_value = {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": {
                "stdout": "2026-04-02T18:18:10.165152015Z 2026-04-02 18:18:10,164 | DEBUG | aiohttp_retry | client.py:110 | Attempt 1 out of 3\n"
                "2026-04-02 18:18:10,164 | DEBUG | aiohttp_retry | client.py:110 | Attempt 1 out of 3\n"
                "unique stdout line"
            },
        }

        mock_endpoint = MagicMock()
        mock_endpoint.run.return_value = mock_job

        async def fake_emit(*, fetcher, request_id):
            fetcher.has_streamed_logs = True
            fetcher.seen.add(
                "2026-04-02T18:18:10.165152015Z 2026-04-02 18:18:10,164 | DEBUG | aiohttp_retry | client.py:110 | Attempt 1 out of 3"
            )
            return None

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with patch("asyncio.sleep"):
                with patch.object(
                    ServerlessResource,
                    "_emit_endpoint_logs",
                    new=AsyncMock(side_effect=fake_emit),
                ):
                    with patch(
                        "runpod_flash.core.resources.serverless.get_api_key",
                        return_value="runpod-key-123",
                    ):
                        result = await serverless.run({"input": "test"})

        assert isinstance(result, JobOutput)
        assert result.output["stdout"] == (
            "2026-04-02 18:18:10,164 | DEBUG | aiohttp_retry | client.py:110 | Attempt 1 out of 3\n"
            "unique stdout line"
        )

    @pytest.mark.asyncio
    async def test_run_async_keeps_stdout_unchanged_when_no_streamed_logs(self):
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"
        serverless.type = ServerlessType.QB
        serverless.aiKey = "endpoint-ai-key"

        original_stdout = "dup line\ndup line\n\n  spaced line"
        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.status.side_effect = ["IN_QUEUE", "COMPLETED"]
        mock_job._fetch_job.return_value = {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": {"stdout": original_stdout},
        }

        mock_endpoint = MagicMock()
        mock_endpoint.run.return_value = mock_job

        async def fake_emit(*, fetcher, request_id):
            fetcher.seen.add("dup line")
            return None

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with patch("asyncio.sleep"):
                with patch.object(
                    ServerlessResource,
                    "_emit_endpoint_logs",
                    new=AsyncMock(side_effect=fake_emit),
                ):
                    result = await serverless.run({"input": "test"})

        assert isinstance(result, JobOutput)
        assert result.output["stdout"] == original_stdout

    @pytest.mark.asyncio
    async def test_run_async_fetches_endpoint_logs_while_polling(self):
        """Test run async polls endpoint logs every cycle until completion."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"
        serverless.type = ServerlessType.QB
        serverless.aiKey = "ai-key-123"

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.status.side_effect = [
            "IN_QUEUE",
            "IN_PROGRESS",
            "IN_PROGRESS",
            "COMPLETED",
        ]
        mock_job._fetch_job.return_value = {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": {"result": "success"},
        }

        mock_endpoint = MagicMock()
        mock_endpoint.run.return_value = mock_job

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with patch("asyncio.sleep"):
                with patch.object(
                    ServerlessResource,
                    "_emit_endpoint_logs",
                    new=AsyncMock(),
                ) as mock_emit_logs:
                    await serverless.run({"input": "test"})

        assert mock_emit_logs.await_count == 6
        fetchers = [call.kwargs["fetcher"] for call in mock_emit_logs.await_args_list]
        assert len({id(fetcher) for fetcher in fetchers}) == 1
        request_ids = [
            call.kwargs["request_id"] for call in mock_emit_logs.await_args_list
        ]
        assert all(request_id == "job-123" for request_id in request_ids)

    @pytest.mark.asyncio
    async def test_run_async_announces_assigned_worker_streaming_once(self):
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"
        serverless.type = ServerlessType.QB
        serverless.aiKey = "ai-key-123"

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.status.side_effect = [
            "IN_PROGRESS",
            "IN_PROGRESS",
            "IN_PROGRESS",
            "COMPLETED",
        ]
        mock_job._fetch_job.return_value = {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": {"result": "success"},
        }

        mock_endpoint = MagicMock()
        mock_endpoint.run.return_value = mock_job

        assigned_batch = QBRequestLogBatch(
            worker_id="worker-456",
            lines=[],
            matched_by_request_id=True,
            phase=QBRequestLogPhase.STREAMING,
        )

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with patch("asyncio.sleep"):
                with patch.object(
                    ServerlessResource,
                    "_emit_endpoint_logs",
                    new=AsyncMock(
                        side_effect=[
                            assigned_batch,
                            assigned_batch,
                            assigned_batch,
                            assigned_batch,
                            assigned_batch,
                            assigned_batch,
                        ]
                    ),
                ):
                    with patch(
                        "runpod_flash.core.resources.serverless.log.info"
                    ) as mock_log_info:
                        await serverless.run({"input": "test"})

        assigned_messages = [
            str(call.args[0])
            for call in mock_log_info.call_args_list
            if call.args
            and "Request assigned to worker worker-456, streaming pod logs"
            in str(call.args[0])
        ]
        assert len(assigned_messages) == 1

    @pytest.mark.asyncio
    async def test_run_async_repeats_no_gpu_availability_message_every_five_updates(
        self,
    ):
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"
        serverless.type = ServerlessType.QB
        serverless.aiKey = "ai-key-123"

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.status.side_effect = [
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "COMPLETED",
        ]
        mock_job._fetch_job.return_value = {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": {"result": "success"},
        }

        waiting_batch = QBRequestLogBatch(
            worker_id=None,
            lines=[],
            matched_by_request_id=False,
            phase=QBRequestLogPhase.WAITING_FOR_WORKER,
        )

        async def emit_waiting_batch(*, fetcher, request_id):
            return waiting_batch

        mock_endpoint = MagicMock()
        mock_endpoint.run.return_value = mock_job

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with patch("asyncio.sleep"):
                with patch.object(
                    ServerlessResource,
                    "_emit_endpoint_logs",
                    new=AsyncMock(side_effect=emit_waiting_batch),
                ):
                    with patch(
                        "runpod_flash.core.resources.serverless.WorkerAvailabilityDiagnostic.diagnose",
                        new=AsyncMock(
                            return_value=WorkerAvailabilityResult(
                                message=(
                                    "No workers available on endpoint: no gpu availability for gpu type NVIDIA GeForce RTX 4090"
                                ),
                                has_availability=False,
                                reason="no_gpu_availability",
                            )
                        ),
                    ):
                        with patch(
                            "runpod_flash.core.resources.serverless.log.info"
                        ) as mock_log_info:
                            await serverless.run({"input": "test"})

        no_worker_messages = [
            str(call.args[0])
            for call in mock_log_info.call_args_list
            if call.args
            and "No workers available on endpoint: no gpu availability for gpu type"
            in str(call.args[0])
        ]
        assert len(no_worker_messages) == 2

    @pytest.mark.asyncio
    async def test_run_async_stops_waiting_metrics_logs_after_in_progress(self):
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"
        serverless.type = ServerlessType.QB
        serverless.aiKey = "ai-key-123"

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.status.side_effect = [
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_QUEUE",
            "IN_PROGRESS",
            "IN_PROGRESS",
            "IN_PROGRESS",
            "IN_PROGRESS",
            "COMPLETED",
        ]
        mock_job._fetch_job.return_value = {
            "id": "job-123",
            "workerId": "worker-456",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": {"result": "success"},
        }

        waiting_batch = QBRequestLogBatch(
            worker_id=None,
            lines=[],
            matched_by_request_id=False,
            phase=QBRequestLogPhase.WAITING_FOR_WORKER,
            worker_metrics={
                "ready": 0,
                "running": 0,
                "idle": 0,
                "initializing": 0,
                "throttled": 2,
                "unhealthy": 0,
            },
        )
        mock_endpoint = MagicMock()
        mock_endpoint.run.return_value = mock_job

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with patch("asyncio.sleep"):
                with patch.object(
                    ServerlessResource,
                    "_emit_endpoint_logs",
                    new=AsyncMock(return_value=waiting_batch),
                ):
                    with patch(
                        "runpod_flash.core.resources.serverless.WorkerAvailabilityDiagnostic.diagnose",
                        new=AsyncMock(
                            return_value=WorkerAvailabilityResult(
                                message="Workers are currently throttled on endpoint for selected gpu NVIDIA GeForce RTX 4090. Consider raising max workers or changing gpu type.",
                                has_availability=True,
                                reason="workers_throttled",
                            )
                        ),
                    ):
                        with patch(
                            "runpod_flash.core.resources.serverless.log.info"
                        ) as mock_log_info:
                            await serverless.run({"input": "test"})

        metrics_logs = [
            str(call.args[0])
            for call in mock_log_info.call_args_list
            if call.args
            and "Waiting for request: endpoint metrics:" in str(call.args[0])
        ]
        assert metrics_logs
        assert not any("status=IN_PROGRESS" in line for line in metrics_logs)

    @pytest.mark.asyncio
    async def test_emit_endpoint_logs_uses_logger_for_worker_lines(self):
        """Endpoint log emission logs each worker line through logger."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"
        serverless.type = ServerlessType.QB
        serverless.aiKey = "endpoint-ai-key"

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_logs = AsyncMock(
            return_value=QBRequestLogBatch(
                worker_id=None,
                lines=["line-a", "line-b"],
                matched_by_request_id=False,
                phase=QBRequestLogPhase.STREAMING,
            )
        )

        with patch(
            "runpod_flash.core.resources.serverless.get_api_key",
            return_value="runpod-key-123",
        ):
            with patch("runpod_flash.core.resources.serverless.log.info") as mock_info:
                batch = await serverless._emit_endpoint_logs(
                    fetcher=mock_fetcher,
                    request_id="job-123",
                )

        mock_fetcher.fetch_logs.assert_awaited_once_with(
            endpoint_id="endpoint-123",
            request_id="job-123",
            status_api_key="endpoint-ai-key",
            pod_logs_api_key="runpod-key-123",
            status_api_key_fallback="runpod-key-123",
        )
        assert batch is not None
        assert batch.phase == QBRequestLogPhase.STREAMING
        mock_info.assert_any_call("worker log: %s", "line-a")
        mock_info.assert_any_call("worker log: %s", "line-b")

    @pytest.mark.asyncio
    async def test_emit_endpoint_logs_skips_when_missing_required_fields(self):
        """Endpoint log fetch is skipped unless QB endpoint has id and API key."""
        serverless = ServerlessResource(name="test")
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_logs = AsyncMock(return_value=None)

        serverless.type = ServerlessType.QB
        serverless.id = None
        serverless.aiKey = "endpoint-ai-key"
        with patch(
            "runpod_flash.core.resources.serverless.get_api_key",
            return_value="runpod-key-123",
        ):
            await serverless._emit_endpoint_logs(
                fetcher=mock_fetcher,
                request_id="job-123",
            )

        serverless.id = "endpoint-123"
        serverless.aiKey = None
        with patch(
            "runpod_flash.core.resources.serverless.get_api_key",
            return_value=None,
        ):
            await serverless._emit_endpoint_logs(
                fetcher=mock_fetcher,
                request_id="job-123",
            )

        serverless.type = ServerlessType.LB
        serverless.aiKey = "endpoint-ai-key"
        with patch(
            "runpod_flash.core.resources.serverless.get_api_key",
            return_value="runpod-key-123",
        ):
            await serverless._emit_endpoint_logs(
                fetcher=mock_fetcher,
                request_id="job-123",
            )

        mock_fetcher.fetch_logs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_async_failure_cancels_job(self):
        """Test run async cancels job on exception."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.status.side_effect = Exception("Job failed")
        mock_job.cancel.return_value = None

        mock_endpoint = MagicMock()
        mock_endpoint.run.return_value = mock_job

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with pytest.raises(Exception, match="Job failed"):
                await serverless.run({"input": "test"})

        mock_job.cancel.assert_called_once()


class TestServerlessEndpoint:
    """Test ServerlessEndpoint class."""

    def test_serverless_endpoint_requires_image_template_or_id(self):
        """Test ServerlessEndpoint validation requires image, template, or templateId."""
        with pytest.raises(
            ValueError,
            match="Either imageName, template, or templateId must be provided",
        ):
            ServerlessEndpoint(name="test")

    def test_serverless_endpoint_with_image_name(self):
        """Test ServerlessEndpoint creates template from imageName."""
        endpoint = ServerlessEndpoint(
            name="test-endpoint",
            imageName="test/image:latest",
        )

        assert endpoint.template is not None
        assert endpoint.template.imageName == "test/image:latest"
        # Template name will be generated based on resource IDs
        assert endpoint.template.name is not None
        assert "ServerlessEndpoint" in endpoint.template.name
        assert "PodTemplate" in endpoint.template.name

    def test_serverless_endpoint_with_template_id(self):
        """Test ServerlessEndpoint works with templateId."""
        endpoint = ServerlessEndpoint(
            name="test-endpoint",
            templateId="template-123",
        )

        assert endpoint.templateId == "template-123"
        assert endpoint.template is None

    def test_serverless_endpoint_with_existing_template(self):
        """Test ServerlessEndpoint with existing template."""
        from runpod_flash.core.resources.template import PodTemplate

        template = PodTemplate(name="existing-template", imageName="test/image:v1")
        endpoint = ServerlessEndpoint(
            name="test-endpoint",
            template=template,
        )

        assert endpoint.template is not None
        # Template name will be generated with resource IDs
        assert endpoint.template.name is not None
        assert "ServerlessEndpoint" in endpoint.template.name
        assert "PodTemplate" in endpoint.template.name
        assert endpoint.template.imageName == "test/image:v1"

    def test_serverless_endpoint_template_env_override(self):
        """Test ServerlessEndpoint overrides template env vars."""
        from runpod_flash.core.resources.template import PodTemplate, KeyValuePair

        template = PodTemplate(
            name="existing-template",
            imageName="test/image:v1",
            env=[KeyValuePair(key="OLD_VAR", value="old_value")],
        )
        endpoint = ServerlessEndpoint(
            name="test-endpoint",
            template=template,
            env={"NEW_VAR": "new_value"},
        )

        # Check that template and env are properly set
        assert endpoint.template is not None
        assert endpoint.template.env is not None
        assert len(endpoint.template.env) == 1
        assert endpoint.template.env[0].key == "NEW_VAR"
        assert endpoint.template.env[0].value == "new_value"


class TestCpuServerlessEndpoint:
    """Test CpuServerlessEndpoint class."""

    def test_cpu_serverless_endpoint_defaults(self):
        """Test CpuServerlessEndpoint has CPU instance defaults."""
        endpoint = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
        )

        # Should default to CPU3G_2_8
        assert endpoint.instanceIds == [CpuInstanceType.CPU3G_2_8]
        # Should trigger CPU mode in sync_input_fields
        assert endpoint.gpuCount == 0
        assert endpoint.allowedCudaVersions == ""
        assert endpoint.gpuIds == ""

    def test_cpu_serverless_endpoint_custom_instance_types(self):
        """Test CpuServerlessEndpoint with custom instance types."""
        # Use valid CPU instance types from the enum
        endpoint = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_4_16, CpuInstanceType.CPU3C_8_16],
        )

        assert endpoint.instanceIds is not None
        assert len(endpoint.instanceIds) == 2
        assert CpuInstanceType.CPU3G_4_16 in endpoint.instanceIds
        assert CpuInstanceType.CPU3C_8_16 in endpoint.instanceIds


class TestServerlessResourceEdgeCases:
    """Test edge cases and error scenarios."""

    @pytest.mark.asyncio
    async def test_is_deployed_with_exception(self):
        """Test is_deployed handles endpoint exceptions."""
        serverless = ServerlessResource(name="test")
        serverless.id = "test-id-123"

        mock_endpoint = MagicMock()
        mock_endpoint.health.side_effect = Exception("Connection error")

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            result = await serverless.is_deployed()

            assert result is False

    def test_payload_exclude_adds_template_when_template_id_set(self):
        """_payload_exclude excludes template field when templateId is already set."""
        serverless = ServerlessResource(name="test")
        serverless.templateId = "tmpl-123"

        excluded = serverless._payload_exclude()

        assert "template" in excluded

    def test_payload_exclude_tolerates_both_template_id_and_template(self):
        """_payload_exclude does not raise when both templateId and template are set.

        After deploy mutates the config object, both fields can coexist.
        templateId takes precedence and template should be excluded.
        """
        serverless = ServerlessResource(name="test")
        serverless.templateId = "tmpl-123"
        serverless.template = PodTemplate(
            name="test-template",
            imageName="runpod/test:latest",
            containerDiskInGb=20,
        )

        excluded = serverless._payload_exclude()

        assert "template" in excluded

    def test_payload_exclude_does_not_exclude_template_without_template_id(self):
        """_payload_exclude does not exclude template when templateId is absent."""
        serverless = ServerlessResource(name="test")
        serverless.templateId = None

        excluded = serverless._payload_exclude()

        assert "template" not in excluded

    def test_reverse_sync_from_backend_response(self):
        """Test reverse sync when receiving backend response with gpuIds."""
        # This tests the lines 173-176 which convert gpuIds back to gpus list
        serverless = ServerlessResource(
            name="test",
            gpuIds="AMPERE_48,AMPERE_24,INVALID_GPU",  # Include invalid GPU to test error handling
        )

        # Should have parsed valid GPUs and skipped invalid ones
        assert serverless.gpus is not None
        valid_gpus = [
            gpu
            for gpu in serverless.gpus
            if gpu in [GpuGroup.AMPERE_48, GpuGroup.AMPERE_24]
        ]
        assert len(valid_gpus) >= 2

    @pytest.mark.asyncio
    async def test_run_sync_with_exception_logs_health(self):
        """Test run_sync exception handling logs health status."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"

        mock_endpoint = MagicMock()
        mock_endpoint.rp_client.post.side_effect = Exception("Request failed")
        mock_endpoint.health.return_value = {
            "workers": {
                "idle": 0,
                "initializing": 0,
                "ready": 0,
                "running": 0,
                "throttled": 1,
                "unhealthy": 0,
            },
            "jobs": {
                "completed": 0,
                "failed": 0,
                "inProgress": 0,
                "inQueue": 0,
                "retried": 0,
            },
        }

        with patch.object(
            type(serverless),
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            with pytest.raises(Exception, match="Request failed"):
                await serverless.runsync({"input": "test"})


class TestLivePrefixNaming:
    """Test live- prefix naming for auto-provisioned resources."""

    def test_live_prefix_applied_when_flag_set(self):
        """Test live- prefix applied when FLASH_IS_LIVE_PROVISIONING=true."""
        with patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"}):
            endpoint = ServerlessEndpoint(
                name="test-endpoint",
                imageName="test:latest",
                flashboot=False,
            )
            assert endpoint.name == "live-test-endpoint"

    def test_live_prefix_with_flashboot(self):
        """Test live- prefix with flashboot suffix."""
        with patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"}):
            endpoint = ServerlessEndpoint(
                name="test-endpoint",
                imageName="test:latest",
                flashboot=True,
            )
            assert endpoint.name == "live-test-endpoint"
            assert endpoint.flashBootType == "FLASHBOOT"

    def test_no_live_prefix_when_flag_not_set(self):
        """Test no live- prefix without flag."""
        with patch.dict(os.environ, {}, clear=True):
            endpoint = ServerlessEndpoint(
                name="test-endpoint",
                imageName="test:latest",
                flashboot=False,
            )
            assert endpoint.name == "test-endpoint"

    def test_live_prefix_idempotent(self):
        """Test live- prefix not duplicated on multiple calls."""
        with patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"}):
            endpoint = ServerlessEndpoint(
                name="test-endpoint",
                imageName="test:latest",
                flashboot=False,
            )
            first_name = endpoint.name
            endpoint.sync_input_fields()  # Call again
            assert endpoint.name == first_name

    def test_live_prefix_strips_existing(self):
        """Test existing live- prefix stripped first."""
        with patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"}):
            endpoint = ServerlessEndpoint(
                name="live-test-endpoint",
                imageName="test:latest",
                flashboot=False,
            )
            assert endpoint.name == "live-test-endpoint"
            assert endpoint.name.count("live-") == 1


class TestServerlessResourceUndeploy:
    """Test undeploy behavior for orphaned endpoints."""

    @pytest.mark.asyncio
    async def test_undeploy_success(self):
        """Test successful undeploy through resource manager."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"

        mock_client = AsyncMock()
        mock_client.delete_endpoint = AsyncMock(return_value={"success": True})
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as MockClient:
            MockClient.return_value = mock_client
            # undeploy() now goes through resource_manager and returns a dict
            with patch(
                "runpod_flash.core.resources.serverless.ResourceManager"
            ) as MockManager:
                manager_instance = AsyncMock()
                manager_instance.undeploy_resource = AsyncMock(
                    return_value={
                        "success": True,
                        "name": "test",
                        "endpoint_id": "endpoint-123",
                        "message": "Successfully undeployed 'test' (endpoint-123)",
                    }
                )
                MockManager.return_value = manager_instance
                result = await serverless.undeploy()

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_undeploy_api_failure_when_endpoint_exists(self):
        """Test undeploy returns dict with success=False when API fails and endpoint still exists."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"

        mock_client = AsyncMock()
        mock_client.delete_endpoint = AsyncMock(
            side_effect=Exception("Something went wrong. Please try again later")
        )
        mock_client.endpoint_exists = AsyncMock(
            return_value=True
        )  # Endpoint still exists
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as MockClient:
            MockClient.return_value = mock_client
            # undeploy() now goes through resource_manager and returns a dict
            with patch(
                "runpod_flash.core.resources.serverless.ResourceManager"
            ) as MockManager:
                manager_instance = AsyncMock()
                manager_instance.undeploy_resource = AsyncMock(
                    return_value={
                        "success": False,
                        "name": "test",
                        "endpoint_id": "endpoint-123",
                        "message": "Failed to undeploy 'test' (endpoint-123)",
                    }
                )
                MockManager.return_value = manager_instance
                result = await serverless.undeploy()

        # API failed and endpoint still exists, so undeploy fails
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_undeploy_auto_cleanup_when_endpoint_not_found(self):
        """Test undeploy auto-cleans cache when endpoint was deleted externally."""
        serverless = ServerlessResource(name="test")
        serverless.id = "endpoint-123"

        mock_client = AsyncMock()
        mock_client.delete_endpoint = AsyncMock(
            side_effect=Exception("Something went wrong. Please try again later")
        )
        mock_client.endpoint_exists = AsyncMock(
            return_value=False
        )  # Endpoint not found
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as MockClient:
            MockClient.return_value = mock_client
            # undeploy() now goes through resource_manager and returns a dict
            with patch(
                "runpod_flash.core.resources.serverless.ResourceManager"
            ) as MockManager:
                manager_instance = AsyncMock()
                manager_instance.undeploy_resource = AsyncMock(
                    return_value={
                        "success": True,
                        "name": "test",
                        "endpoint_id": "endpoint-123",
                        "message": "Successfully undeployed 'test' (endpoint-123)",
                    }
                )
                MockManager.return_value = manager_instance
                result = await serverless.undeploy()

        # API failed but endpoint doesn't exist, so treat as successful cleanup
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_undeploy_no_id(self):
        """Test undeploy returns dict with success=False when endpoint has no ID."""
        serverless = ServerlessResource(name="test")
        # No ID set

        # undeploy() now goes through resource_manager and returns a dict
        with patch(
            "runpod_flash.core.resources.serverless.ResourceManager"
        ) as MockManager:
            manager_instance = AsyncMock()
            manager_instance.undeploy_resource = AsyncMock(
                return_value={
                    "success": False,
                    "name": "test",
                    "endpoint_id": "N/A",
                    "message": "Resource not found in tracking",
                }
            )
            MockManager.return_value = manager_instance
            result = await serverless.undeploy()

        assert result["success"] is False


class TestHealthModels:
    """Test health-related models."""

    def test_workers_health_status_ready(self):
        """Test WorkersHealth status when workers are ready."""
        health = WorkersHealth(
            idle=2,
            initializing=0,
            ready=1,
            running=1,
            throttled=0,
            unhealthy=0,
        )

        assert health.status == Status.READY

    def test_workers_health_status_initializing(self):
        """Test WorkersHealth status when workers are initializing."""
        health = WorkersHealth(
            idle=0,
            initializing=2,
            ready=0,
            running=0,
            throttled=0,
            unhealthy=0,
        )

        assert health.status == Status.INITIALIZING

    def test_workers_health_status_throttled(self):
        """Test WorkersHealth status when workers are throttled."""
        health = WorkersHealth(
            idle=0,
            initializing=0,
            ready=0,
            running=0,
            throttled=2,
            unhealthy=0,
        )

        assert health.status == Status.THROTTLED

    def test_workers_health_status_unhealthy(self):
        """Test WorkersHealth status when workers are unhealthy."""
        health = WorkersHealth(
            idle=0,
            initializing=0,
            ready=0,
            running=0,
            throttled=0,
            unhealthy=2,
        )

        assert health.status == Status.UNHEALTHY

    def test_workers_health_status_unknown(self):
        """Test WorkersHealth status when all workers are zero."""
        health = WorkersHealth(
            idle=0,
            initializing=0,
            ready=0,
            running=0,
            throttled=0,
            unhealthy=0,
        )

        assert health.status == Status.UNKNOWN

    def test_serverless_health_is_ready_true(self):
        """Test ServerlessHealth is_ready property when ready."""
        workers_health = WorkersHealth(
            idle=1, initializing=0, ready=1, running=0, throttled=0, unhealthy=0
        )
        jobs_health = JobsHealth(
            completed=5, failed=0, inProgress=1, inQueue=2, retried=0
        )

        health = ServerlessHealth(workers=workers_health, jobs=jobs_health)

        assert health.is_ready is True

    def test_serverless_health_is_ready_false(self):
        """Test ServerlessHealth is_ready property when not ready."""
        workers_health = WorkersHealth(
            idle=0, initializing=2, ready=0, running=0, throttled=0, unhealthy=0
        )
        jobs_health = JobsHealth(
            completed=5, failed=0, inProgress=1, inQueue=2, retried=0
        )

        health = ServerlessHealth(workers=workers_health, jobs=jobs_health)

        assert health.is_ready is False


class TestServerlessResourcePythonVersion:
    """Tests for python_version field on ServerlessResource."""

    def _get_class_set(self, attr_name: str) -> set:
        """Extract set from class attribute, handling ModelPrivateAttr wrapping."""
        attr = getattr(ServerlessEndpoint, attr_name, None)
        if isinstance(attr, (set, frozenset)):
            return attr
        if hasattr(attr, "default") and isinstance(attr.default, (set, frozenset)):
            return attr.default
        raise TypeError(f"Cannot extract set from {attr_name}: {type(attr)}")

    def test_python_version_defaults_to_none(self):
        endpoint = ServerlessEndpoint(name="test", imageName="test:latest")
        assert endpoint.python_version is None

    def test_python_version_accepts_valid_values(self):
        from runpod_flash.core.resources.constants import SUPPORTED_PYTHON_VERSIONS

        for version in SUPPORTED_PYTHON_VERSIONS:
            endpoint = ServerlessEndpoint(
                name="test", imageName="test:latest", python_version=version
            )
            assert endpoint.python_version == version

    def test_python_version_rejects_invalid(self):
        with pytest.raises(ValueError, match="not supported"):
            ServerlessEndpoint(
                name="test", imageName="test:latest", python_version="3.13"
            )

    def test_python_version_rejects_3_9(self):
        with pytest.raises(ValueError, match="not supported"):
            ServerlessEndpoint(
                name="test", imageName="test:latest", python_version="3.9"
            )

    def test_python_version_in_hashed_fields(self):
        hashed = self._get_class_set("_hashed_fields")
        assert "python_version" in hashed

    def test_python_version_in_input_only(self):
        input_only = self._get_class_set("_input_only")
        assert "python_version" in input_only


class TestInjectTemplateEnv:
    """Test _inject_template_env helper and _do_deploy env non-mutation."""

    def _make_resource_with_template(self, **overrides):
        """Create a ServerlessEndpoint with a template for injection tests."""
        defaults = {
            "name": "inject-test",
            "imageName": "test:latest",
            "env": {"USER_VAR": "user_value"},
            "flashboot": False,
        }
        defaults.update(overrides)
        return ServerlessEndpoint(**defaults)

    def test_inject_template_env_adds_key_value_pair(self):
        """_inject_template_env adds a KeyValuePair to template.env."""
        resource = self._make_resource_with_template()
        assert resource.template is not None

        original_len = len(resource.template.env)
        resource._inject_template_env("NEW_KEY", "new_value")

        assert len(resource.template.env) == original_len + 1
        added = resource.template.env[-1]
        assert added.key == "NEW_KEY"
        assert added.value == "new_value"

    def test_inject_template_env_is_idempotent(self):
        """_inject_template_env does not add duplicate keys."""
        resource = self._make_resource_with_template()
        assert resource.template is not None

        resource._inject_template_env("DEDUP_KEY", "first")
        resource._inject_template_env("DEDUP_KEY", "second")

        matching = [kv for kv in resource.template.env if kv.key == "DEDUP_KEY"]
        assert len(matching) == 1
        assert matching[0].value == "first"

    def test_inject_template_env_skips_when_no_template(self):
        """_inject_template_env is a no-op when template is None."""
        resource = ServerlessResource(name="no-template")
        resource.template = None

        # Should not raise
        resource._inject_template_env("KEY", "value")

    def test_inject_template_env_initializes_empty_env_list(self):
        """_inject_template_env handles template with None env list."""
        resource = self._make_resource_with_template()
        resource.template.env = None

        resource._inject_template_env("INIT_KEY", "init_value")

        assert len(resource.template.env) == 1
        assert resource.template.env[0].key == "INIT_KEY"

    @pytest.mark.asyncio
    async def test_do_deploy_does_not_mutate_self_env(self):
        """_do_deploy should not modify self.env (prevents false config drift)."""
        resource = self._make_resource_with_template(
            env={"LOG_LEVEL": "INFO"},
        )
        env_before = dict(resource.env)

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "endpoint-env-test",
                "name": "inject-test",
                "templateId": "tpl-env-test",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                with patch.object(
                    ServerlessResource, "is_deployed", return_value=False
                ):
                    with patch.object(
                        ServerlessResource,
                        "_check_makes_remote_calls",
                        return_value=True,
                    ):
                        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key-123"}):
                            await resource._do_deploy()

        assert resource.env == env_before

    @pytest.mark.asyncio
    async def test_do_deploy_injects_api_key_into_template_env(self):
        """_do_deploy should inject RUNPOD_API_KEY into template.env for QB endpoints."""
        resource = self._make_resource_with_template(
            env={"LOG_LEVEL": "INFO"},
        )

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "endpoint-inject-test",
                "name": "inject-test",
                "templateId": "tpl-inject-test",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                with patch.object(
                    ServerlessResource, "is_deployed", return_value=False
                ):
                    with patch.object(
                        ServerlessResource,
                        "_check_makes_remote_calls",
                        return_value=True,
                    ):
                        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key-456"}):
                            await resource._do_deploy()

        # The API key should have been in the payload sent to save_endpoint
        # via the template env, not via self.env
        payload = mock_client.save_endpoint.call_args.args[0]
        template_env = payload.get("template", {}).get("env", [])
        api_key_entries = [e for e in template_env if e["key"] == "RUNPOD_API_KEY"]
        assert len(api_key_entries) == 1
        assert api_key_entries[0]["value"] == "test-key-456"

    @pytest.mark.asyncio
    async def test_do_deploy_lb_injects_module_path_into_template_env(self):
        """_do_deploy should inject FLASH_MODULE_PATH into template.env for LB endpoints."""
        from runpod_flash.core.resources.load_balancer_sls_resource import (
            LoadBalancerSlsResource,
        )

        resource = LoadBalancerSlsResource(
            name="lb-inject-test",
            imageName="test:latest",
            env={"LOG_LEVEL": "INFO"},
            flashboot=False,
        )
        env_before = dict(resource.env)

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "endpoint-lb-test",
                "name": "lb-inject-test",
                "templateId": "tpl-lb-test",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                with patch.object(
                    LoadBalancerSlsResource, "is_deployed", return_value=False
                ):
                    with patch.object(
                        ServerlessResource,
                        "_get_module_path",
                        return_value="myapp.handler",
                    ):
                        await resource._do_deploy()

        # self.env should not be mutated
        assert resource.env == env_before

        # FLASH_MODULE_PATH should be in template env
        payload = mock_client.save_endpoint.call_args.args[0]
        template_env = payload.get("template", {}).get("env", [])
        module_entries = [e for e in template_env if e["key"] == "FLASH_MODULE_PATH"]
        assert len(module_entries) == 1
        assert module_entries[0]["value"] == "myapp.handler"

        # FLASH_ENDPOINT_TYPE should NOT be injected here — it's set by the
        # runtime resource_provisioner for flash deploy, not by _do_deploy
        type_entries = [e for e in template_env if e["key"] == "FLASH_ENDPOINT_TYPE"]
        assert len(type_entries) == 0


class TestBuildTemplateUpdatePayload:
    """Test _build_template_update_payload always includes env."""

    def test_payload_includes_env(self):
        """Template update payload always includes env (non-nullable in saveTemplate)."""
        template = PodTemplate(
            name="test-template",
            imageName="test:latest",
            env=[KeyValuePair(key="MY_VAR", value="my_val")],
        )
        payload = ServerlessResource._build_template_update_payload(template, "tpl-123")
        assert "env" in payload
        assert payload["env"] == [{"key": "MY_VAR", "value": "my_val"}]

    def test_payload_defaults_env_to_empty_list(self):
        """Template update payload defaults env to [] when template has no env."""
        template = PodTemplate(
            name="test-template",
            imageName="test:latest",
        )
        # env defaults to [] on PodTemplate, but exclude_none=True in model_dump
        # might drop it — payload.setdefault ensures it's always present.
        payload = ServerlessResource._build_template_update_payload(template, "tpl-123")
        assert "env" in payload
        assert payload["imageName"] == "test:latest"
        assert payload["id"] == "tpl-123"

    @pytest.mark.asyncio
    async def test_update_echoes_live_env_when_unchanged(self):
        """update() fetches live template env when user env hasn't changed.

        saveTemplate requires env (non-nullable), so even when the user's env
        is unchanged we must send the field.  The live env is echoed back to
        preserve platform-injected vars (PORT, PORT_HEALTH).
        """
        env = {"LOG_LEVEL": "INFO"}
        old_resource = ServerlessEndpoint(
            name="update-test",
            imageName="test:latest",
            env=env,
            flashboot=False,
        )
        old_resource.id = "ep-123"
        old_resource.templateId = "tpl-123"

        new_resource = ServerlessEndpoint(
            name="update-test",
            imageName="test:latest",
            env=env,
            flashboot=False,
            workersMax=5,
        )

        live_env = [
            {"key": "LOG_LEVEL", "value": "INFO"},
            {"key": "PORT", "value": "8080"},
        ]
        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-123",
                "name": "update-test",
                "templateId": "tpl-123",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(return_value={"env": live_env})

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                await old_resource.update(new_resource)

        # env IS in the payload — echoed from the live template
        assert mock_client.update_template.called
        template_payload = mock_client.update_template.call_args.args[0]
        assert "env" in template_payload
        env_keys = {e["key"] for e in template_payload["env"]}
        assert "LOG_LEVEL" in env_keys
        assert "PORT" in env_keys

    @pytest.mark.asyncio
    async def test_update_raises_when_get_template_fails_env_unchanged(self):
        """update() raises when get_template fails and env is unchanged.

        If we cannot fetch the live template env, proceeding would risk
        wiping platform-injected vars (PORT, PORT_HEALTH).  The deploy
        must fail loudly rather than send a destructive payload.
        """
        env = {"LOG_LEVEL": "INFO"}
        old_resource = ServerlessEndpoint(
            name="update-test",
            imageName="test:latest",
            env=env,
            flashboot=False,
        )
        old_resource.id = "ep-123"
        old_resource.templateId = "tpl-123"

        new_resource = ServerlessEndpoint(
            name="update-test",
            imageName="test:latest",
            env=env,
            flashboot=False,
            workersMax=5,
        )

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-123",
                "name": "update-test",
                "templateId": "tpl-123",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(
            side_effect=RuntimeError("API unavailable")
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                with pytest.raises(RuntimeError, match="API unavailable"):
                    await old_resource.update(new_resource)

        # update_template should NOT have been called since we raised
        mock_client.update_template.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_includes_env_when_changed(self):
        """update() includes env in template payload when env changed."""
        old_resource = ServerlessEndpoint(
            name="update-test",
            imageName="test:latest",
            env={"LOG_LEVEL": "INFO"},
            flashboot=False,
        )
        old_resource.id = "ep-123"
        old_resource.templateId = "tpl-123"

        new_resource = ServerlessEndpoint(
            name="update-test",
            imageName="test:latest",
            env={"LOG_LEVEL": "DEBUG", "NEW_VAR": "new_val"},
            flashboot=False,
        )

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-123",
                "name": "update-test",
                "templateId": "tpl-123",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(return_value={"env": []})

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                await old_resource.update(new_resource)

        # update_template was called WITH env since it changed
        assert mock_client.update_template.called
        template_payload = mock_client.update_template.call_args.args[0]
        assert "env" in template_payload

    @pytest.mark.asyncio
    async def test_update_injects_runtime_vars_when_env_changed(self):
        """update() injects RUNPOD_API_KEY into template.env when env changed.

        Without this, runtime-injected vars (set during _do_deploy) would be
        lost when update() overwrites the template env.
        """
        old_resource = ServerlessEndpoint(
            name="update-inject-test",
            imageName="test:latest",
            env={"LOG_LEVEL": "INFO"},
            flashboot=False,
        )
        old_resource.id = "ep-inject"
        old_resource.templateId = "tpl-inject"

        new_resource = ServerlessEndpoint(
            name="update-inject-test",
            imageName="test:latest",
            env={"LOG_LEVEL": "DEBUG"},
            flashboot=False,
        )

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-inject",
                "name": "update-inject-test",
                "templateId": "tpl-inject",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(return_value={"env": []})

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                with patch.object(
                    ServerlessResource,
                    "_check_makes_remote_calls",
                    return_value=True,
                ):
                    with patch.dict(os.environ, {"RUNPOD_API_KEY": "inject-key"}):
                        await old_resource.update(new_resource)

        template_payload = mock_client.update_template.call_args.args[0]
        env_entries = template_payload.get("env", [])
        api_key_entries = [e for e in env_entries if e["key"] == "RUNPOD_API_KEY"]
        assert len(api_key_entries) == 1
        assert api_key_entries[0]["value"] == "inject-key"

    @pytest.mark.asyncio
    async def test_update_skips_runtime_injection_when_env_unchanged(self):
        """update() does not inject runtime vars when env is unchanged.

        When env is unchanged, the live template env is echoed back
        (preserving platform-injected vars) without re-injecting
        RUNPOD_API_KEY or other runtime vars.
        """
        env = {"LOG_LEVEL": "INFO"}
        old_resource = ServerlessEndpoint(
            name="update-no-inject",
            imageName="test:latest",
            env=env,
            flashboot=False,
        )
        old_resource.id = "ep-no-inject"
        old_resource.templateId = "tpl-no-inject"

        new_resource = ServerlessEndpoint(
            name="update-no-inject",
            imageName="test:latest",
            env=env,
            flashboot=False,
        )

        live_env = [{"key": "LOG_LEVEL", "value": "INFO"}]
        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-no-inject",
                "name": "update-no-inject",
                "templateId": "tpl-no-inject",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(return_value={"env": live_env})

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                with patch.object(
                    ServerlessResource,
                    "_check_makes_remote_calls",
                    return_value=True,
                ):
                    with patch.dict(os.environ, {"RUNPOD_API_KEY": "inject-key"}):
                        await old_resource.update(new_resource)

        # env IS in the payload (echoed from live), but RUNPOD_API_KEY
        # should NOT be injected since env was unchanged
        template_payload = mock_client.update_template.call_args.args[0]
        assert "env" in template_payload
        env_keys = {e["key"] for e in template_payload["env"]}
        assert "RUNPOD_API_KEY" not in env_keys

    @pytest.mark.asyncio
    async def test_update_includes_env_for_explicit_template_env(self):
        """update() sends env when caller provides explicit template.env with empty env.

        Even if self.env == new_config.env (both empty), explicit template.env
        entries must not be silently dropped.
        """
        old_resource = ServerlessEndpoint(
            name="update-tpl-env",
            imageName="test:latest",
            env={},
            flashboot=False,
        )
        old_resource.id = "ep-tpl-env"
        old_resource.templateId = "tpl-tpl-env"

        new_resource = ServerlessEndpoint(
            name="update-tpl-env",
            imageName="test:latest",
            env={},
            flashboot=False,
            template=PodTemplate(
                name="explicit-tpl",
                imageName="test:latest",
                env=[KeyValuePair(key="EXPLICIT_VAR", value="explicit_val")],
            ),
        )

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-tpl-env",
                "name": "update-tpl-env",
                "templateId": "tpl-tpl-env",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(return_value={"env": []})

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                await old_resource.update(new_resource)

        template_payload = mock_client.update_template.call_args.args[0]
        assert "env" in template_payload
        env_entries = template_payload["env"]
        explicit = [e for e in env_entries if e["key"] == "EXPLICIT_VAR"]
        assert len(explicit) == 1

    @pytest.mark.asyncio
    async def test_update_preserves_platform_injected_env_vars(self):
        """update() preserves platform-injected env vars (e.g. PORT) on env change.

        The platform injects vars like PORT and PORT_HEALTH once at initial
        deploy and does not re-inject on saveTemplate.  When the user changes
        env, the update must read the live template, identify vars not managed
        by user or flash, and carry them forward in the payload.
        """
        old_resource = ServerlessEndpoint(
            name="update-platform-env",
            imageName="test:latest",
            env={"HF_TOKEN": "old-token"},
            flashboot=False,
        )
        old_resource.id = "ep-platform"
        old_resource.templateId = "tpl-platform"

        new_resource = ServerlessEndpoint(
            name="update-platform-env",
            imageName="test:latest",
            env={"HF_TOKEN": "new-token"},
            flashboot=False,
        )

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-platform",
                "name": "update-platform-env",
                "templateId": "tpl-platform",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(
            return_value={
                "env": [
                    {"key": "HF_TOKEN", "value": "old-token"},
                    {"key": "PORT", "value": "8080"},
                    {"key": "PORT_HEALTH", "value": "8081"},
                ]
            }
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                await old_resource.update(new_resource)

        template_payload = mock_client.update_template.call_args.args[0]
        assert "env" in template_payload
        env_entries = template_payload["env"]
        env_keys = {e["key"] for e in env_entries}

        # User env updated
        hf = [e for e in env_entries if e["key"] == "HF_TOKEN"]
        assert len(hf) == 1
        assert hf[0]["value"] == "new-token"

        # Platform vars preserved
        assert "PORT" in env_keys
        assert "PORT_HEALTH" in env_keys

    @pytest.mark.asyncio
    async def test_update_does_not_resurrect_user_removed_env_vars(self):
        """update() does not bring back env vars the user intentionally removed.

        If old config had env={"A": "1", "B": "2"} and new config has
        env={"A": "1"}, key B was in the old user config so it was
        intentionally removed. It must not be preserved even though it
        exists in the live template.
        """
        old_resource = ServerlessEndpoint(
            name="update-no-resurrect",
            imageName="test:latest",
            env={"KEEP": "yes", "REMOVE_ME": "gone"},
            flashboot=False,
        )
        old_resource.id = "ep-resurrect"
        old_resource.templateId = "tpl-resurrect"

        new_resource = ServerlessEndpoint(
            name="update-no-resurrect",
            imageName="test:latest",
            env={"KEEP": "yes"},
            flashboot=False,
        )

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-resurrect",
                "name": "update-no-resurrect",
                "templateId": "tpl-resurrect",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(
            return_value={
                "env": [
                    {"key": "KEEP", "value": "yes"},
                    {"key": "REMOVE_ME", "value": "gone"},
                    {"key": "PORT", "value": "8080"},
                ]
            }
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                await old_resource.update(new_resource)

        template_payload = mock_client.update_template.call_args.args[0]
        env_entries = template_payload["env"]
        env_keys = {e["key"] for e in env_entries}

        assert "KEEP" in env_keys
        assert "PORT" in env_keys  # platform var preserved
        assert "REMOVE_ME" not in env_keys  # user-removed var NOT resurrected

    @pytest.mark.asyncio
    async def test_update_echoes_empty_env_for_default_template_env(self):
        """update() sends empty env when template.env is default and live env is empty.

        PodTemplate.env defaults to []. When env is unchanged, the live
        template env is echoed back.  With an empty live env, the payload
        contains ``env: []`` which satisfies saveTemplate's non-nullable
        requirement without triggering a rolling release.
        """
        old_resource = ServerlessEndpoint(
            name="update-default-tpl",
            imageName="test:latest",
            env={},
            flashboot=False,
        )
        old_resource.id = "ep-default-tpl"
        old_resource.templateId = "tpl-default-tpl"

        # template with default env (not explicitly set)
        new_resource = ServerlessEndpoint(
            name="update-default-tpl",
            imageName="test:latest",
            env={},
            flashboot=False,
            template=PodTemplate(
                name="default-tpl",
                imageName="test:latest",
            ),
        )

        mock_client = AsyncMock()
        mock_client.save_endpoint = AsyncMock(
            return_value={
                "id": "ep-default-tpl",
                "name": "update-default-tpl",
                "templateId": "tpl-default-tpl",
                "gpuIds": "AMPERE_48",
                "allowedCudaVersions": "",
            }
        )
        mock_client.update_template = AsyncMock(return_value={})
        mock_client.get_template = AsyncMock(return_value={"env": []})

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None

            with patch.object(
                ServerlessResource,
                "_ensure_network_volume_deployed",
                new=AsyncMock(),
            ):
                await old_resource.update(new_resource)

        # With env={} on both sides, _configure_existing_template sets
        # template.env=[] which marks env as explicitly set. The update
        # sends env in the payload (empty list), which is harmless.
        template_payload = mock_client.update_template.call_args.args[0]
        env_entries = template_payload.get("env", [])
        assert env_entries == []


class TestServerlessRunsyncTimeout:
    """Test that runsync uses executionTimeoutMs as client timeout."""

    @pytest.fixture
    def resource_with_timeout(self):
        """ServerlessResource with executionTimeoutMs set to 300s."""
        resource = ServerlessResource(
            name="test-gpu-worker",
            executionTimeoutMs=300_000,
        )
        resource.id = "ep-abc123"
        return resource

    @pytest.fixture
    def resource_default_timeout(self):
        """ServerlessResource with default executionTimeoutMs (0)."""
        resource = ServerlessResource(
            name="test-default",
            executionTimeoutMs=0,
        )
        resource.id = "ep-default"
        return resource

    @pytest.mark.asyncio
    async def test_runsync_uses_execution_timeout(self, resource_with_timeout):
        """runsync should use executionTimeoutMs/1000 as client timeout."""
        mock_rp_client = MagicMock()
        mock_rp_client.post.return_value = {
            "id": "job-1",
            "workerId": "w-1",
            "status": "COMPLETED",
            "delayTime": 100,
            "executionTime": 5000,
            "output": {"result": "ok"},
        }

        mock_endpoint = MagicMock()
        mock_endpoint.rp_client = mock_rp_client

        with patch.object(
            ServerlessResource,
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            result = await resource_with_timeout.runsync({"input": "data"})

        # The client timeout should be executionTimeoutMs / 1000 = 300s, not 60s
        mock_rp_client.post.assert_called_once_with(
            "ep-abc123/runsync", {"input": "data"}, timeout=300
        )
        assert result.status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_runsync_default_timeout_when_zero(self, resource_default_timeout):
        """runsync should fall back to 60s when executionTimeoutMs is 0."""
        mock_rp_client = MagicMock()
        mock_rp_client.post.return_value = {
            "id": "job-2",
            "workerId": "w-2",
            "status": "COMPLETED",
            "delayTime": 50,
            "executionTime": 2000,
            "output": None,
        }

        mock_endpoint = MagicMock()
        mock_endpoint.rp_client = mock_rp_client

        with patch.object(
            ServerlessResource,
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            await resource_default_timeout.runsync({"input": "data"})

        mock_rp_client.post.assert_called_once_with(
            "ep-default/runsync", {"input": "data"}, timeout=60
        )

    @pytest.mark.asyncio
    async def test_runsync_default_timeout_when_none(self):
        """runsync should fall back to 60s when executionTimeoutMs is None."""
        resource = ServerlessResource(
            name="test-none",
            executionTimeoutMs=None,
        )
        resource.id = "ep-none"

        mock_rp_client = MagicMock()
        mock_rp_client.post.return_value = {
            "id": "job-3",
            "workerId": "w-3",
            "status": "COMPLETED",
            "delayTime": 10,
            "executionTime": 1000,
            "output": None,
        }

        mock_endpoint = MagicMock()
        mock_endpoint.rp_client = mock_rp_client

        with patch.object(
            ServerlessResource,
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            await resource.runsync({"input": "data"})

        mock_rp_client.post.assert_called_once_with(
            "ep-none/runsync", {"input": "data"}, timeout=60
        )
