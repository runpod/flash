"""
Tests for LoadBalancerSlsResource provisioning and health checks.
"""

import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from runpod_flash.core.resources import (
    LoadBalancerSlsResource,
    ServerlessType,
    ServerlessScalerType,
)
from runpod_flash.core.resources.serverless import ServerlessResource

# Set a dummy API key for tests that create ResourceManager instances
os.environ.setdefault("RUNPOD_API_KEY", "test-key-for-unit-tests")


class TestLoadBalancerSlsResourceCreation:
    """Test LoadBalancerSlsResource creation and validation."""

    def test_create_with_defaults(self):
        """Test creating LoadBalancerSlsResource with minimal config."""
        resource = LoadBalancerSlsResource(
            name="test-endpoint",
            imageName="test-image:latest",
        )

        # Note: name should not get -fb appended anymore
        assert resource.name == "test-endpoint"
        assert resource.flashBootType == "FLASHBOOT"
        assert resource.imageName == "test-image:latest"
        assert resource.type == ServerlessType.LB
        assert resource.scalerType == ServerlessScalerType.REQUEST_COUNT

    def test_type_always_lb(self):
        """Test that type is always LB regardless of input."""
        # Try to set type to QB - should be overridden to LB
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            type=ServerlessType.QB,  # This should be overridden
        )

        assert resource.type == ServerlessType.LB

    def test_scaler_type_defaults_to_request_count(self):
        """Test that scaler type defaults to REQUEST_COUNT for LB."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
        )

        assert resource.scalerType == ServerlessScalerType.REQUEST_COUNT

    def test_validate_lb_configuration_rejects_queue_delay(self):
        """Test that QUEUE_DELAY scaler is rejected for LB endpoints."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            scalerType=ServerlessScalerType.QUEUE_DELAY,
        )

        with pytest.raises(ValueError, match="requires REQUEST_COUNT scaler"):
            resource._validate_lb_configuration()

    def test_with_custom_env_vars(self):
        """Test creating LB resource with custom environment variables."""
        env = {
            "FLASH_APP": "my_app",
            "LOG_LEVEL": "DEBUG",
        }

        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            env=env,
        )

        assert resource.env == env

    def test_with_worker_config(self):
        """Test creating LB resource with worker scaling config."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            workersMin=1,
            workersMax=5,
            scalerValue=10,
        )

        assert resource.workersMin == 1
        assert resource.workersMax == 5
        assert resource.scalerValue == 10

    def test_endpoint_url_format_for_load_balanced_endpoints(self):
        """Test that endpoint_url uses load-balanced format, not v2 API format."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="6g2hfns3ar5pti",
        )

        # Load-balanced endpoints use: https://{id}.api.runpod.ai
        # NOT: https://api.runpod.ai/v2/{id}
        assert resource.endpoint_url == "https://6g2hfns3ar5pti.api.runpod.ai"

    def test_endpoint_url_raises_without_id(self):
        """Test that endpoint_url raises error when endpoint ID not set."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
        )

        with pytest.raises(ValueError, match="Endpoint ID not set"):
            _ = resource.endpoint_url


class TestLoadBalancerSlsResourceDeployment:
    """Test deployment flow."""

    @pytest.mark.asyncio
    async def test_do_deploy_validates_configuration(self):
        """Test that _do_deploy validates LB configuration."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            scalerType=ServerlessScalerType.QUEUE_DELAY,
        )

        with pytest.raises(ValueError, match="requires REQUEST_COUNT scaler"):
            await resource._do_deploy()

    @pytest.mark.asyncio
    async def test_do_deploy_already_deployed(self):
        """Test _do_deploy skips deployment if already deployed."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="existing-id",
        )

        with patch.object(
            LoadBalancerSlsResource,
            "is_deployed",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await resource._do_deploy()

            assert result == resource

    @pytest.mark.asyncio
    async def test_do_deploy_success(self):
        """Test successful deployment without health check blocking."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
        )

        mock_deployed = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="new-endpoint-id",
        )

        with (
            patch.object(
                LoadBalancerSlsResource,
                "is_deployed",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(
                ServerlessResource,
                "_do_deploy",
                new_callable=AsyncMock,
                return_value=mock_deployed,
            ),
        ):
            result = await resource._do_deploy()

            assert result == mock_deployed

    @pytest.mark.asyncio
    async def test_do_deploy_parent_deploy_failure(self):
        """Test deployment handles parent deploy failure."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
        )

        with (
            patch.object(
                LoadBalancerSlsResource,
                "is_deployed",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(
                ServerlessResource,
                "_do_deploy",
                new_callable=AsyncMock,
                side_effect=ValueError("RunPod API error"),
            ),
        ):
            with pytest.raises(ValueError, match="RunPod API error"):
                await resource._do_deploy()


class TestLoadBalancerSlsResourceIntegration:
    """Integration tests with ResourceManager."""

    def test_resource_manager_integration(self):
        """Test that LoadBalancerSlsResource can be created and used."""
        # Test that LoadBalancerSlsResource can be instantiated and used
        resource = LoadBalancerSlsResource(
            name="integration-test",
            imageName="test-image:latest",
        )

        assert isinstance(resource, LoadBalancerSlsResource)
        assert resource.type == ServerlessType.LB

    @pytest.mark.asyncio
    async def test_is_deployed_endpoint_exists(self):
        """Test is_deployed returns True when GQL confirms endpoint exists."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-id",
        )

        mock_client = AsyncMock()
        mock_client.endpoint_exists = AsyncMock(return_value=True)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # patch on the method's own globals dict so the mock survives
        # sys.modules manipulation by other tests (test_dotenv_loading
        # deletes and re-imports runpod_flash.core.* modules)
        globs = LoadBalancerSlsResource.is_deployed.__globals__
        original = globs["RunpodGraphQLClient"]
        globs["RunpodGraphQLClient"] = MagicMock(return_value=mock_client)
        try:
            result = await resource.is_deployed()
            assert result is True
        finally:
            globs["RunpodGraphQLClient"] = original

    @pytest.mark.asyncio
    async def test_is_deployed_endpoint_not_found(self):
        """Test is_deployed returns False when endpoint not found via GQL."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="nonexistent-id",
        )

        mock_client = AsyncMock()
        mock_client.endpoint_exists = AsyncMock(return_value=False)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        globs = LoadBalancerSlsResource.is_deployed.__globals__
        original = globs["RunpodGraphQLClient"]
        globs["RunpodGraphQLClient"] = MagicMock(return_value=mock_client)
        try:
            result = await resource.is_deployed()
            assert result is False
        finally:
            globs["RunpodGraphQLClient"] = original

    @pytest.mark.asyncio
    async def test_is_deployed_no_id(self):
        """Test is_deployed returns False when no ID."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
        )

        result = await resource.is_deployed()

        assert result is False
