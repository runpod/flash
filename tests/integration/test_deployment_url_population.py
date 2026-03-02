"""Integration tests for endpoint URL population in reconcile_and_provision_resources.

Verifies that the deployment pipeline correctly:
1. Populates resources_endpoints after provisioning resources
2. Pushes the updated manifest (with URLs) to State Manager via FlashApp
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.cli.utils.deployment import reconcile_and_provision_resources


@pytest.fixture
def mock_flash_app():
    """Create a mock FlashApp with async methods for build manifest operations."""
    app = AsyncMock()
    app.get_build_manifest = AsyncMock(return_value={})
    app.update_build_manifest = AsyncMock()
    return app


@pytest.fixture
def two_resource_manifest():
    """Local manifest with two resources for provisioning."""
    return {
        "resources": {
            "gpu_worker": {
                "resource_type": "ServerlessResource",
                "config": "gpu_v1",
            },
            "cpu_worker": {
                "resource_type": "ServerlessResource",
                "config": "cpu_v1",
            },
        }
    }


@pytest.fixture
def mock_deployed_resources():
    """Two mock deployed resources with distinct endpoint URLs and IDs."""
    gpu = MagicMock()
    gpu.endpoint_url = "https://gpu-worker.api.runpod.ai"
    gpu.endpoint_id = "ep-gpu-001"

    cpu = MagicMock()
    cpu.endpoint_url = "https://cpu-worker.api.runpod.ai"
    cpu.endpoint_id = "ep-cpu-002"

    return gpu, cpu


class TestResourcesEndpointsPopulatedAfterProvisioning:
    """Verify resources_endpoints is populated in the returned dict and local manifest."""

    @pytest.mark.asyncio
    async def test_returned_dict_contains_both_resource_urls(
        self, mock_flash_app, two_resource_manifest, mock_deployed_resources, tmp_path
    ):
        """reconcile_and_provision_resources returns a dict mapping resource names to URLs."""
        flash_dir = tmp_path / ".flash"
        flash_dir.mkdir()

        mock_gpu, mock_cpu = mock_deployed_resources

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_rm_cls,
            patch(
                "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
            ) as mock_create,
        ):
            mock_manager = MagicMock()
            mock_manager.get_or_deploy_resource = AsyncMock(
                side_effect=[mock_cpu, mock_gpu]
            )
            mock_rm_cls.return_value = mock_manager
            mock_create.side_effect = [MagicMock(), MagicMock()]

            result = await reconcile_and_provision_resources(
                mock_flash_app,
                "build-100",
                "staging",
                two_resource_manifest,
                show_progress=False,
            )

        assert "cpu_worker" in result
        assert "gpu_worker" in result
        assert result["cpu_worker"] == "https://cpu-worker.api.runpod.ai"
        assert result["gpu_worker"] == "https://gpu-worker.api.runpod.ai"

    @pytest.mark.asyncio
    async def test_local_manifest_resources_endpoints_populated(
        self, mock_flash_app, two_resource_manifest, mock_deployed_resources, tmp_path
    ):
        """local_manifest dict is mutated in-place with resources_endpoints mapping."""
        flash_dir = tmp_path / ".flash"
        flash_dir.mkdir()

        mock_gpu, mock_cpu = mock_deployed_resources

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_rm_cls,
            patch(
                "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
            ) as mock_create,
        ):
            mock_manager = MagicMock()
            mock_manager.get_or_deploy_resource = AsyncMock(
                side_effect=[mock_cpu, mock_gpu]
            )
            mock_rm_cls.return_value = mock_manager
            mock_create.side_effect = [MagicMock(), MagicMock()]

            await reconcile_and_provision_resources(
                mock_flash_app,
                "build-100",
                "staging",
                two_resource_manifest,
                show_progress=False,
            )

        assert "resources_endpoints" in two_resource_manifest
        endpoints = two_resource_manifest["resources_endpoints"]
        assert len(endpoints) == 2
        assert endpoints["cpu_worker"] == "https://cpu-worker.api.runpod.ai"
        assert endpoints["gpu_worker"] == "https://gpu-worker.api.runpod.ai"

    @pytest.mark.asyncio
    async def test_local_manifest_file_written_with_endpoints(
        self, mock_flash_app, two_resource_manifest, mock_deployed_resources, tmp_path
    ):
        """The local .flash/flash_manifest.json file contains resources_endpoints after call."""
        flash_dir = tmp_path / ".flash"
        flash_dir.mkdir()

        mock_gpu, mock_cpu = mock_deployed_resources

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_rm_cls,
            patch(
                "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
            ) as mock_create,
        ):
            mock_manager = MagicMock()
            mock_manager.get_or_deploy_resource = AsyncMock(
                side_effect=[mock_cpu, mock_gpu]
            )
            mock_rm_cls.return_value = mock_manager
            mock_create.side_effect = [MagicMock(), MagicMock()]

            await reconcile_and_provision_resources(
                mock_flash_app,
                "build-100",
                "staging",
                two_resource_manifest,
                show_progress=False,
            )

        manifest_file = flash_dir / "flash_manifest.json"
        assert manifest_file.exists()

        written_manifest = json.loads(manifest_file.read_text())
        assert "resources_endpoints" in written_manifest
        assert (
            written_manifest["resources_endpoints"]["cpu_worker"]
            == "https://cpu-worker.api.runpod.ai"
        )
        assert (
            written_manifest["resources_endpoints"]["gpu_worker"]
            == "https://gpu-worker.api.runpod.ai"
        )

    @pytest.mark.asyncio
    async def test_endpoint_ids_written_to_resource_configs(
        self, mock_flash_app, two_resource_manifest, mock_deployed_resources, tmp_path
    ):
        """endpoint_id from deployed resources is written back into each resource config."""
        flash_dir = tmp_path / ".flash"
        flash_dir.mkdir()

        mock_gpu, mock_cpu = mock_deployed_resources

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_rm_cls,
            patch(
                "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
            ) as mock_create,
        ):
            mock_manager = MagicMock()
            mock_manager.get_or_deploy_resource = AsyncMock(
                side_effect=[mock_cpu, mock_gpu]
            )
            mock_rm_cls.return_value = mock_manager
            mock_create.side_effect = [MagicMock(), MagicMock()]

            await reconcile_and_provision_resources(
                mock_flash_app,
                "build-100",
                "staging",
                two_resource_manifest,
                show_progress=False,
            )

        assert (
            two_resource_manifest["resources"]["cpu_worker"]["endpoint_id"]
            == "ep-cpu-002"
        )
        assert (
            two_resource_manifest["resources"]["gpu_worker"]["endpoint_id"]
            == "ep-gpu-001"
        )


class TestStateManagerReceivesManifestWithUrls:
    """Verify app.update_build_manifest() is called with manifest containing URLs."""

    @pytest.mark.asyncio
    async def test_update_build_manifest_called_with_endpoints(
        self, mock_flash_app, two_resource_manifest, mock_deployed_resources, tmp_path
    ):
        """app.update_build_manifest is called with a manifest that has resources_endpoints."""
        flash_dir = tmp_path / ".flash"
        flash_dir.mkdir()

        mock_gpu, mock_cpu = mock_deployed_resources

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_rm_cls,
            patch(
                "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
            ) as mock_create,
        ):
            mock_manager = MagicMock()
            mock_manager.get_or_deploy_resource = AsyncMock(
                side_effect=[mock_cpu, mock_gpu]
            )
            mock_rm_cls.return_value = mock_manager
            mock_create.side_effect = [MagicMock(), MagicMock()]

            await reconcile_and_provision_resources(
                mock_flash_app,
                "build-100",
                "staging",
                two_resource_manifest,
                show_progress=False,
            )

        mock_flash_app.update_build_manifest.assert_awaited_once()
        call_args = mock_flash_app.update_build_manifest.call_args
        build_id_arg = call_args[0][0]
        manifest_arg = call_args[0][1]

        assert build_id_arg == "build-100"
        assert "resources_endpoints" in manifest_arg
        assert (
            manifest_arg["resources_endpoints"]["cpu_worker"]
            == "https://cpu-worker.api.runpod.ai"
        )
        assert (
            manifest_arg["resources_endpoints"]["gpu_worker"]
            == "https://gpu-worker.api.runpod.ai"
        )

    @pytest.mark.asyncio
    async def test_update_build_manifest_manifest_preserves_resources(
        self, mock_flash_app, two_resource_manifest, mock_deployed_resources, tmp_path
    ):
        """The manifest pushed to State Manager still contains the original resources section."""
        flash_dir = tmp_path / ".flash"
        flash_dir.mkdir()

        mock_gpu, mock_cpu = mock_deployed_resources

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_rm_cls,
            patch(
                "runpod_flash.cli.utils.deployment.create_resource_from_manifest"
            ) as mock_create,
        ):
            mock_manager = MagicMock()
            mock_manager.get_or_deploy_resource = AsyncMock(
                side_effect=[mock_cpu, mock_gpu]
            )
            mock_rm_cls.return_value = mock_manager
            mock_create.side_effect = [MagicMock(), MagicMock()]

            await reconcile_and_provision_resources(
                mock_flash_app,
                "build-100",
                "staging",
                two_resource_manifest,
                show_progress=False,
            )

        manifest_arg = mock_flash_app.update_build_manifest.call_args[0][1]
        assert "resources" in manifest_arg
        assert "gpu_worker" in manifest_arg["resources"]
        assert "cpu_worker" in manifest_arg["resources"]

    @pytest.mark.asyncio
    async def test_no_actions_skips_provisioning_but_still_pushes_manifest(
        self, mock_flash_app, tmp_path
    ):
        """When local and state manifests match (with endpoints), no provisioning occurs
        but manifest is still pushed to State Manager."""
        flash_dir = tmp_path / ".flash"
        flash_dir.mkdir()

        local_manifest = {
            "resources": {
                "worker": {
                    "resource_type": "ServerlessResource",
                    "config": "v1",
                },
            },
        }

        # State manifest has same config AND existing endpoint
        state_manifest = {
            "resources": {
                "worker": {
                    "resource_type": "ServerlessResource",
                    "config": "v1",
                },
            },
            "resources_endpoints": {
                "worker": "https://worker.api.runpod.ai",
            },
        }

        mock_flash_app.get_build_manifest.return_value = state_manifest

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch("runpod_flash.cli.utils.deployment.ResourceManager") as mock_rm_cls,
        ):
            mock_manager = MagicMock()
            mock_manager.get_or_deploy_resource = AsyncMock()
            mock_rm_cls.return_value = mock_manager

            result = await reconcile_and_provision_resources(
                mock_flash_app,
                "build-200",
                "prod",
                local_manifest,
                show_progress=False,
            )

        # No provisioning calls since config and endpoint both match
        mock_manager.get_or_deploy_resource.assert_not_awaited()

        # Endpoint reused from state manifest
        assert result["worker"] == "https://worker.api.runpod.ai"

        # State Manager still receives the updated manifest
        mock_flash_app.update_build_manifest.assert_awaited_once()
        pushed_manifest = mock_flash_app.update_build_manifest.call_args[0][1]
        assert (
            pushed_manifest["resources_endpoints"]["worker"]
            == "https://worker.api.runpod.ai"
        )
