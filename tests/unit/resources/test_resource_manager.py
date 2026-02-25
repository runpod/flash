"""Unit tests for ResourceManager."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.core.utils.singleton import SingletonMixin
from runpod_flash.core.resources.serverless import ServerlessResource
from runpod_flash.core.exceptions import RunpodAPIKeyError


class TestResourceManager:
    """Test ResourceManager functionality."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton state before each test."""
        ResourceManager._resources = {}
        ResourceManager._deployment_locks = {}
        ResourceManager._resources_initialized = False
        ResourceManager._lock_initialized = False
        SingletonMixin._instances.pop(ResourceManager, None)
        yield
        # Cleanup after test
        ResourceManager._resources = {}
        ResourceManager._deployment_locks = {}
        ResourceManager._resources_initialized = False
        ResourceManager._lock_initialized = False
        SingletonMixin._instances.pop(ResourceManager, None)

    @pytest.fixture
    def mock_resource_file(self, tmp_path):
        """Mock the resource state file path."""
        resource_file = tmp_path / ".flash" / "resources.pkl"
        with patch(
            "runpod_flash.core.resources.resource_manager.RESOURCE_STATE_FILE",
            resource_file,
        ):
            yield resource_file

    @pytest.fixture
    def sample_resources(self):
        """Create sample resources for testing."""
        resource1 = ServerlessResource(
            name="test-api-1",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,  # Disable to keep original name
        )
        resource1.id = "endpoint-id-1"

        resource2 = ServerlessResource(
            name="test-api-2",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,  # Disable to keep original name
        )
        resource2.id = "endpoint-id-2"

        resource3 = ServerlessResource(
            name="test-api-1",  # Same name as resource1
            gpuCount=2,  # Different config
            workersMax=5,
            workersMin=1,
            flashboot=False,  # Disable to keep original name
        )
        resource3.id = "endpoint-id-3"

        return {
            resource1.resource_id: resource1,
            resource2.resource_id: resource2,
            resource3.resource_id: resource3,
        }

    def test_list_all_resources_empty(self, mock_resource_file):
        """Test list_all_resources returns empty dict when no resources."""
        manager = ResourceManager()
        resources = manager.list_all_resources()

        assert resources == {}
        assert isinstance(resources, dict)

    def test_list_all_resources_with_data(self, mock_resource_file, sample_resources):
        """Test list_all_resources returns all tracked resources."""
        manager = ResourceManager()

        # Add resources
        for uid, resource in sample_resources.items():
            manager._resources[uid] = resource

        resources = manager.list_all_resources()

        assert len(resources) == 3
        assert set(resources.keys()) == set(sample_resources.keys())
        # Ensure it's a copy, not the original
        assert resources is not manager._resources

    def test_list_all_resources_returns_copy(
        self, mock_resource_file, sample_resources
    ):
        """Test that list_all_resources returns a copy, not reference."""
        manager = ResourceManager()
        manager._resources = sample_resources.copy()

        resources = manager.list_all_resources()
        resources.clear()

        # Original should still have data
        assert len(manager._resources) == 3

    def test_find_resources_by_name_no_matches(
        self, mock_resource_file, sample_resources
    ):
        """Test find_resources_by_name returns empty list when no matches."""
        manager = ResourceManager()
        manager._resources = sample_resources.copy()

        matches = manager.find_resources_by_name("nonexistent-name")

        assert matches == []
        assert isinstance(matches, list)

    def test_find_resources_by_name_single_match(
        self, mock_resource_file, sample_resources
    ):
        """Test find_resources_by_name returns single match."""
        manager = ResourceManager()
        manager._resources = sample_resources.copy()

        matches = manager.find_resources_by_name("test-api-2")

        assert len(matches) == 1
        uid, resource = matches[0]
        assert resource.name == "test-api-2"
        assert resource.id == "endpoint-id-2"

    def test_find_resources_by_name_multiple_matches(
        self, mock_resource_file, sample_resources
    ):
        """Test find_resources_by_name returns multiple matches with same name."""
        manager = ResourceManager()
        manager._resources = sample_resources.copy()

        matches = manager.find_resources_by_name("test-api-1")

        assert len(matches) == 2
        names = [resource.name for _, resource in matches]
        assert all(name == "test-api-1" for name in names)

        # Check that both resources are different (different configs)
        ids = [resource.id for _, resource in matches]
        assert "endpoint-id-1" in ids
        assert "endpoint-id-3" in ids

    def test_find_resources_by_name_exact_match_only(
        self, mock_resource_file, sample_resources
    ):
        """Test find_resources_by_name does exact match, not partial."""
        manager = ResourceManager()
        manager._resources = sample_resources.copy()

        # Should not match "test-api-1" or "test-api-2"
        matches = manager.find_resources_by_name("test-api")

        assert matches == []

    def test_find_resources_by_name_without_name_attribute(self, mock_resource_file):
        """Test find_resources_by_name handles resources without name attribute."""
        manager = ResourceManager()

        # Create a mock resource without name attribute
        mock_resource = MagicMock(spec=[])  # No attributes
        manager._resources = {"uid-1": mock_resource}

        matches = manager.find_resources_by_name("any-name")

        assert matches == []

    def test_add_and_find_resource(self, mock_resource_file):
        """Test adding a resource and finding it by name."""
        manager = ResourceManager()

        resource = ServerlessResource(
            name="my-endpoint",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,  # Disable to keep original name
        )
        resource.id = "test-endpoint-id"

        with patch.object(manager, "_save_resources"):
            manager._add_resource(resource.resource_id, resource)

        # Find by name
        matches = manager.find_resources_by_name("my-endpoint")
        assert len(matches) == 1
        assert matches[0][1].name == "my-endpoint"
        assert matches[0][1].id == "test-endpoint-id"

    def test_remove_resource_updates_find_results(
        self, mock_resource_file, sample_resources
    ):
        """Test that removing a resource updates find_resources_by_name results."""
        manager = ResourceManager()
        manager._resources = sample_resources.copy()

        # Initially 2 matches for "test-api-1"
        matches = manager.find_resources_by_name("test-api-1")
        assert len(matches) == 2

        # Remove one
        uid_to_remove = matches[0][0]
        with patch.object(manager, "_save_resources"):
            manager._remove_resource(uid_to_remove)

        # Now should be 1 match
        matches_after = manager.find_resources_by_name("test-api-1")
        assert len(matches_after) == 1

    def test_list_all_resources_integration_with_add_remove(self, mock_resource_file):
        """Test list_all_resources works correctly with add and remove operations."""
        manager = ResourceManager()
        # Force clean state for this test
        manager._resources = {}

        # Initially empty
        assert len(manager.list_all_resources()) == 0

        # Add resource
        resource = ServerlessResource(
            name="test",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,  # Disable to keep original name
        )

        with patch.object(manager, "_save_resources"):
            manager._add_resource(resource.resource_id, resource)

        # Should have 1 resource
        assert len(manager.list_all_resources()) == 1

        # Remove resource
        with patch.object(manager, "_save_resources"):
            manager._remove_resource(resource.resource_id)

        # Should be empty again
        assert len(manager.list_all_resources()) == 0

    @pytest.mark.asyncio
    async def test_get_or_deploy_resource_calls_do_deploy_once(
        self, mock_resource_file
    ):
        """Ensure get_or_deploy_resource triggers _do_deploy exactly once."""
        manager = ResourceManager()
        resource = ServerlessResource(name="rm-test", flashboot=False)
        resource.id = "endpoint-rm-test"

        with patch.object(ServerlessResource, "is_deployed", return_value=False):
            with patch.object(
                ServerlessResource, "_do_deploy", new=AsyncMock(return_value=resource)
            ) as mock_do_deploy:
                with patch.object(manager, "_add_resource") as mock_add:
                    result = await manager.get_or_deploy_resource(resource)

        mock_do_deploy.assert_awaited_once()
        # Use get_resource_key() to get the name-based key format
        mock_add.assert_called_once_with(resource.get_resource_key(), resource)
        assert result is resource

    @pytest.mark.asyncio
    async def test_deploy_with_error_context_adds_resource_name(
        self, mock_resource_file
    ):
        """RunpodAPIKeyError should mention the resource name for context."""
        manager = ResourceManager()
        resource = ServerlessResource(name="error-test", flashboot=False)

        with patch.object(
            ServerlessResource,
            "_do_deploy",
            new=AsyncMock(side_effect=RunpodAPIKeyError("missing key")),
        ):
            with pytest.raises(RunpodAPIKeyError) as excinfo:
                await manager._deploy_with_error_context(resource)

        assert "error-test" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_get_or_deploy_resource_updates_on_config_drift(
        self, mock_resource_file
    ):
        """Config drift should trigger in-place update, not redeploy."""
        manager = ResourceManager()

        existing = ServerlessResource(
            name="drift-endpoint",
            flashboot=False,
            env={"VERSION": "v1"},
        )
        existing.id = "endpoint-existing"

        new_config = ServerlessResource(
            name="drift-endpoint",
            flashboot=False,
            env={"VERSION": "v2"},
        )

        resource_key = new_config.get_resource_key()
        manager._resources[resource_key] = existing
        manager._resource_configs[resource_key] = existing.config_hash

        updated = ServerlessResource(
            name="drift-endpoint",
            flashboot=False,
            env={"VERSION": "v2"},
        )
        updated.id = "endpoint-existing"

        with patch.object(ServerlessResource, "is_deployed", return_value=True):
            with patch.object(
                ServerlessResource, "update", new=AsyncMock(return_value=updated)
            ) as mock_update:
                with patch.object(
                    ServerlessResource,
                    "_do_deploy",
                    new=AsyncMock(),
                ) as mock_do_deploy:
                    with patch.object(manager, "_add_resource") as mock_add:
                        result = await manager.get_or_deploy_resource(new_config)

        mock_update.assert_awaited_once_with(new_config)
        mock_do_deploy.assert_not_awaited()
        mock_add.assert_called_once_with(resource_key, updated)
        assert result is updated


