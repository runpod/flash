"""Unit tests for CLI deployment utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.cli.utils.deployment import (
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

    # Local manifest has load balancer + worker
    local_manifest = {
        "resources": {
            "lb_endpoint": {
                "is_load_balanced": True,
                "resource_type": "CpuLiveLoadBalancer",
            },
            "worker": {
                "is_load_balanced": False,
                "resource_type": "LiveServerless",
            },
        }
    }
    (flash_dir / "flash_manifest.json").write_text(json.dumps(local_manifest))

    # State Manager has same resources but NO endpoints (failed deployment)
    state_manifest = {
        "resources": {
            "lb_endpoint": {
                "is_load_balanced": True,
                "resource_type": "CpuLiveLoadBalancer",
            },
            "worker": {
                "is_load_balanced": False,
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

        mock_lb_endpoint = MagicMock()
        mock_lb_endpoint.endpoint_url = "https://lb.api.runpod.ai"
        mock_lb_endpoint.endpoint_id = "abc123lb"

        mock_worker = MagicMock()
        mock_worker.endpoint_url = "https://worker.api.runpod.ai"
        mock_worker.endpoint_id = "xyz789worker"

        mock_manager.get_or_deploy_resource = AsyncMock(
            side_effect=[mock_lb_endpoint, mock_worker]
        )
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.side_effect = [MagicMock(), MagicMock()]

        result = await reconcile_and_provision_resources(
            app, "build-123", "dev", local_manifest
        )

    # Both resources should have been provisioned (re-provisioned actually)
    assert "lb_endpoint" in result
    assert "worker" in result
    assert result["lb_endpoint"] == "https://lb.api.runpod.ai"
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
async def test_deploy_fails_when_api_key_missing_for_remote_calls(tmp_path):
    """Raises ValueError when RUNPOD_API_KEY is unset and a resource makes remote calls."""
    import json

    flash_dir = tmp_path / ".flash"
    flash_dir.mkdir()

    local_manifest = {
        "resources": {
            "gpu_worker": {
                "resource_type": "LiveServerless",
                "makes_remote_calls": True,
            },
        }
    }
    (flash_dir / "flash_manifest.json").write_text(json.dumps(local_manifest))

    app = AsyncMock()
    app.get_build_manifest = AsyncMock(return_value={})

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("runpod_flash.core.credentials.get_api_key", return_value=None),
    ):
        with pytest.raises(ValueError) as exc_info:
            await reconcile_and_provision_resources(
                app, "build-123", "dev", local_manifest
            )

        assert "RUNPOD_API_KEY" in str(exc_info.value)
        assert "remote calls" in str(exc_info.value)


@pytest.mark.asyncio
async def test_deploy_succeeds_without_api_key_when_no_remote_calls(tmp_path):
    """No error when RUNPOD_API_KEY is unset but no resource makes remote calls."""
    import json

    flash_dir = tmp_path / ".flash"
    flash_dir.mkdir()

    local_manifest = {
        "resources": {
            "cpu_service": {
                "resource_type": "CpuLiveLoadBalancer",
                "makes_remote_calls": False,
            },
        }
    }
    (flash_dir / "flash_manifest.json").write_text(json.dumps(local_manifest))

    # State manifest matches local so no provisioning needed
    state_manifest = {
        "resources": {
            "cpu_service": {
                "resource_type": "CpuLiveLoadBalancer",
                "makes_remote_calls": False,
            },
        },
        "resources_endpoints": {
            "cpu_service": "https://cpu.api.runpod.ai",
        },
    }

    app = AsyncMock()
    app.get_build_manifest = AsyncMock(return_value=state_manifest)
    app.update_build_manifest = AsyncMock()

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("pathlib.Path.cwd", return_value=tmp_path),
    ):
        import os

        os.environ.pop("RUNPOD_API_KEY", None)

        # Should not raise -- no remote callers, so API key not required
        await reconcile_and_provision_resources(
            app, "build-123", "dev", local_manifest, show_progress=False
        )


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

    with open(flash_dir / "flash_manifest.json") as f:
        persisted_manifest = json.load(f)
    assert "aiKey" not in persisted_manifest["resources"]["worker"]


@pytest.mark.asyncio
async def test_reconciliation_ignores_runtime_fields_in_config_comparison(tmp_path):
    import json

    flash_dir = tmp_path / ".flash"
    flash_dir.mkdir()

    local_manifest = {
        "resources": {
            "worker": {
                "resource_type": "LiveServerless",
                "config": "same",
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
                "aiKey": "ai-key-123",
                "endpoint_id": "endpoint-123",
                "templateId": "template-123",
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

    mock_manager.get_or_deploy_resource.assert_not_called()


@pytest.mark.asyncio
async def test_source_fingerprint_injected_into_resource_env(tmp_path):
    """Source fingerprint from manifest is injected into each resource's env.

    Both manifests have identical config and env except for the fingerprint
    value. This isolates the fingerprint as the sole driver of the update path.
    """
    import json

    flash_dir = tmp_path / ".flash"
    flash_dir.mkdir()

    # Local and state manifests are structurally identical except for the
    # fingerprint value in env. If any other field differs, the test would
    # not prove the injection is what triggered the update.
    local_manifest = {
        "source_fingerprint": "new_fingerprint_abc",
        "resources": {
            "worker": {
                "resource_type": "LiveServerless",
                "config": "same",
                "env": {},
            },
            "lb_endpoint": {
                "resource_type": "CpuLiveLoadBalancer",
                "config": "same",
                "env": {"USER_VAR": "value"},
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
                "env": {"_FLASH_SOURCE_FINGERPRINT": "old_fingerprint_000"},
            },
            "lb_endpoint": {
                "resource_type": "CpuLiveLoadBalancer",
                "config": "same",
                "env": {
                    "USER_VAR": "value",
                    "_FLASH_SOURCE_FINGERPRINT": "old_fingerprint_000",
                },
            },
        },
        "resources_endpoints": {
            "worker": "https://worker.api.runpod.ai",
            "lb_endpoint": "https://lb.api.runpod.ai",
        },
    }

    app = AsyncMock()
    app.get_build_manifest = AsyncMock(return_value=state_manifest)
    app.update_build_manifest = AsyncMock()

    mock_resource = MagicMock()
    mock_resource.endpoint_url = "https://new.api.runpod.ai"
    mock_resource.endpoint_id = "new-endpoint-id"

    with (
        patch("pathlib.Path.cwd", return_value=tmp_path),
        patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_manager_cls,
        patch(
            "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
        ) as mock_create_resource,
    ):
        mock_manager = MagicMock()
        mock_manager.get_or_deploy_resource = AsyncMock(return_value=mock_resource)
        mock_manager_cls.return_value = mock_manager
        mock_create_resource.return_value = MagicMock()

        await reconcile_and_provision_resources(
            app, "build-123", "dev", local_manifest, show_progress=False
        )

    # Fingerprint is the only diff -> both resources should have been updated
    assert mock_manager.get_or_deploy_resource.call_count == 2

    # Verify injection overwrote the fingerprint with the new value
    worker_env = local_manifest["resources"]["worker"]["env"]
    assert worker_env["_FLASH_SOURCE_FINGERPRINT"] == "new_fingerprint_abc"

    lb_env = local_manifest["resources"]["lb_endpoint"]["env"]
    assert lb_env["_FLASH_SOURCE_FINGERPRINT"] == "new_fingerprint_abc"
    # User-defined env vars preserved after injection
    assert lb_env["USER_VAR"] == "value"


@pytest.mark.asyncio
async def test_source_fingerprint_unchanged_takes_reuse_path(tmp_path):
    """When source fingerprint matches state, reuse path is taken (no update)."""
    import json

    flash_dir = tmp_path / ".flash"
    flash_dir.mkdir()

    local_manifest = {
        "source_fingerprint": "same_fingerprint_abc",
        "resources": {
            "worker": {
                "resource_type": "LiveServerless",
                "config": "same",
            },
        },
        "resources_endpoints": {},
    }
    (flash_dir / "flash_manifest.json").write_text(json.dumps(local_manifest))

    # State manifest has SAME fingerprint (code unchanged)
    state_manifest = {
        "resources": {
            "worker": {
                "resource_type": "LiveServerless",
                "config": "same",
                "env": {"_FLASH_SOURCE_FINGERPRINT": "same_fingerprint_abc"},
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

        await reconcile_and_provision_resources(
            app, "build-123", "dev", local_manifest, show_progress=False
        )

    # Fingerprint unchanged -> reuse path, no provisioning
    mock_manager.get_or_deploy_resource.assert_not_called()

    # Endpoint info copied from state
    assert (
        local_manifest["resources_endpoints"]["worker"]
        == "https://worker.api.runpod.ai"
    )


@pytest.mark.asyncio
async def test_missing_source_fingerprint_backward_compatible(tmp_path):
    """Manifests without source_fingerprint behave as before (reuse when config matches)."""
    import json

    flash_dir = tmp_path / ".flash"
    flash_dir.mkdir()

    # No source_fingerprint key -- older flash version
    local_manifest = {
        "resources": {
            "worker": {
                "resource_type": "LiveServerless",
                "config": "same",
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

        await reconcile_and_provision_resources(
            app, "build-123", "dev", local_manifest, show_progress=False
        )

    # No fingerprint -> no injection -> config matches -> reuse path
    mock_manager.get_or_deploy_resource.assert_not_called()
    assert (
        local_manifest["resources_endpoints"]["worker"]
        == "https://worker.api.runpod.ai"
    )
