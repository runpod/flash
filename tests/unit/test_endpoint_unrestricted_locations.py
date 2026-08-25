"""tests for unrestricted serverless endpoint placement."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.datacenter import DataCenter
from runpod_flash.core.resources.gpu import GpuGroup
from runpod_flash.core.resources.load_balancer_sls_resource import (
    LoadBalancerSlsResource,
)
from runpod_flash.core.resources.network_volume import NetworkVolume
from runpod_flash.core.resources.serverless import CudaVersion, ServerlessScalerType
from runpod_flash.core.resources.template import PodTemplate
from runpod_flash.endpoint import Endpoint


class TestEndpointUnrestrictedLocations:
    def test_default_gpu_endpoint_keeps_all_datacenters(self):
        endpoint = Endpoint(name="default-placement", gpu=GpuGroup.ADA_24)

        config = endpoint._build_resource_config()

        assert endpoint.datacenter == DataCenter.all()
        assert config.datacenter == DataCenter.all()
        assert config.locations

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"}, clear=True)
    async def test_unrestricted_endpoint_deploys_without_location_payload(self):
        endpoint = Endpoint(
            name="unrestricted",
            image="example/image:v1",
            gpu=GpuGroup.ADA_24,
            gpu_count=2,
            workers=(1, 3),
            idle_timeout=90,
            execution_timeout_ms=12_000,
            scaler_type=ServerlessScalerType.REQUEST_COUNT,
            scaler_value=7,
            min_cuda_version=CudaVersion.V12_4,
            unrestricted_locations=True,
        )
        config = endpoint._build_resource_config()
        mock_client = AsyncMock()
        mock_client.save_endpoint.return_value = {
            "id": "endpoint-123",
            "name": "unrestricted",
            "templateId": "template-123",
            "gpuIds": config.gpuIds,
            "gpuCount": 2,
            "allowedCudaVersions": "",
        }

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as client_class:
            client_class.return_value.__aenter__.return_value = mock_client
            client_class.return_value.__aexit__.return_value = None
            deployed = await config._do_deploy()

        payload = mock_client.save_endpoint.call_args.args[0]
        assert config.datacenter is None
        assert config.locations is None
        assert deployed.unrestrictedLocations is True
        assert deployed.datacenter is None
        assert deployed.locations is None
        assert "locations" not in payload
        assert "unrestrictedLocations" not in payload
        assert payload["gpuIds"] == config.gpuIds
        assert payload["gpuCount"] == 2
        assert payload["template"]["imageName"] == "example/image:v1"
        assert payload["minCudaVersion"] == "12.4"
        assert payload["workersMin"] == 1
        assert payload["workersMax"] == 3
        assert payload["scalerType"] == "REQUEST_COUNT"
        assert payload["scalerValue"] == 7
        assert payload["idleTimeout"] == 90
        assert payload["executionTimeoutMs"] == 12_000

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "FLASH_IS_LIVE_PROVISIONING": "false",
            "RUNPOD_DEFAULT_LOCATIONS": "US-TX-3",
            "RUNPOD_DEFAULT_DATACENTER": "EU-RO-1",
        },
        clear=True,
    )
    async def test_unrestricted_endpoint_ignores_ambient_location_defaults(self):
        endpoint = Endpoint(
            name="unrestricted-env",
            image="example/image:v1",
            unrestricted_locations=True,
        )
        config = endpoint._build_resource_config()
        mock_client = AsyncMock()
        mock_client.save_endpoint.return_value = {
            "id": "endpoint-env",
            "name": "unrestricted-env",
            "templateId": "template-env",
            "gpuIds": config.gpuIds,
            "allowedCudaVersions": "",
        }

        with patch(
            "runpod_flash.core.resources.serverless.RunpodGraphQLClient"
        ) as client_class:
            client_class.return_value.__aenter__.return_value = mock_client
            client_class.return_value.__aexit__.return_value = None
            await config._do_deploy()

        payload = mock_client.save_endpoint.call_args.args[0]
        assert config.datacenter is None
        assert config.locations is None
        assert "locations" not in payload
        assert "unrestrictedLocations" not in payload

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"}, clear=True)
    def test_unrestricted_load_balanced_endpoint_uses_same_placement_contract(self):
        endpoint = Endpoint(
            name="unrestricted-lb",
            template=PodTemplate(imageName="example/image:v1"),
            unrestricted_locations=True,
        )

        @endpoint.get("/health")
        async def health():
            return {"ok": True}

        config = endpoint._build_resource_config()

        assert isinstance(config, LoadBalancerSlsResource)
        assert config.unrestrictedLocations is True
        assert config.datacenter is None
        assert config.locations is None

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"cpu": CpuInstanceType.CPU3G_2_8}, "gpu endpoints"),
            ({"id": "endpoint-123"}, "newly provisioned"),
            ({"datacenter": DataCenter.EU_RO_1}, "datacenter"),
            ({"volume": NetworkVolume(name="volume", size=10)}, "network volume"),
            (
                {
                    "volume": [
                        NetworkVolume(
                            name="volume-list", size=10, dataCenterId=DataCenter.EU_RO_1
                        )
                    ]
                },
                "network volume",
            ),
        ],
    )
    def test_unrestricted_endpoint_rejects_incompatible_options(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            Endpoint(
                name="invalid-unrestricted",
                unrestricted_locations=True,
                **kwargs,
            )