class TestConfigHashStability:
    """Test that config_hash is stable and excludes dynamic fields like env."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton state before each test."""
        ResourceManager._resources = {}
        ResourceManager._deployment_locks = {}
        ResourceManager._resources_initialized = False
        ResourceManager._lock_initialized = False
        yield
        ResourceManager._resources = {}
        ResourceManager._deployment_locks = {}
        ResourceManager._resources_initialized = False
        ResourceManager._lock_initialized = False

    def test_config_hash_stable_across_instances(self):
        """Test that config_hash is identical for two instances with same config."""
        config1 = ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,
        )

        config2 = ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,
        )

        # Hashes should be identical despite being different instances
        assert config1.config_hash == config2.config_hash

    def test_config_hash_detects_env_from_drift(self):
        """Test that env field changes trigger drift detection.

        Environment variable changes now trigger drift detection so that
        endpoints can be updated with new environment configurations.
        """
        config1 = ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,
        )

        # Simulate API response with different env
        config2 = ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,
            env={"CUSTOM_VAR": "custom_value"},  # Different env
        )

        # Config hashes should be different (env included in hash)
        assert config1.config_hash != config2.config_hash

    def test_config_hash_includes_structural_changes(self):
        """Test that config_hash detects actual structural changes.

        Tests changes to fields in _input_only set (the fields used for config hashing).
        Changes to other fields (like workersMax) don't affect the hash since they're
        API-managed.
        """
        config1 = ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,
        )

        config2 = ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=True,  # Different flashboot (in _input_only)
        )

        # Hashes should be different (flashboot changed)
        assert config1.config_hash != config2.config_hash

    def test_config_hash_with_different_image(self):
        """Test that different images produce different hashes."""
        config1 = ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            imageName="image1:latest",
            flashboot=False,
        )

        config2 = ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            imageName="image2:latest",
            flashboot=False,
        )

        # Hashes should be different (different image)
        assert config1.config_hash != config2.config_hash


class TestCpuEndpointConfigHash:
    """Test config_hash for CPU endpoints excludes env."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton state before each test."""
        ResourceManager._resources = {}
        ResourceManager._deployment_locks = {}
        ResourceManager._resources_initialized = False
        ResourceManager._lock_initialized = False
        yield
        ResourceManager._resources = {}
        ResourceManager._deployment_locks = {}
        ResourceManager._resources_initialized = False
        ResourceManager._lock_initialized = False

    def test_cpu_config_hash_excludes_env(self):
        """Test that CPU endpoint config_hash excludes env to prevent drift."""
        from runpod_flash.core.resources.serverless_cpu import CpuServerlessEndpoint

        config1 = CpuServerlessEndpoint(
            name="test-cpu",
            workersMax=3,
            workersMin=0,
            flashboot=False,
            imageName="runpod/flash-cpu:latest",
        )

        config2 = CpuServerlessEndpoint(
            name="test-cpu",
            workersMax=3,
            workersMin=0,
            flashboot=False,
            imageName="runpod/flash-cpu:latest",
            env={"DIFFERENT_ENV": "value"},
        )

        # Hashes should be the same (env excluded from CPU hash too)
        assert config1.config_hash == config2.config_hash
