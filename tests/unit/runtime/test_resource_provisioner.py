"""Unit tests for resource provisioner module."""

import os
from unittest.mock import patch

import pytest

from runpod_flash.runtime.resource_provisioner import (
    create_resource_from_manifest,
)


class TestCreateResourceFromManifest:
    """Tests for create_resource_from_manifest function."""

    def test_create_resource_from_manifest_serverless(self):
        """Test creating ServerlessResource from manifest."""
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert isinstance(resource, ServerlessResource)
            # ServerlessResource may append "-fb" suffix during initialization
            assert resource_name in resource.name
            assert resource.env["FLASH_RESOURCE_NAME"] == resource_name

    def test_create_resource_from_manifest_live_serverless(self):
        """Test that LiveServerless type is accepted but creates ServerlessResource.

        Note: Current implementation creates ServerlessResource regardless of type.
        This is a known limitation - manifest needs to include full deployment config
        to properly construct different resource types.
        """
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "resource_type": "LiveServerless",
            "imageName": "runpod/flash:latest",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            # Should not raise - LiveServerless is in supported types
            resource = create_resource_from_manifest(resource_name, resource_data)

            # Returns ServerlessResource (current limitation)
            assert isinstance(resource, ServerlessResource)
            assert resource_name in resource.name

    def test_create_resource_from_manifest_unsupported_type(self):
        """Test that ValueError is raised for unsupported resource types."""
        resource_name = "worker1"
        resource_data = {"resource_type": "UnsupportedResourceType"}

        with pytest.raises(ValueError, match="Unsupported resource type"):
            create_resource_from_manifest(resource_name, resource_data)

    def test_create_resource_from_manifest_default_type(self):
        """Test that default type is ServerlessResource when not specified."""
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "imageName": "runpod/flash:latest"
        }  # No resource_type specified

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert isinstance(resource, ServerlessResource)
            assert resource_name in resource.name

    def test_create_resource_from_manifest_cli_context_no_runpod_endpoint_id(self):
        """Test resource creation in CLI context without RUNPOD_ENDPOINT_ID."""
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
        }

        # Clear RUNPOD_ENDPOINT_ID to simulate CLI environment
        with patch.dict(os.environ, {}, clear=True):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert isinstance(resource, ServerlessResource)
            assert resource_name in resource.name
            assert resource.env["FLASH_RESOURCE_NAME"] == resource_name

    def test_create_resource_from_manifest_runtime_context_with_endpoint_id(self):
        """Test resource creation in runtime context.

        When running inside an endpoint, RUNPOD_ENDPOINT_ID is available.
        """
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-456"}):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert isinstance(resource, ServerlessResource)
            assert resource_name in resource.name
            assert resource.env["FLASH_RESOURCE_NAME"] == resource_name

    def test_create_resource_from_manifest_cpu_live_serverless(self):
        """Test creating CpuLiveServerless from manifest."""
        from runpod_flash.core.resources.live_serverless import CpuLiveServerless

        resource_name = "cpu_worker"
        resource_data = {"resource_type": "CpuLiveServerless"}

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert isinstance(resource, CpuLiveServerless)
            assert resource_name in resource.name
            assert resource.env["FLASH_RESOURCE_NAME"] == resource_name

    def test_create_resource_lb_via_is_load_balanced_sets_endpoint_type(self):
        """Test that is_load_balanced=True sets FLASH_ENDPOINT_TYPE=lb."""
        resource_name = "lb_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "is_load_balanced": True,
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert resource.env["FLASH_ENDPOINT_TYPE"] == "lb"

    def test_create_resource_non_lb_does_not_set_endpoint_type(self):
        """Test that non-LB resources do NOT get FLASH_ENDPOINT_TYPE."""
        resource_name = "plain_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert "FLASH_ENDPOINT_TYPE" not in resource.env

    def test_create_resource_lb_sets_main_file_and_app_variable(self):
        """Test that FLASH_MAIN_FILE and FLASH_APP_VARIABLE still work for LB resources."""
        resource_name = "lb_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "is_load_balanced": True,
            "main_file": "app.py",
            "app_variable": "my_app",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert resource.env["FLASH_ENDPOINT_TYPE"] == "lb"
            assert resource.env["FLASH_MAIN_FILE"] == "app.py"
            assert resource.env["FLASH_APP_VARIABLE"] == "my_app"

    def test_create_resource_lb_via_is_load_balanced_with_main_file(self):
        """Test main_file and app_variable work with is_load_balanced flag too."""
        resource_name = "lb_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "is_load_balanced": True,
            "main_file": "server.py",
            "app_variable": "server_app",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert resource.env["FLASH_ENDPOINT_TYPE"] == "lb"
            assert resource.env["FLASH_MAIN_FILE"] == "server.py"
            assert resource.env["FLASH_APP_VARIABLE"] == "server_app"

    def test_create_resource_injects_api_key_when_makes_remote_calls(self):
        """Test RUNPOD_API_KEY injected when makes_remote_calls is True."""
        resource_name = "caller_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "makes_remote_calls": True,
        }

        with patch.dict(
            os.environ,
            {
                "RUNPOD_ENDPOINT_ID": "endpoint-123",
                "RUNPOD_API_KEY": "test-api-key-secret",
            },
        ):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert resource.env["RUNPOD_API_KEY"] == "test-api-key-secret"

    def test_create_resource_skips_api_key_when_no_remote_calls(self):
        """Test RUNPOD_API_KEY NOT injected when makes_remote_calls is False."""
        resource_name = "isolated_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "makes_remote_calls": False,
        }

        with patch.dict(
            os.environ,
            {
                "RUNPOD_ENDPOINT_ID": "endpoint-123",
                "RUNPOD_API_KEY": "test-api-key-secret",
            },
        ):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert "RUNPOD_API_KEY" not in resource.env

    def test_create_resource_injects_flash_environment_id_when_makes_remote_calls(self):
        """Test FLASH_ENVIRONMENT_ID injected when makes_remote_calls and flash_environment_id passed."""
        resource_name = "caller_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "makes_remote_calls": True,
        }

        with patch.dict(
            os.environ,
            {
                "RUNPOD_ENDPOINT_ID": "endpoint-123",
                "RUNPOD_API_KEY": "test-api-key-secret",
            },
        ):
            resource = create_resource_from_manifest(
                resource_name,
                resource_data,
                flash_environment_id="flash-env-abc123",
            )

            assert resource.env["FLASH_ENVIRONMENT_ID"] == "flash-env-abc123"
            assert resource.env["RUNPOD_API_KEY"] == "test-api-key-secret"

    def test_create_resource_skips_flash_env_id_when_no_remote_calls(self):
        """Test FLASH_ENVIRONMENT_ID NOT injected when makes_remote_calls is False."""
        resource_name = "isolated_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "makes_remote_calls": False,
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}):
            resource = create_resource_from_manifest(
                resource_name,
                resource_data,
                flash_environment_id="flash-env-abc123",
            )

            assert "FLASH_ENVIRONMENT_ID" not in resource.env

    def test_endpoint_gpu_qb_resolves_to_live_serverless(self):
        """Test Endpoint resource_type with gpuIds resolves to LiveServerless."""
        from runpod_flash.core.resources.live_serverless import LiveServerless

        resource = create_resource_from_manifest(
            "gpu-worker",
            {"resource_type": "Endpoint", "gpuIds": "any", "imageName": "img:latest"},
        )
        assert isinstance(resource, LiveServerless)

    def test_endpoint_cpu_qb_resolves_to_cpu_live_serverless(self):
        """Test Endpoint resource_type without gpuIds resolves to CpuLiveServerless."""
        from runpod_flash.core.resources.live_serverless import CpuLiveServerless

        resource = create_resource_from_manifest(
            "cpu-worker",
            {"resource_type": "Endpoint"},
        )
        assert isinstance(resource, CpuLiveServerless)

    def test_endpoint_gpu_lb_resolves_to_live_load_balancer(self):
        """Test Endpoint LB with gpuIds resolves to LiveLoadBalancer."""
        from runpod_flash.core.resources.live_serverless import LiveLoadBalancer

        resource = create_resource_from_manifest(
            "gpu-api",
            {
                "resource_type": "Endpoint",
                "is_load_balanced": True,
                "gpuIds": "any",
                "imageName": "img:latest",
            },
        )
        assert isinstance(resource, LiveLoadBalancer)

    def test_endpoint_cpu_lb_resolves_to_cpu_live_load_balancer(self):
        """Test Endpoint LB without gpuIds resolves to CpuLiveLoadBalancer."""
        from runpod_flash.core.resources.live_serverless import CpuLiveLoadBalancer

        resource = create_resource_from_manifest(
            "cpu-api",
            {"resource_type": "Endpoint", "is_load_balanced": True},
        )
        assert isinstance(resource, CpuLiveLoadBalancer)

    def test_create_resource_skips_api_key_when_not_set(self):
        """Test RUNPOD_API_KEY NOT injected when env var is not set."""
        resource_name = "caller_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "makes_remote_calls": True,
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-123"}, clear=True):
            resource = create_resource_from_manifest(resource_name, resource_data)

            assert "RUNPOD_API_KEY" not in resource.env
