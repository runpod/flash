"""Unit tests for DeploymentOrchestrator."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from runpod_flash.core.deployment import (
    DeploymentOrchestrator,
    DeploymentStatus,
)
from runpod_flash.core.resources.serverless import ServerlessResource


class TestDeploymentOrchestrator:
    """Test DeploymentOrchestrator functionality."""

    @pytest.fixture
    def mock_resources(self):
        """Create mock resources for testing."""
        resource1 = MagicMock(spec=ServerlessResource)
        resource1.name = "gpu-endpoint-1"
        resource1.id = "endpoint-1"
        resource1.is_deployed = AsyncMock(return_value=False)

        resource2 = MagicMock(spec=ServerlessResource)
        resource2.name = "gpu-endpoint-2"
        resource2.id = "endpoint-2"
        resource2.is_deployed = AsyncMock(return_value=False)

        resource3 = MagicMock(spec=ServerlessResource)
        resource3.name = "cpu-endpoint-1"
        resource3.id = "endpoint-3"
        resource3.is_deployed = AsyncMock(return_value=False)

        return [resource1, resource2, resource3]

    @pytest.fixture
    def mock_cached_resource(self):
        """Create a mock resource that is already deployed."""
        resource = MagicMock(spec=ServerlessResource)
        resource.name = "cached-endpoint"
        resource.id = "cached-1"
        resource.is_deployed = AsyncMock(return_value=True)
        return resource

    @pytest.mark.asyncio
    async def test_deploy_all_empty_list(self):
        """Test deploy_all with empty resource list."""
        orchestrator = DeploymentOrchestrator()
        results = await orchestrator.deploy_all([])

        assert results == []

    @pytest.mark.asyncio
    async def test_deploy_all_single_resource(self, mock_resources):
        """Test deploy_all with single resource."""
        orchestrator = DeploymentOrchestrator()

        # Mock ResourceManager
        with patch.object(
            orchestrator.manager, "get_or_deploy_resource", new_callable=AsyncMock
        ) as mock_deploy:
            mock_deploy.return_value = mock_resources[0]

            results = await orchestrator.deploy_all([mock_resources[0]])

            assert len(results) == 1
            assert results[0].status == DeploymentStatus.SUCCESS
            assert results[0].resource == mock_resources[0]
            mock_deploy.assert_called_once()

    @pytest.mark.asyncio
    async def test_deploy_all_multiple_resources(self, mock_resources):
        """Test deploy_all with multiple resources."""
        orchestrator = DeploymentOrchestrator(max_concurrent=3)

        # Mock ResourceManager
        with patch.object(
            orchestrator.manager, "get_or_deploy_resource", new_callable=AsyncMock
        ) as mock_deploy:
            mock_deploy.side_effect = mock_resources

            results = await orchestrator.deploy_all(mock_resources)

            assert len(results) == 3
            assert all(r.status == DeploymentStatus.SUCCESS for r in results)
            assert mock_deploy.call_count == 3

    @pytest.mark.asyncio
    async def test_deploy_cached_resource(self, mock_cached_resource):
        """Test deploy_all with already deployed resource."""
        orchestrator = DeploymentOrchestrator()

        with patch.object(
            orchestrator.manager, "get_or_deploy_resource", new_callable=AsyncMock
        ):
            results = await orchestrator.deploy_all([mock_cached_resource])

            assert len(results) == 1
            assert results[0].status == DeploymentStatus.CACHED
            assert results[0].endpoint_id == "cached-1"

    @pytest.mark.asyncio
    async def test_deploy_with_failure(self, mock_resources):
        """Test deploy_all handles deployment failures gracefully."""
        orchestrator = DeploymentOrchestrator()

        # Mock ResourceManager to raise exception
        with patch.object(
            orchestrator.manager, "get_or_deploy_resource", new_callable=AsyncMock
        ) as mock_deploy:
            mock_deploy.side_effect = Exception("Deployment failed")

            results = await orchestrator.deploy_all([mock_resources[0]])

            assert len(results) == 1
            assert results[0].status == DeploymentStatus.FAILED
            assert "Deployment failed" in results[0].error

    @pytest.mark.asyncio
    async def test_parallel_deployment_concurrency(self, mock_resources):
        """Test that parallel deployment respects max_concurrent limit."""
        orchestrator = DeploymentOrchestrator(max_concurrent=2)

        concurrent_count = 0
        max_concurrent_observed = 0

        async def mock_deploy(resource):
            nonlocal concurrent_count, max_concurrent_observed
            concurrent_count += 1
            max_concurrent_observed = max(max_concurrent_observed, concurrent_count)

            # Simulate deployment time
            await asyncio.sleep(0.1)

            concurrent_count -= 1
            return resource

        with patch.object(
            orchestrator.manager, "get_or_deploy_resource", new_callable=AsyncMock
        ) as mock_deploy_fn:
            mock_deploy_fn.side_effect = mock_deploy

            await orchestrator.deploy_all(mock_resources)

            # Verify concurrency was limited to 2
            assert max_concurrent_observed <= 2

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, mock_resources):
        """Test deploy_all with mix of successful and failed deployments."""
        orchestrator = DeploymentOrchestrator()

        # First succeeds, second fails, third succeeds
        async def deploy_side_effect(resource):
            if resource.name == "gpu-endpoint-2":
                raise Exception("Deployment failed")
            return resource

        with patch.object(
            orchestrator.manager, "get_or_deploy_resource", new_callable=AsyncMock
        ) as mock_deploy:
            mock_deploy.side_effect = deploy_side_effect

            results = await orchestrator.deploy_all(mock_resources)

            assert len(results) == 3
            assert results[0].status == DeploymentStatus.SUCCESS
            assert results[1].status == DeploymentStatus.FAILED
            assert results[2].status == DeploymentStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_deployment_duration_tracking(self, mock_resources):
        """Test that deployment duration is tracked."""
        orchestrator = DeploymentOrchestrator()

        async def slow_deploy(resource):
            await asyncio.sleep(0.1)
            return resource

        with patch.object(
            orchestrator.manager, "get_or_deploy_resource", new_callable=AsyncMock
        ) as mock_deploy:
            mock_deploy.side_effect = slow_deploy

            results = await orchestrator.deploy_all([mock_resources[0]])

            assert len(results) == 1
            assert results[0].duration >= 0.09

    def test_deploy_all_background(self, mock_resources):
        """Test background deployment doesn't block."""
        orchestrator = DeploymentOrchestrator()

        with patch.object(
            orchestrator.manager, "get_or_deploy_resource", new_callable=AsyncMock
        ) as mock_deploy:
            mock_deploy.side_effect = mock_resources

            # Should not block
            orchestrator.deploy_all_background(mock_resources)

            # Background thread should be started
            # (not much we can test here without waiting for thread)

    def test_deploy_all_background_empty_list(self):
        """Test background deployment with empty list."""
        orchestrator = DeploymentOrchestrator()

        # Should handle gracefully
        orchestrator.deploy_all_background([])
