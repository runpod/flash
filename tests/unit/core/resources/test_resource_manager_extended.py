"""Extended tests for core/resources/resource_manager.py - coverage gaps."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.core.resources.resource_manager import (
    ResourceManager,
)


@pytest.fixture(autouse=True)
def reset_manager(isolate_resource_state_file, reset_singletons):
    """Reset singleton and state file between tests."""
    ResourceManager._resources = {}
    ResourceManager._resource_configs = {}
    ResourceManager._deployment_locks = {}
    ResourceManager._global_lock = None
    ResourceManager._lock_initialized = False
    ResourceManager._resources_initialized = False
    yield
    ResourceManager._resources = {}
    ResourceManager._resource_configs = {}
    ResourceManager._deployment_locks = {}
    ResourceManager._global_lock = None
    ResourceManager._lock_initialized = False
    ResourceManager._resources_initialized = False


class TestLoadResources:
    """Test _load_resources with various data formats."""

    def test_loads_tuple_format(self, tmp_path):
        """Loads new tuple (resources, configs) format."""
        import cloudpickle

        state_file = tmp_path / ".runpod" / "resources.pkl"
        state_file.parent.mkdir(parents=True)

        resources = {"key1": MagicMock(config_hash="hash1")}
        configs = {"key1": "hash1"}
        with open(state_file, "wb") as f:
            cloudpickle.dump((resources, configs), f)

        with patch(
            "runpod_flash.core.resources.resource_manager.RESOURCE_STATE_FILE",
            state_file,
        ):
            manager = ResourceManager()
            assert "key1" in manager._resources

    def test_loads_legacy_dict_format(self, tmp_path):
        """Loads old dict-only format."""
        import cloudpickle

        state_file = tmp_path / ".runpod" / "resources.pkl"
        state_file.parent.mkdir(parents=True)

        resources = {"key1": MagicMock(config_hash="hash1")}
        with open(state_file, "wb") as f:
            cloudpickle.dump(resources, f)

        with patch(
            "runpod_flash.core.resources.resource_manager.RESOURCE_STATE_FILE",
            state_file,
        ):
            manager = ResourceManager()
            assert "key1" in manager._resources
            # After loading legacy format, _refresh_config_hashes updates configs
            # from the resource's config_hash attribute
            assert manager._resource_configs == {"key1": "hash1"}

    def test_handles_file_lock_error(self, tmp_path):
        """Handles FileLockError during load gracefully."""
        state_file = tmp_path / ".runpod" / "resources.pkl"
        state_file.parent.mkdir(parents=True)
        state_file.write_bytes(b"corrupt")

        with patch(
            "runpod_flash.core.resources.resource_manager.RESOURCE_STATE_FILE",
            state_file,
        ):
            manager = ResourceManager()
            # Should not raise, just log error
            assert manager._resources == {}


class TestGetOrDeployResource:
    """Test get_or_deploy_resource method."""

    @pytest.mark.asyncio
    async def test_deploys_new_resource(self):
        """Deploys when no existing resource found."""
        manager = ResourceManager()

        config = MagicMock()
        config.get_resource_key.return_value = "TestResource:my-resource"
        config.config_hash = "hash-new"
        config._do_deploy = AsyncMock(return_value=config)
        config.name = "my-resource"

        with patch.object(manager, "_save_resources"):
            result = await manager.get_or_deploy_resource(config)
            assert result == config

    @pytest.mark.asyncio
    async def test_returns_existing_unchanged(self):
        """Returns existing resource when config hasn't changed."""
        manager = ResourceManager()

        existing = MagicMock()
        existing.is_deployed.return_value = True
        existing.config_hash = "same-hash"

        key = "TestResource:existing"
        manager._resources[key] = existing
        manager._resource_configs[key] = "same-hash"

        config = MagicMock()
        config.get_resource_key.return_value = key
        config.config_hash = "same-hash"

        result = await manager.get_or_deploy_resource(config)
        assert result == existing

    @pytest.mark.asyncio
    async def test_detects_config_drift_and_updates(self):
        """Detects config change and calls update."""
        manager = ResourceManager()

        existing = MagicMock()
        existing.is_deployed.return_value = True
        existing.config_hash = "old-hash"
        existing.update = AsyncMock(return_value=MagicMock(config_hash="new-hash"))

        key = "TestResource:drifted"
        manager._resources[key] = existing
        manager._resource_configs[key] = "old-hash"

        config = MagicMock()
        config.get_resource_key.return_value = key
        config.config_hash = "new-hash"

        with patch.object(manager, "_save_resources"):
            await manager.get_or_deploy_resource(config)
            existing.update.assert_called_once_with(config)

    @pytest.mark.asyncio
    async def test_redeploys_when_invalid(self):
        """Redeploys when existing resource is no longer valid."""
        manager = ResourceManager()

        existing = MagicMock()
        existing.is_deployed.return_value = False

        key = "TestResource:invalid"
        manager._resources[key] = existing
        manager._resource_configs[key] = "hash"

        config = MagicMock()
        config.get_resource_key.return_value = key
        config.config_hash = "hash"
        config._do_deploy = AsyncMock(return_value=config)
        config.name = "invalid"
        config.id = None

        with patch.object(manager, "_save_resources"):
            await manager.get_or_deploy_resource(config)
            config._do_deploy.assert_called_once()

    @pytest.mark.asyncio
    async def test_caches_resource_on_deploy_failure_with_id(self):
        """Caches resource for cleanup if deployment fails but resource was created."""
        manager = ResourceManager()

        config = MagicMock()
        config.get_resource_key.return_value = "TestResource:fail"
        config.config_hash = "hash"
        config._do_deploy = AsyncMock(side_effect=Exception("deploy failed"))
        config.name = "fail"
        config.id = "created-id-123"

        with patch.object(manager, "_save_resources"):
            with pytest.raises(Exception, match="deploy failed"):
                await manager.get_or_deploy_resource(config)

            # Resource should be cached for cleanup
            assert "TestResource:fail" in manager._resources


