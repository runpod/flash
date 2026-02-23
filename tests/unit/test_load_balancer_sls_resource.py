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

        # Note: name gets -fb suffix added by sync_input_fields due to flashboot=True
        assert resource.name == "test-endpoint-fb"
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


class TestLoadBalancerSlsResourceHealthCheck:
    """Test health check functionality."""

    @staticmethod
    def _create_mock_client(
        status_code: int = 200, error: Exception = None
    ) -> MagicMock:
        """Create properly configured async context manager mock client."""
        mock_response = AsyncMock()
        mock_response.status_code = status_code
        mock_client = MagicMock()
        if error:
            mock_client.get = AsyncMock(side_effect=error)
        else:
            mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        return mock_client

    @pytest.mark.asyncio
    async def test_check_ping_endpoint_success(self):
        """Test successful ping endpoint check with ID set."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        mock_client = self._create_mock_client(200)
        with (
            patch.object(
                LoadBalancerSlsResource,
                "endpoint_url",
                new_callable=lambda: property(lambda self: "https://test-endpoint.com"),
            ),
            patch(
                "runpod_flash.core.utils.http.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await resource._check_ping_endpoint()

            assert result is True

    @pytest.mark.asyncio
    async def test_check_ping_endpoint_initializing(self):
        """Test ping endpoint returning 204 (initializing)."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        mock_client = self._create_mock_client(204)
        with (
            patch.object(
                LoadBalancerSlsResource,
                "endpoint_url",
                new_callable=lambda: property(lambda self: "https://test-endpoint.com"),
            ),
            patch(
                "runpod_flash.core.utils.http.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await resource._check_ping_endpoint()

            assert result is True

    @pytest.mark.asyncio
    async def test_check_ping_endpoint_failure(self):
        """Test ping endpoint returning unhealthy status."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        mock_client = self._create_mock_client(503)
        with (
            patch.object(
                LoadBalancerSlsResource,
                "endpoint_url",
                new_callable=lambda: property(lambda self: "https://test-endpoint.com"),
            ),
            patch(
                "runpod_flash.core.utils.http.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await resource._check_ping_endpoint()

            assert result is False

    @pytest.mark.asyncio
    async def test_check_ping_endpoint_connection_error(self):
        """Test ping endpoint with connection error."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        mock_client = self._create_mock_client(
            error=ConnectionError("Connection refused")
        )
        with (
            patch.object(
                LoadBalancerSlsResource,
                "endpoint_url",
                new_callable=lambda: property(lambda self: "https://test-endpoint.com"),
            ),
            patch(
                "runpod_flash.core.utils.http.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await resource._check_ping_endpoint()

            assert result is False

    @pytest.mark.asyncio
    async def test_check_ping_endpoint_no_id(self):
        """Test ping check when endpoint ID is not set."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            # id not set
        )

        result = await resource._check_ping_endpoint()
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_health_success(self):
        """Test health check polling with successful response."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        with patch.object(resource, "_check_ping_endpoint") as mock_check:
            mock_check.return_value = True

            result = await resource._wait_for_health(max_retries=3)

            assert result is True
            mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_health_retry_then_success(self):
        """Test health check polling with retries before success."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        with patch.object(resource, "_check_ping_endpoint") as mock_check:
            # Fail twice, then succeed
            mock_check.side_effect = [False, False, True]

            result = await resource._wait_for_health(max_retries=5, retry_interval=0)

            assert result is True
            assert mock_check.call_count == 3

    @pytest.mark.asyncio
    async def test_wait_for_health_timeout(self):
        """Test health check polling timeout after max retries."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        with patch.object(resource, "_check_ping_endpoint") as mock_check:
            mock_check.return_value = False

            result = await resource._wait_for_health(max_retries=3, retry_interval=0)

            assert result is False
            assert mock_check.call_count == 3

    @pytest.mark.asyncio
    async def test_wait_for_health_no_id(self):
        """Test health check when endpoint ID not set."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            # id not set
        )

        with pytest.raises(ValueError, match="Cannot wait for health"):
            await resource._wait_for_health()

    @pytest.mark.asyncio
    async def test_is_deployed_async_with_id(self):
        """Test is_deployed_async returns True when healthy."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        with patch.object(resource, "_check_ping_endpoint") as mock_check:
            mock_check.return_value = True

            result = await resource.is_deployed_async()

            assert result is True

    @pytest.mark.asyncio
    async def test_is_deployed_async_without_id(self):
        """Test is_deployed_async returns False when ID not set."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
        )

        result = await resource.is_deployed_async()

        assert result is False

    @pytest.mark.asyncio
    async def test_is_deployed_async_unhealthy(self):
        """Test is_deployed_async returns False when unhealthy."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-endpoint-id",
        )

        with patch.object(resource, "_check_ping_endpoint") as mock_check:
            mock_check.return_value = False

            result = await resource.is_deployed_async()

            assert result is False


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

        with patch.object(LoadBalancerSlsResource, "is_deployed") as mock_deployed:
            mock_deployed.return_value = True

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
                LoadBalancerSlsResource, "is_deployed", MagicMock(return_value=False)
            ),
            patch.object(
                resource, "_wait_for_health", new_callable=AsyncMock
            ) as mock_wait,
            patch.object(
                ServerlessResource,
                "_do_deploy",
                new_callable=AsyncMock,
                return_value=mock_deployed,
            ),
        ):
            result = await resource._do_deploy()

            assert result == mock_deployed
            # Health check should not be called during deployment
            mock_wait.assert_not_called()

    @pytest.mark.asyncio
    async def test_do_deploy_parent_deploy_failure(self):
        """Test deployment handles parent deploy failure."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
        )

        with (
            patch.object(
                LoadBalancerSlsResource, "is_deployed", MagicMock(return_value=False)
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

    def test_is_deployed_sync(self):
        """Test synchronous is_deployed method."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
            id="test-id",
        )

        # Mock the endpoint property and its health method
        mock_endpoint = MagicMock()
        mock_endpoint.health.return_value = {"status": "healthy"}

        with patch.object(
            LoadBalancerSlsResource,
            "endpoint",
            new_callable=lambda: property(lambda self: mock_endpoint),
        ):
            result = resource.is_deployed()

            assert result is True
            mock_endpoint.health.assert_called_once()

    def test_is_deployed_sync_no_id(self):
        """Test is_deployed returns False when no ID."""
        resource = LoadBalancerSlsResource(
            name="test",
            imageName="image",
        )

        result = resource.is_deployed()

        assert result is False
