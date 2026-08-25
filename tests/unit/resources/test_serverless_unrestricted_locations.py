"""tests for unrestricted placement in serverless resources."""

import os
from unittest.mock import AsyncMock, patch

import cloudpickle
import pytest

from runpod_flash.core.resources.base import BaseResource
from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.datacenter import DataCenter
from runpod_flash.core.resources.live_serverless import (
    CpuLiveLoadBalancer,
    CpuLiveServerless,
)
from runpod_flash.core.resources.load_balancer_sls_resource import (
    CpuLoadBalancerSlsResource,
    LoadBalancerSlsResource,
)
from runpod_flash.core.resources.network_volume import NetworkVolume
from runpod_flash.core.resources.serverless import (
    ServerlessEndpoint,
    ServerlessResource,
)
from runpod_flash.core.resources.serverless_cpu import CpuServerlessEndpoint


def _hydrated_unrestricted(name: str = "hydrated-id-bound") -> ServerlessEndpoint:
    config = ServerlessEndpoint(
        name=name,
        imageName="example/image:v1",
        flashboot=False,
        unrestrictedLocations=True,
    )
    return config._hydrate_graphql_result(
        {
            "id": "trusted-id",
            "name": name,
            "templateId": "template-id",
            "gpuIds": config.gpuIds,
        }
    )


