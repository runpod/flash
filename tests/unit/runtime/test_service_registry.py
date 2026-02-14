"""Tests for ServiceRegistry."""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.runtime.service_registry import ServiceRegistry


class TestServiceRegistry:
    """Test ServiceRegistry functionality."""

    @pytest.fixture
    def manifest_dict(self):
        """Sample manifest."""
        return {
            "version": "1.0",
            "project_name": "test_app",
            "function_registry": {
                "gpu_task": "gpu_config",
                "preprocess": "cpu_config",
                "inference": "gpu_config",
            },
            "resources": {
                "gpu_config": {
                    "resource_type": "LiveServerless",
                    "functions": [
                        {"name": "gpu_task", "module": "workers.gpu", "is_async": True},
                        {
                            "name": "inference",
                            "module": "workers.gpu",
                            "is_async": True,
                        },
                    ],
                },
                "cpu_config": {
                    "resource_type": "LiveServerless",
                    "functions": [
                        {
                            "name": "preprocess",
                            "module": "workers.cpu",
                            "is_async": False,
                        },
                    ],
                },
            },
        }

    @pytest.fixture
    def manifest_file(self, manifest_dict):
        """Create temporary manifest file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest_dict, f)
            path = f.name

        yield Path(path)

        # Cleanup
        Path(path).unlink()

    def test_init_with_manifest_path(self, manifest_file):
        """Test initialization with explicit manifest path."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        assert registry.get_manifest().project_name == "test_app"

    def test_init_from_env_manifest_path(self, manifest_file):
        """Test initialization from FLASH_MANIFEST_PATH env var."""
        with patch.dict(os.environ, {"FLASH_MANIFEST_PATH": str(manifest_file)}):
            registry = ServiceRegistry()
            assert registry.get_manifest().project_name == "test_app"

    def test_init_manifest_not_found(self):
        """Test initialization with missing manifest."""
        with patch.dict(os.environ, {}, clear=True):
            registry = ServiceRegistry(manifest_path=Path("/nonexistent/manifest.json"))
            # Should not fail, returns empty manifest
            assert registry.get_manifest().function_registry == {}

    def test_get_current_endpoint_id_with_resource_name(self):
        """Test retrieval using FLASH_RESOURCE_NAME (child endpoint)."""
        with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "gpu_config"}):
            registry = ServiceRegistry(manifest_path=Path("/nonexistent"))
            assert registry.get_current_endpoint_id() == "gpu_config"

    def test_get_current_endpoint_id_fallback_to_runpod_id(self):
        """Test fallback to RUNPOD_ENDPOINT_ID when FLASH_RESOURCE_NAME not set."""
        with patch.dict(
            os.environ, {"RUNPOD_ENDPOINT_ID": "gpu-endpoint-123"}, clear=True
        ):
            registry = ServiceRegistry(manifest_path=Path("/nonexistent"))
            assert registry.get_current_endpoint_id() == "gpu-endpoint-123"

    def test_get_current_endpoint_id_not_set(self):
        """Test when neither env var is set."""
        with patch.dict(os.environ, {}, clear=True):
            registry = ServiceRegistry(manifest_path=Path("/nonexistent"))
            assert registry.get_current_endpoint_id() is None

    @pytest.mark.asyncio
    async def test_is_local_function_local(self, manifest_file):
        """Test determining local function using FLASH_RESOURCE_NAME."""
        with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "gpu_config"}):
            registry = ServiceRegistry(manifest_path=manifest_file)
            assert await registry.is_local_function("gpu_task") is True
            assert await registry.is_local_function("inference") is True

    @pytest.mark.asyncio
    async def test_is_local_function_remote(self, manifest_file):
        """Test determining remote function (with manifest loaded)."""
        with patch.dict(
            os.environ,
            {
                "FLASH_RESOURCE_NAME": "gpu_config",
                "RUNPOD_ENDPOINT_ID": "mothership-id",
                "FLASH_ENVIRONMENT_ID": "env-mothership",
            },
        ):
            registry = ServiceRegistry(manifest_path=manifest_file)

            # Mock the manifest client
            mock_client = AsyncMock()
            mock_client.get_persisted_manifest.return_value = {
                "resources_endpoints": {"cpu_config": "https://cpu.example.com"}
            }
            registry._manifest_client = mock_client

            # After manifest is loaded, CPU tasks should be recognized as remote
            await registry._ensure_manifest_loaded()
            assert await registry.is_local_function("preprocess") is False

    @pytest.mark.asyncio
    async def test_is_local_function_not_in_manifest(self, manifest_file):
        """Test function not in manifest."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        # Unknown function assumed local
        assert await registry.is_local_function("unknown_function") is True

    @pytest.mark.asyncio
    async def test_get_endpoint_for_function_local(self, manifest_file):
        """Test getting endpoint for local function using FLASH_RESOURCE_NAME."""
        with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "gpu_config"}):
            registry = ServiceRegistry(manifest_path=manifest_file)
            endpoint = await registry.get_endpoint_for_function("gpu_task")
            assert endpoint is None  # Local returns None

    @pytest.mark.asyncio
    async def test_get_endpoint_for_function_remote_no_manifest(self, manifest_file):
        """Test getting endpoint for remote function without manifest."""
        with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "gpu_config"}):
            registry = ServiceRegistry(manifest_path=manifest_file)
            # CPU function is remote, but no manifest loaded
            endpoint = await registry.get_endpoint_for_function("preprocess")
            assert endpoint is None

    @pytest.mark.asyncio
    async def test_get_endpoint_for_function_not_in_manifest(self, manifest_file):
        """Test getting endpoint for unknown function."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        with pytest.raises(ValueError, match="not found in manifest"):
            await registry.get_endpoint_for_function("unknown_function")

    @pytest.mark.asyncio
    async def test_get_resource_for_function_local(self, manifest_file):
        """Test getting ServerlessResource for local function using FLASH_RESOURCE_NAME."""
        with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "gpu_config"}):
            registry = ServiceRegistry(manifest_path=manifest_file)
            resource = await registry.get_resource_for_function("gpu_task")
            # Local function returns None
            assert resource is None

    @pytest.mark.asyncio
    async def test_get_resource_for_function_remote(self, manifest_file):
        """Test getting ServerlessResource for remote function."""
        with patch.dict(
            os.environ,
            {
                "FLASH_RESOURCE_NAME": "gpu_config",
                "RUNPOD_ENDPOINT_ID": "mothership-id",
                "FLASH_ENVIRONMENT_ID": "env-mothership",
            },
        ):
            registry = ServiceRegistry(manifest_path=manifest_file)

            # Mock the manifest client
            mock_client = AsyncMock()
            mock_client.get_persisted_manifest.return_value = {
                "resources_endpoints": {"cpu_config": "https://api.runpod.ai/v2/abc123"}
            }
            registry._manifest_client = mock_client

            # Load manifest
            await registry._ensure_manifest_loaded()

            resource = await registry.get_resource_for_function("preprocess")

            # Should return LoadBalancerSlsResource with correct endpoint ID
            assert resource is not None
            assert resource.id == "abc123"
            # Name should be the resource config name from manifest
            assert resource.name == "cpu_config"

    @pytest.mark.asyncio
    async def test_get_resource_for_function_not_in_manifest(self, manifest_file):
        """Test getting resource for unknown function."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        with pytest.raises(ValueError, match="not found in manifest"):
            await registry.get_resource_for_function("unknown_function")

    @pytest.mark.asyncio
    async def test_ensure_manifest_loaded(self, manifest_file):
        """Test lazy loading of manifest from client."""
        mock_endpoint_registry = {
            "gpu_config": "https://gpu.example.com",
            "cpu_config": "https://cpu.example.com",
        }

        with patch.dict(
            os.environ,
            {
                "RUNPOD_ENDPOINT_ID": "mothership-id",
                "FLASH_RESOURCE_NAME": "gpu_config",
                "FLASH_ENVIRONMENT_ID": "env-test",
            },
        ):
            registry = ServiceRegistry(manifest_path=manifest_file, cache_ttl=10)

            # Mock the manifest client
            mock_client = AsyncMock()
            mock_client.get_persisted_manifest.return_value = {
                "resources_endpoints": mock_endpoint_registry
            }
            registry._manifest_client = mock_client

            # Endpoint registry not loaded yet
            assert registry._endpoint_registry == {}

            # Load manifest
            await registry._ensure_manifest_loaded()

            # Should now have loaded endpoint registry
            assert registry._endpoint_registry == mock_endpoint_registry
            mock_client.get_persisted_manifest.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_manifest_cache_respects_ttl(self, manifest_file):
        """Test that manifest cache respects TTL."""
        mock_endpoint_registry = {"gpu_config": "https://gpu.example.com"}

        with patch.dict(
            os.environ,
            {
                "RUNPOD_ENDPOINT_ID": "mothership-id",
                "FLASH_RESOURCE_NAME": "gpu_config",
                "FLASH_ENVIRONMENT_ID": "env-test",
            },
        ):
            registry = ServiceRegistry(manifest_path=manifest_file, cache_ttl=1)

            # Mock the manifest client
            mock_client = AsyncMock()
            mock_client.get_persisted_manifest.return_value = {
                "resources_endpoints": mock_endpoint_registry
            }
            registry._manifest_client = mock_client

            # Load manifest
            await registry._ensure_manifest_loaded()
            assert mock_client.get_persisted_manifest.call_count == 1

            # Immediate reload should use cache
            await registry._ensure_manifest_loaded()
            assert mock_client.get_persisted_manifest.call_count == 1

            # After TTL, should reload
            registry._endpoint_registry_loaded_at = time.time() - 2  # 2 seconds ago
            await registry._ensure_manifest_loaded()
            assert mock_client.get_persisted_manifest.call_count == 2

    @pytest.mark.asyncio
    async def test_refresh_manifest(self, manifest_file):
        """Test forcing manifest refresh."""
        mock_endpoint_registry = {"gpu_config": "https://gpu.example.com"}

        with patch.dict(
            os.environ,
            {
                "RUNPOD_ENDPOINT_ID": "mothership-id",
                "FLASH_RESOURCE_NAME": "gpu_config",
                "FLASH_ENVIRONMENT_ID": "env-test",
            },
        ):
            registry = ServiceRegistry(manifest_path=manifest_file, cache_ttl=3600)

            # Mock the manifest client
            mock_client = AsyncMock()
            mock_client.get_persisted_manifest.return_value = {
                "resources_endpoints": mock_endpoint_registry
            }
            registry._manifest_client = mock_client

            # Load manifest
            await registry._ensure_manifest_loaded()
            assert mock_client.get_persisted_manifest.call_count == 1

            # Force refresh
            registry.refresh_manifest()

            # Next load should fetch again
            await registry._ensure_manifest_loaded()
            assert mock_client.get_persisted_manifest.call_count == 2

    def test_get_manifest(self, manifest_file):
        """Test getting manifest."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        manifest = registry.get_manifest()
        assert manifest.project_name == "test_app"

    def test_get_all_resources(self, manifest_file):
        """Test getting all resources."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        resources = registry.get_all_resources()
        assert "gpu_config" in resources
        assert "cpu_config" in resources

    def test_get_resource_functions(self, manifest_file):
        """Test getting functions for a resource."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        functions = registry.get_resource_functions("gpu_config")
        assert len(functions) == 2
        names = [f["name"] for f in functions]
        assert "gpu_task" in names
        assert "inference" in names

    def test_get_resource_functions_not_found(self, manifest_file):
        """Test getting functions for nonexistent resource."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        functions = registry.get_resource_functions("nonexistent")
        assert functions == []

    def test_init_no_manifest_client_no_runpod_key(self, manifest_file):
        """Test initialization without RUNPOD_API_KEY."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "runpod_flash.runtime.service_registry.StateManagerClient"
            ) as mock_client_class:
                mock_client_class.side_effect = Exception("No API key")
                registry = ServiceRegistry(manifest_path=manifest_file)
                # Should handle the exception and set client to None
                assert registry._manifest_client is None

    @pytest.mark.asyncio
    async def test_ensure_manifest_loaded_unavailable_client(self, manifest_file):
        """Test manifest loading when client is None."""
        registry = ServiceRegistry(manifest_path=manifest_file)
        registry._manifest_client = None
        # Should not fail, just log warning
        await registry._ensure_manifest_loaded()
        assert registry._endpoint_registry == {}

    def test_load_preview_endpoints_from_environment(self, manifest_file):
        """Test loading endpoints from FLASH_RESOURCES_ENDPOINTS env var."""
        preview_endpoints = {
            "gpu_config": "http://flash-preview-gpu_config:80",
            "cpu_config": "http://flash-preview-cpu_config:80",
        }

        with patch.dict(
            os.environ, {"FLASH_RESOURCES_ENDPOINTS": json.dumps(preview_endpoints)}
        ):
            registry = ServiceRegistry(manifest_path=manifest_file)

            # Should have loaded endpoints from environment
            assert registry._endpoint_registry == preview_endpoints

    def test_load_preview_endpoints_invalid_json(self, manifest_file):
        """Test handling of invalid JSON in FLASH_RESOURCES_ENDPOINTS."""
        with patch.dict(os.environ, {"FLASH_RESOURCES_ENDPOINTS": "invalid json{"}):
            registry = ServiceRegistry(manifest_path=manifest_file)

            # Should handle error gracefully and have empty registry
            assert registry._endpoint_registry == {}

    def test_load_preview_endpoints_not_set(self, manifest_file):
        """Test initialization when FLASH_RESOURCES_ENDPOINTS not set."""
        with patch.dict(os.environ, {}, clear=True):
            registry = ServiceRegistry(manifest_path=manifest_file)

            # Should have empty registry (no State Manager, no preview endpoints)
            assert registry._endpoint_registry == {}

    def test_check_makes_remote_calls_true(self):
        """Test _check_makes_remote_calls returns True when makes_remote_calls is True."""
        manifest_dict = {
            "version": "1.0",
            "project_name": "test_app",
            "resources": {
                "mothership": {
                    "resource_type": "CpuLiveLoadBalancer",
                    "makes_remote_calls": True,
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest_dict, f)
            manifest_path = Path(f.name)

        try:
            with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "mothership"}):
                registry = ServiceRegistry(manifest_path=manifest_path)
                assert registry._check_makes_remote_calls("mothership") is True
        finally:
            manifest_path.unlink()

    def test_check_makes_remote_calls_false(self):
        """Test _check_makes_remote_calls returns False when makes_remote_calls is False."""
        manifest_dict = {
            "version": "1.0",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": False,
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest_dict, f)
            manifest_path = Path(f.name)

        try:
            with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "worker"}):
                registry = ServiceRegistry(manifest_path=manifest_path)
                assert registry._check_makes_remote_calls("worker") is False
        finally:
            manifest_path.unlink()

    def test_check_makes_remote_calls_null_returns_true(self):
        """Test _check_makes_remote_calls returns True (safe default) when makes_remote_calls is null."""
        manifest_dict = {
            "version": "1.0",
            "project_name": "test_app",
            "resources": {
                "mothership": {
                    "resource_type": "CpuLiveLoadBalancer",
                    "makes_remote_calls": None,
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest_dict, f)
            manifest_path = Path(f.name)

        try:
            with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "mothership"}):
                registry = ServiceRegistry(manifest_path=manifest_path)
                assert registry._check_makes_remote_calls("mothership") is True
        finally:
            manifest_path.unlink()

    def test_check_makes_remote_calls_missing_resource_returns_true(self):
        """Test _check_makes_remote_calls returns True (safe default) when resource not found."""
        manifest_dict = {
            "version": "1.0",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": False,
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest_dict, f)
            manifest_path = Path(f.name)

        try:
            registry = ServiceRegistry(manifest_path=manifest_path)
            # Check for a resource that doesn't exist
            assert registry._check_makes_remote_calls("nonexistent") is True
        finally:
            manifest_path.unlink()

    def test_check_makes_remote_calls_no_resource_name_returns_true(self):
        """Test _check_makes_remote_calls returns True (safe default) when resource_name is None."""
        manifest_dict = {
            "version": "1.0",
            "project_name": "test_app",
            "resources": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest_dict, f)
            manifest_path = Path(f.name)

        try:
            registry = ServiceRegistry(manifest_path=manifest_path)
            assert registry._check_makes_remote_calls(None) is True
        finally:
            manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_ensure_manifest_loaded_skips_if_no_remote_calls(self):
        """Test that _ensure_manifest_loaded skips State Manager query if makes_remote_calls=False."""
        manifest_dict = {
            "version": "1.0",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": False,
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest_dict, f)
            manifest_path = Path(f.name)

        try:
            with patch.dict(
                os.environ,
                {
                    "FLASH_RESOURCE_NAME": "worker",
                    "RUNPOD_ENDPOINT_ID": "test-endpoint",
                },
                clear=True,
            ):
                registry = ServiceRegistry(manifest_path=manifest_path)

                # Mock the manifest client (should not be called)
                mock_client = AsyncMock()
                registry._manifest_client = mock_client

                # Should skip State Manager query
                await registry._ensure_manifest_loaded()

                # Client should NOT have been called
                mock_client.get_persisted_manifest.assert_not_called()
        finally:
            manifest_path.unlink()