class TestUndeployResource:
    """Test undeploy_resource method."""

    @pytest.mark.asyncio
    async def test_undeploy_success(self):
        manager = ResourceManager()

        resource = MagicMock()
        resource.name = "test"
        resource.id = "ep-123"
        resource._do_undeploy = AsyncMock(return_value=True)

        manager._resources["key"] = resource
        manager._resource_configs["key"] = "hash"

        with patch.object(manager, "_save_resources"):
            result = await manager.undeploy_resource("key")
            assert result["success"] is True
            assert "key" not in manager._resources

    @pytest.mark.asyncio
    async def test_undeploy_not_found(self):
        manager = ResourceManager()
        result = await manager.undeploy_resource("nonexistent")
        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_undeploy_failure(self):
        manager = ResourceManager()

        resource = MagicMock()
        resource.name = "test"
        resource.id = "ep-123"
        resource._do_undeploy = AsyncMock(return_value=False)

        manager._resources["key"] = resource

        result = await manager.undeploy_resource("key")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_undeploy_force_remove(self):
        """force_remove removes from tracking even on failure."""
        manager = ResourceManager()

        resource = MagicMock()
        resource.name = "test"
        resource.id = "ep-123"
        resource._do_undeploy = AsyncMock(return_value=False)

        manager._resources["key"] = resource
        manager._resource_configs["key"] = "hash"

        with patch.object(manager, "_save_resources"):
            result = await manager.undeploy_resource("key", force_remove=True)
            assert result["success"] is False
            assert "key" not in manager._resources

    @pytest.mark.asyncio
    async def test_undeploy_not_implemented(self):
        manager = ResourceManager()

        resource = MagicMock()
        resource.name = "test"
        resource.id = "ep-123"
        resource._do_undeploy = AsyncMock(
            side_effect=NotImplementedError("unsupported")
        )

        manager._resources["key"] = resource

        result = await manager.undeploy_resource("key")
        assert result["success"] is False
        assert "Cannot undeploy" in result["message"]

    @pytest.mark.asyncio
    async def test_undeploy_unexpected_error_force(self):
        """Unexpected errors with force_remove still removes resource."""
        manager = ResourceManager()

        resource = MagicMock()
        resource.name = "test"
        resource.id = "ep-123"
        resource._do_undeploy = AsyncMock(
            side_effect=Exception("already deleted remotely")
        )

        manager._resources["key"] = resource
        manager._resource_configs["key"] = "hash"

        with patch.object(manager, "_save_resources"):
            result = await manager.undeploy_resource("key", force_remove=True)
            assert result["success"] is False
            assert "key" not in manager._resources


class TestFindResources:
    """Test resource lookup methods."""

    def test_find_by_name(self):
        manager = ResourceManager()
        r1 = MagicMock()
        r1.name = "gpu-worker"
        r2 = MagicMock()
        r2.name = "cpu-worker"
        manager._resources = {"k1": r1, "k2": r2}

        matches = manager.find_resources_by_name("gpu-worker")
        assert len(matches) == 1
        assert matches[0][0] == "k1"

    def test_find_by_provider_id(self):
        manager = ResourceManager()
        r1 = MagicMock(id="ep-123")
        r2 = MagicMock(id="ep-456")
        manager._resources = {"k1": r1, "k2": r2}

        matches = manager.find_resources_by_provider_id("ep-456")
        assert len(matches) == 1
        assert matches[0][0] == "k2"

    def test_find_no_matches(self):
        manager = ResourceManager()
        manager._resources = {}
        assert manager.find_resources_by_name("nonexistent") == []
        assert manager.find_resources_by_provider_id("ep-999") == []
