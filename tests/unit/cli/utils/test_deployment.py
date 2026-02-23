"""Unit tests for CLI deployment utilities."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.cli.utils.deployment import (
    provision_resources_for_build,
    deploy_from_uploaded_build,
    reconcile_and_provision_resources,
)


@pytest.fixture
def mock_flash_app():
    """Create a mock FlashApp instance."""
    app = AsyncMock()
    app.get_build_manifest = AsyncMock()
    app.update_build_manifest = AsyncMock()
    return app


@pytest.fixture
def mock_resource_manager():
    """Create a mock ResourceManager."""
    manager = MagicMock()
    manager.get_or_deploy_resource = AsyncMock()
    return manager


@pytest.fixture
def mock_deployed_resource():
    """Create a mock deployed resource."""
    resource = MagicMock()
    resource.endpoint_url = "https://example.com/endpoint"
    resource.endpoint_id = "endpoint-id-123"
    return resource


@pytest.mark.asyncio
async def test_provision_resources_for_build_success(
    mock_flash_app,
    mock_deployed_resource,
):
    """Test successful resource provisioning."""
    manifest = {
        "resources": {
            "cpu": {"resource_type": "ServerlessResource"},
            "gpu": {"resource_type": "ServerlessResource"},
        }
    }
    mock_flash_app.get_build_manifest.return_value = manifest

    with (
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
        patch(
            "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
        ) as mock_create_resource,
    ):
        mock_manager = MagicMock()
        mock_manager.get_or_deploy_resource = AsyncMock(
            return_value=mock_deployed_resource
        )
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.side_effect = [MagicMock(), MagicMock()]

        result = await provision_resources_for_build(
            mock_flash_app,
            "build-123",
            "dev",
            show_progress=False,
        )

        assert len(result) == 2
        assert result["cpu"] == "https://example.com/endpoint"
        assert result["gpu"] == "https://example.com/endpoint"
        mock_flash_app.update_build_manifest.assert_called_once()

        # Verify manifest was updated with resources_endpoints
        call_args = mock_flash_app.update_build_manifest.call_args
        updated_manifest = call_args[0][1]
        assert "resources_endpoints" in updated_manifest
        assert len(updated_manifest["resources_endpoints"]) == 2


@pytest.mark.asyncio
async def test_provision_resources_for_build_no_resources(mock_flash_app):
    """Test provisioning with empty manifest."""
    mock_flash_app.get_build_manifest.return_value = {}

    result = await provision_resources_for_build(
        mock_flash_app,
        "build-123",
        "dev",
        show_progress=False,
    )

    assert result == {}
    mock_flash_app.update_build_manifest.assert_not_called()


@pytest.mark.asyncio
async def test_provision_resources_for_build_missing_resources_key(mock_flash_app):
    """Test provisioning when resources key is missing."""
    mock_flash_app.get_build_manifest.return_value = {"other_field": "value"}

    result = await provision_resources_for_build(
        mock_flash_app,
        "build-123",
        "dev",
        show_progress=False,
    )

    assert result == {}
    mock_flash_app.update_build_manifest.assert_not_called()


@pytest.mark.asyncio
async def test_provision_resources_for_build_failure(
    mock_flash_app,
):
    """Test provisioning failure handling."""
    manifest = {
        "resources": {
            "cpu": {"resource_type": "ServerlessResource"},
        }
    }
    mock_flash_app.get_build_manifest.return_value = manifest

    with (
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
        patch(
            "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
        ) as mock_create_resource,
    ):
        mock_manager = MagicMock()
        mock_manager.get_or_deploy_resource = AsyncMock(
            side_effect=Exception("Deployment failed")
        )
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.return_value = MagicMock()

        with pytest.raises(RuntimeError) as exc_info:
            await provision_resources_for_build(
                mock_flash_app,
                "build-123",
                "dev",
                show_progress=False,
            )

        assert "Failed to provision resources" in str(exc_info.value)
        mock_flash_app.update_build_manifest.assert_not_called()


@pytest.mark.asyncio
async def test_provision_resources_for_build_parallel_execution(
    mock_flash_app,
):
    """Test that multiple resources provision in parallel."""
    manifest = {
        "resources": {
            "resource1": {"resource_type": "ServerlessResource"},
            "resource2": {"resource_type": "ServerlessResource"},
            "resource3": {"resource_type": "ServerlessResource"},
        }
    }
    mock_flash_app.get_build_manifest.return_value = manifest

    call_times = []

    async def mock_get_or_deploy_resource(resource):
        call_times.append(__import__("time").time())
        await asyncio.sleep(0.1)
        resource_mock = MagicMock()
        resource_mock.endpoint_url = "https://example.com"
        return resource_mock

    with (
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
        patch(
            "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
        ) as mock_create_resource,
    ):
        mock_manager = MagicMock()
        mock_manager.get_or_deploy_resource = mock_get_or_deploy_resource
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.side_effect = [MagicMock(), MagicMock(), MagicMock()]

        await provision_resources_for_build(
            mock_flash_app,
            "build-123",
            "dev",
            show_progress=False,
        )

        # All tasks should start roughly at the same time (parallel execution)
        # If serial, the time between first and last call would be > 0.2s
        # If parallel, it would be < 0.1s
        if len(call_times) > 1:
            time_diff = max(call_times) - min(call_times)
            assert time_diff < 0.15, f"Tasks not parallel: {time_diff}s difference"


@pytest.mark.asyncio
async def test_deploy_from_uploaded_build_success(
    mock_flash_app, mock_deployed_resource, tmp_path
):
    """Test successful deployment flow with provisioning."""
    mock_flash_app.get_environment_by_name = AsyncMock()
    mock_flash_app.deploy_build_to_environment = AsyncMock(
        return_value={"success": True}
    )
    mock_flash_app.get_build_manifest = AsyncMock(
        return_value={
            "resources": {
                "cpu": {"resource_type": "ServerlessResource"},
            }
        }
    )
    mock_flash_app.update_build_manifest = AsyncMock()

    local_manifest = {
        "resources": {
            "cpu": {"resource_type": "ServerlessResource"},
        },
        "resources_endpoints": {},
    }

    import json

    manifest_dir = tmp_path / ".flash"
    manifest_dir.mkdir()
    manifest_file = manifest_dir / "flash_manifest.json"
    manifest_file.write_text(json.dumps(local_manifest))

    with (
        patch("pathlib.Path.cwd", return_value=tmp_path),
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
        patch(
            "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
        ) as mock_create_resource,
    ):
        mock_manager = MagicMock()
        mock_manager.get_or_deploy_resource = AsyncMock(
            return_value=mock_deployed_resource
        )
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.return_value = MagicMock()

        result = await deploy_from_uploaded_build(
            mock_flash_app, "build-123", "dev", local_manifest
        )

        assert result["success"] is True
        assert "resources_endpoints" in result
        assert "local_manifest" in result
        mock_flash_app.get_environment_by_name.assert_awaited_once_with("dev")
        mock_flash_app.deploy_build_to_environment.assert_awaited_once()


@pytest.mark.asyncio
async def test_deploy_from_uploaded_build_provisioning_failure(
    mock_flash_app, tmp_path
):
    """Test deployment when provisioning fails."""
    mock_flash_app.get_environment_by_name = AsyncMock()
    mock_flash_app.deploy_build_to_environment = AsyncMock(
        return_value={"success": True}
    )
    mock_flash_app.get_build_manifest = AsyncMock(
        return_value={
            "resources": {},
        }
    )

    local_manifest = {
        "resources": {
            "cpu": {"resource_type": "ServerlessResource"},
        },
        "resources_endpoints": {},
    }

    import json

    manifest_dir = tmp_path / ".flash"
    manifest_dir.mkdir()
    manifest_file = manifest_dir / "flash_manifest.json"
    manifest_file.write_text(json.dumps(local_manifest))

    with (
        patch("pathlib.Path.cwd", return_value=tmp_path),
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
        patch(
            "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
        ) as mock_create_resource,
    ):
        mock_manager = MagicMock()
        mock_manager.get_or_deploy_resource = AsyncMock(
            side_effect=Exception("Resource deployment failed")
        )
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.return_value = MagicMock()

        with pytest.raises(RuntimeError) as exc_info:
            await deploy_from_uploaded_build(
                mock_flash_app, "build-123", "dev", local_manifest
            )

        assert "Failed to provision resources" in str(exc_info.value)


@pytest.mark.asyncio
async def test_reconciliation_reprovisions_resources_without_endpoints(tmp_path):
    """Test that resources without endpoints are re-provisioned.

    Scenario: Previous deployment failed, so resources exist in State Manager
    but have no endpoint_url. The reconciliation should detect missing endpoints
    and re-provision those resources.
    """
    import json

    flash_dir = tmp_path / ".flash"
    flash_dir.mkdir()

    # Local manifest has mothership + worker
    local_manifest = {
        "resources": {
            "mothership": {
                "is_mothership": True,
                "resource_type": "CpuLiveLoadBalancer",
            },
            "worker": {
                "is_mothership": False,
                "resource_type": "LiveServerless",
            },
        }
    }
    (flash_dir / "flash_manifest.json").write_text(json.dumps(local_manifest))

    # State Manager has same resources but NO endpoints (failed deployment)
    state_manifest = {
        "resources": {
            "mothership": {
                "is_mothership": True,
                "resource_type": "CpuLiveLoadBalancer",
            },
            "worker": {
                "is_mothership": False,
                "resource_type": "LiveServerless",
            },
        },
        "resources_endpoints": {},  # Empty - previous deployment failed
    }

    app = AsyncMock()
    app.get_build_manifest = AsyncMock(return_value=state_manifest)
    app.update_build_manifest = AsyncMock()

    with (
        patch("pathlib.Path.cwd", return_value=tmp_path),
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
        patch(
            "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
        ) as mock_create_resource,
    ):
        # Both resources should be re-provisioned (marked as "update" action)
        mock_manager = MagicMock()

        mock_mothership = MagicMock()
        mock_mothership.endpoint_url = "https://mothership.api.runpod.ai"
        mock_mothership.endpoint_id = "abc123mothership"

        mock_worker = MagicMock()
        mock_worker.endpoint_url = "https://worker.api.runpod.ai"
        mock_worker.endpoint_id = "xyz789worker"

        mock_manager.get_or_deploy_resource = AsyncMock(
            side_effect=[mock_mothership, mock_worker]
        )
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.side_effect = [MagicMock(), MagicMock()]

        result = await reconcile_and_provision_resources(
            app, "build-123", "dev", local_manifest
        )

    # Both resources should have been provisioned (re-provisioned actually)
    assert "mothership" in result
    assert "worker" in result
    assert result["mothership"] == "https://mothership.api.runpod.ai"
    assert result["worker"] == "https://worker.api.runpod.ai"

    # Verify both resources were provisioned (2 calls to get_or_deploy_resource)
    assert mock_manager.get_or_deploy_resource.call_count == 2

    # Verify manifest was updated with endpoints
    app.update_build_manifest.assert_awaited_once()
    call_args = app.update_build_manifest.call_args
    updated_manifest = call_args[0][1]
    assert "resources_endpoints" in updated_manifest
    assert len(updated_manifest["resources_endpoints"]) == 2


@pytest.mark.asyncio
async def test_provision_resources_persists_ai_key_to_manifest(mock_flash_app):
    manifest = {
        "resources": {
            "cpu": {"resource_type": "ServerlessResource"},
        }
    }
    mock_flash_app.get_build_manifest.return_value = manifest

    deployed = MagicMock()
    deployed.endpoint_url = "https://example.com/endpoint"
    deployed.id = "endpoint-123"
    deployed.aiKey = "ai-key-123"

    with (
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
        patch(
            "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
        ) as mock_create_resource,
    ):
        mock_manager = MagicMock()
        mock_manager.get_or_deploy_resource = AsyncMock(return_value=deployed)
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.return_value = MagicMock()

        await provision_resources_for_build(
            mock_flash_app,
            "build-123",
            "dev",
            show_progress=False,
        )

    call_args = mock_flash_app.update_build_manifest.call_args
    updated_manifest = call_args[0][1]
    assert updated_manifest["resources"]["cpu"]["endpoint_id"] == "endpoint-123"
    assert updated_manifest["resources"]["cpu"]["aiKey"] == "ai-key-123"


@pytest.mark.asyncio
async def test_reconciliation_copies_ai_key_from_state_manifest(tmp_path):
    import json

    flash_dir = tmp_path / ".flash"
    flash_dir.mkdir()

    local_manifest = {
        "resources": {
            "worker": {
                "resource_type": "LiveServerless",
                "config": "same",
                "endpoint_id": "endpoint-123",
                "aiKey": "ai-key-123",
            },
        },
        "resources_endpoints": {},
    }
    (flash_dir / "flash_manifest.json").write_text(json.dumps(local_manifest))

    state_manifest = {
        "resources": {
            "worker": {
                "resource_type": "LiveServerless",
                "config": "same",
                "endpoint_id": "endpoint-123",
                "aiKey": "ai-key-123",
            },
        },
        "resources_endpoints": {
            "worker": "https://worker.api.runpod.ai",
        },
    }

    app = AsyncMock()
    app.get_build_manifest = AsyncMock(return_value=state_manifest)
    app.update_build_manifest = AsyncMock()

    with (
        patch("pathlib.Path.cwd", return_value=tmp_path),
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
    ):
        mock_manager = MagicMock()
        mock_manager.get_or_deploy_resource = AsyncMock()
        mock_manager_cls.return_value = mock_manager

        await reconcile_and_provision_resources(app, "build-123", "dev", local_manifest)

    updated_manifest = app.update_build_manifest.call_args[0][1]
    assert updated_manifest["resources"]["worker"]["endpoint_id"] == "endpoint-123"
    assert updated_manifest["resources"]["worker"]["aiKey"] == "ai-key-123"
    assert (
        updated_manifest["resources_endpoints"]["worker"]
        == "https://worker.api.runpod.ai"
    )