class TestServerlessUnrestrictedLocations:
    def test_unrestricted_intent_changes_resource_identity(self):
        default = ServerlessEndpoint(
            name="identity",
            imageName="example/image:v1",
            flashboot=False,
        )
        unrestricted = ServerlessEndpoint(
            name="identity",
            imageName="example/image:v1",
            flashboot=False,
            unrestrictedLocations=True,
        )

        assert default.resource_id != unrestricted.resource_id
        assert default.config_hash != unrestricted.config_hash

    def test_unrestricted_flag_is_input_only_and_hashed(self):
        input_only = ServerlessResource._input_only
        hashed_fields = ServerlessResource._hashed_fields
        if hasattr(input_only, "default"):
            input_only = input_only.default
        if hasattr(hashed_fields, "default"):
            hashed_fields = hashed_fields.default

        assert "unrestrictedLocations" in input_only
        assert "unrestrictedLocations" in hashed_fields

    def test_unrestricted_resource_rejects_datacenter(self):
        with pytest.raises(ValueError, match="datacenter"):
            ServerlessEndpoint(
                name="invalid",
                imageName="example/image:v1",
                datacenter=DataCenter.EU_RO_1,
                unrestrictedLocations=True,
            )

    @pytest.mark.parametrize(
        "volume_kwargs",
        [
            {"networkVolume": NetworkVolume(name="volume", size=10)},
            {"networkVolumes": [NetworkVolume(name="volume-list", size=10)]},
            {"networkVolumeId": "volume-123"},
        ],
    )
    def test_unrestricted_resource_rejects_network_volume(self, volume_kwargs):
        with pytest.raises(ValueError, match="network volumes"):
            ServerlessEndpoint(
                name="invalid-volume",
                imageName="example/image:v1",
                unrestrictedLocations=True,
                **volume_kwargs,
            )

    @pytest.mark.asyncio
    async def test_unrestricted_resource_rejects_deployed_volume_ids(self):
        resource = ServerlessEndpoint(
            name="invalid-deployed-volume",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        )
        resource._deployed_volume_ids = ["volume-123"]

        with pytest.raises(ValueError, match="network volumes"):
            await resource._ensure_network_volume_deployed()

    @pytest.mark.parametrize(
        "resource_class",
        [
            CpuServerlessEndpoint,
            CpuLoadBalancerSlsResource,
            CpuLiveServerless,
            CpuLiveLoadBalancer,
        ],
    )
    @pytest.mark.parametrize("instance_ids", [None, []])
    def test_unrestricted_resource_rejects_cpu_class_capability(
        self, resource_class, instance_ids
    ):
        with pytest.raises(ValueError, match="GPU endpoints"):
            resource_class(
                name="invalid-cpu",
                imageName="example/image:v1",
                instanceIds=instance_ids,
                unrestrictedLocations=True,
            )

    @pytest.mark.parametrize(
        "resource_class",
        [ServerlessEndpoint, LoadBalancerSlsResource],
    )
    def test_generic_gpu_resource_rejects_effective_cpu_shape(self, resource_class):
        with pytest.raises(ValueError, match="GPU endpoints"):
            resource_class(
                name="invalid-generic-cpu",
                imageName="example/image:v1",
                instanceIds=[CpuInstanceType.CPU3G_2_8],
                unrestrictedLocations=True,
            )

    @pytest.mark.parametrize(
        "resource_class",
        [ServerlessEndpoint, LoadBalancerSlsResource],
    )
    def test_generic_gpu_hydration_rejects_provider_cpu_shape(self, resource_class):
        resource = resource_class(
            name="invalid-hydrated-cpu",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        )

        with pytest.raises(ValueError, match="GPU endpoints"):
            resource._hydrate_graphql_result(
                {
                    "id": "endpoint-cpu",
                    "name": "invalid-hydrated-cpu",
                    "templateId": "template-cpu",
                    "instanceIds": [CpuInstanceType.CPU3G_2_8.value],
                }
            )

    @pytest.mark.parametrize(
        "marker_name",
        [
            "providerHydratedUnrestricted",
            "provider_hydrated_unrestricted",
            "_provider_hydrated_unrestricted",
            "_provider_hydrated_unrestricted_id",
        ],
    )
    def test_public_hydration_marker_input_cannot_authorize_id(self, marker_name):
        payload = {
            "name": "marker-reset",
            "id": "endpoint-existing",
            "imageName": "example/image:v1",
            "unrestrictedLocations": True,
            marker_name: "endpoint-existing",
        }

        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            ServerlessEndpoint(**payload)
        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            ServerlessEndpoint.model_validate(payload)

    def test_public_hydration_marker_is_not_a_model_field(self):
        assert "providerHydratedUnrestricted" not in ServerlessEndpoint.model_fields

    @pytest.mark.parametrize(
        "resource_class",
        [ServerlessEndpoint, LoadBalancerSlsResource],
    )
    def test_public_resource_rejects_id_with_unrestricted_placement(
        self, resource_class
    ):
        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            resource_class(
                name="invalid-existing",
                id="endpoint-existing",
                imageName="example/image:v1",
                unrestrictedLocations=True,
                providerHydratedUnrestricted=True,
            )

    @pytest.mark.parametrize(
        "marker_name",
        [
            "providerHydratedUnrestricted",
            "provider_hydrated_unrestricted",
            "_provider_hydrated_unrestricted",
            "_provider_hydrated_unrestricted_id",
        ],
    )
    def test_model_construct_marker_cannot_authorize_id(self, marker_name):
        resource = ServerlessEndpoint.model_construct(
            name="constructed-marker",
            id="endpoint-existing",
            imageName="example/image:v1",
            unrestrictedLocations=True,
            **{marker_name: "endpoint-existing"},
        )

        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            resource._validate_unrestricted_placement()

    def test_direct_marker_assignment_is_rejected(self):
        resource = ServerlessEndpoint(
            name="invalid-public-marker",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        )

        with pytest.raises(ValueError, match="provenance is internal"):
            resource.providerHydratedUnrestricted = True
        with pytest.raises(ValueError, match="provenance is internal"):
            resource._provider_hydrated_unrestricted_id = "endpoint-existing"

        resource.id = "endpoint-existing"
        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            resource._validate_unrestricted_placement()

    def test_hydrated_id_substitution_rejected_before_validate(self):
        resource = _hydrated_unrestricted()

        resource.id = "substituted-id"

        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            resource._validate_unrestricted_placement()

    def test_model_copy_preserves_provenance_only_without_id_change(self):
        resource = _hydrated_unrestricted()

        copied = resource.model_copy()
        copied._validate_unrestricted_placement()
        assert copied.id == "trusted-id"
        assert copied._get_provider_hydrated_unrestricted_id() == "trusted-id"

        forged = resource.model_copy(
            update={
                "id": "restricted-id",
                "providerHydratedUnrestricted": True,
                "_provider_hydrated_unrestricted_id": "restricted-id",
            }
        )
        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            forged._validate_unrestricted_placement()

    @pytest.mark.asyncio
    async def test_hydrated_id_substitution_rejected_before_is_deployed(self):
        resource = _hydrated_unrestricted("substituted-health")
        resource.id = "substituted-id"

        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            await resource.is_deployed()

    @pytest.mark.asyncio
    async def test_hydrated_id_substitution_rejected_before_do_deploy(self):
        resource = _hydrated_unrestricted("substituted-deploy")
        resource.id = "substituted-id"

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as client_class:
            with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
                await resource._do_deploy()

        client_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_hydrated_id_substitution_rejected_before_update_api_mutation(self):
        resource = _hydrated_unrestricted("substituted-update")
        resource.id = "substituted-id"
        new_config = ServerlessEndpoint(
            name="substituted-update",
            imageName="example/image:v2",
            flashboot=False,
            unrestrictedLocations=True,
        )

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as client_class:
            with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
                await resource.update(new_config)

        client_class.assert_not_called()

    @pytest.mark.parametrize(
        "marker_name",
        [
            "providerHydratedUnrestricted",
            "provider_hydrated_unrestricted",
            "_provider_hydrated_unrestricted",
            "_provider_hydrated_unrestricted_id",
        ],
    )
    def test_direct_setstate_old_marker_cannot_authorize_id(self, marker_name):
        state = ServerlessEndpoint(
            name="restored-old-marker",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        ).__getstate__()
        state["id"] = "restricted-id"
        state[marker_name] = "restricted-id"
        restored = object.__new__(ServerlessEndpoint)

        with pytest.raises(ValueError, match="missing trusted provider provenance"):
            restored.__setstate__(state)
        assert restored._get_provider_hydrated_unrestricted_id() is None

    def test_direct_setstate_matching_provenance_key_cannot_authorize_id(self):
        state = ServerlessEndpoint(
            name="restored-matching-key",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        ).__getstate__()
        state["id"] = "restricted-id"
        state[ServerlessResource._UNRESTRICTED_PROVENANCE_STATE_KEY] = "restricted-id"
        restored = object.__new__(ServerlessEndpoint)

        with pytest.raises(ValueError, match="untrusted provider provenance"):
            restored.__setstate__(state)
        assert restored._get_provider_hydrated_unrestricted_id() is None

    def test_cloudpickle_round_trip_preserves_exact_id_provenance(self):
        resource = _hydrated_unrestricted("pickle-round-trip")

        restored = cloudpickle.loads(cloudpickle.dumps(resource))

        assert restored.id == "trusted-id"
        assert restored._get_provider_hydrated_unrestricted_id() == "trusted-id"
        restored._validate_unrestricted_placement()

    def test_setstate_rejects_mismatched_exact_id_provenance(self):
        resource = _hydrated_unrestricted("pickle-tampered")
        state = resource.__getstate__()
        state["id"] = "substituted-id"
        restored = object.__new__(ServerlessEndpoint)

        with pytest.raises(ValueError, match="mismatched provider provenance"):
            restored.__setstate__(state)
        assert restored._get_provider_hydrated_unrestricted_id() is None

    def test_base_setstate_public_marker_cannot_authorize_id(self):
        state = ServerlessEndpoint(
            name="base-setstate-old-marker",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        ).__getstate__()
        state["id"] = "restricted-id"
        state["providerHydratedUnrestricted"] = True
        restored = object.__new__(ServerlessEndpoint)

        BaseResource.__setstate__(restored, state)

        assert restored._get_provider_hydrated_unrestricted_id() is None
        with pytest.raises(ValueError, match="exact provider-hydrated endpoint"):
            restored._validate_unrestricted_placement()

    @pytest.mark.asyncio
    async def test_post_construction_id_rejected_before_is_deployed_early_return(self):
        resource = ServerlessEndpoint(
            name="invalid-mutated-id-health",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        )
        resource.id = "endpoint-existing"

        with pytest.raises(ValueError, match="newly provisioned"):
            await resource.is_deployed()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"}, clear=True)
    async def test_post_construction_id_rejected_before_deploy_early_return(self):
        resource = ServerlessEndpoint(
            name="invalid-mutated-id",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        )
        resource.id = "endpoint-existing"

        with pytest.raises(ValueError, match="newly provisioned"):
            await resource._do_deploy()

    @pytest.mark.parametrize(
        "field_name,value",
        [
            ("networkVolumeId", "late-volume-id"),
            ("networkVolume", NetworkVolume(name="late-volume", size=10)),
            (
                "networkVolumes",
                [NetworkVolume(name="late-volume-list", size=10)],
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_post_construction_volume_rejected_before_remote_deploy(
        self, field_name, value
    ):
        resource = ServerlessEndpoint(
            name="invalid-mutated-volume",
            imageName="example/image:v1",
            unrestrictedLocations=True,
        )
        setattr(resource, field_name, value)

        with (
            patch.object(
                NetworkVolume,
                "deploy",
                new=AsyncMock(),
            ) as deploy_volume,
            patch(
                "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
            ) as client_class,
        ):
            with pytest.raises(ValueError, match="network volumes"):
                await resource._do_deploy()

        deploy_volume.assert_not_awaited()
        client_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_hydration_and_update_preserve_unrestricted_intent(self):
        initial = ServerlessEndpoint(
            name="hydrated",
            imageName="example/image:v1",
            flashboot=False,
            unrestrictedLocations=True,
        )
        deploy_client = AsyncMock()
        deploy_client.save_endpoint.return_value = {
            "id": "endpoint-hydrated",
            "name": "hydrated",
            "templateId": "template-hydrated",
            "gpuIds": initial.gpuIds,
            "allowedCudaVersions": "",
        }

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as client_class:
            client_class.return_value.__aenter__.return_value = deploy_client
            client_class.return_value.__aexit__.return_value = None
            hydrated = await initial._do_deploy()

        assert hydrated.unrestrictedLocations is True
        assert hydrated.datacenter is None
        assert hydrated.locations is None
        assert hydrated._get_provider_hydrated_unrestricted_id() == hydrated.id

        persisted = cloudpickle.loads(cloudpickle.dumps(hydrated))
        assert persisted.id == "endpoint-hydrated"
        assert persisted.unrestrictedLocations is True
        assert persisted.locations is None
        assert persisted._get_provider_hydrated_unrestricted_id() == persisted.id
        persisted._validate_unrestricted_placement()

        updated_config = ServerlessEndpoint(
            name="hydrated",
            templateId="template-hydrated",
            flashboot=False,
            unrestrictedLocations=True,
            workersMax=5,
        )
        update_client = AsyncMock()
        update_client.save_endpoint.return_value = {
            "id": "endpoint-hydrated",
            "name": "hydrated",
            "templateId": "template-hydrated",
            "gpuIds": updated_config.gpuIds,
            "allowedCudaVersions": "",
            "workersMax": 5,
        }

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as client_class:
            client_class.return_value.__aenter__.return_value = update_client
            client_class.return_value.__aexit__.return_value = None
            updated = await hydrated.update(updated_config)

        payload = update_client.save_endpoint.call_args.args[0]
        assert payload["id"] == "endpoint-hydrated"
        assert "locations" not in payload
        assert "unrestrictedLocations" not in payload
        assert updated.unrestrictedLocations is True
        assert updated.datacenter is None
        assert updated.locations is None

    @pytest.mark.asyncio
    async def test_hydration_rejects_backend_restricted_state(self):
        initial = ServerlessEndpoint(
            name="hydrated-backend-locations",
            imageName="example/image:v1",
            flashboot=False,
            unrestrictedLocations=True,
        )
        mock_client = AsyncMock()
        mock_client.save_endpoint.return_value = {
            "id": "endpoint-backend-locations",
            "name": "hydrated-backend-locations",
            "templateId": "template-backend-locations",
            "gpuIds": initial.gpuIds,
            "allowedCudaVersions": "",
            "locations": "US-TX-3",
        }

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as client_class:
            client_class.return_value.__aenter__.return_value = mock_client
            client_class.return_value.__aexit__.return_value = None
            with pytest.raises(ValueError, match="locations cannot be set"):
                await initial._do_deploy()

    @pytest.mark.parametrize(
        "provider_volume_field,provider_volume_value",
        [
            ("networkVolumeId", "provider-volume"),
            (
                "networkVolumeIds",
                [{"networkVolumeId": "provider-volume"}],
            ),
        ],
    )
    def test_hydration_rejects_provider_network_volumes(
        self, provider_volume_field, provider_volume_value
    ):
        initial = ServerlessEndpoint(
            name="hydrated-provider-volume",
            imageName="example/image:v1",
            flashboot=False,
            unrestrictedLocations=True,
        )

        with pytest.raises(ValueError, match="network volumes"):
            initial._hydrate_graphql_result(
                {
                    "id": "endpoint-provider-volume",
                    "name": "hydrated-provider-volume",
                    "templateId": "template-provider-volume",
                    "gpuIds": initial.gpuIds,
                    provider_volume_field: provider_volume_value,
                }
            )

    def test_update_rejects_provider_id_substitution(self):
        existing = _hydrated_unrestricted("provider-id-substitution")
        new_config = ServerlessEndpoint(
            name="provider-id-substitution",
            imageName="example/image:v2",
            flashboot=False,
            unrestrictedLocations=True,
        )

        with pytest.raises(ValueError, match="does not match the updated endpoint"):
            new_config._hydrate_graphql_result(
                {
                    "id": "substituted-id",
                    "name": "provider-id-substitution",
                    "gpuIds": new_config.gpuIds,
                },
                expected_id=existing.id,
            )
