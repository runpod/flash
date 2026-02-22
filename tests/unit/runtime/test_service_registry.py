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
                "RUNPOD_ENDPOINT_ID": "endpoint-env-id",
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
                "RUNPOD_ENDPOINT_ID": "endpoint-env-id",
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

            # Should return ServerlessResource
            assert resource is not None
            assert resource.id == "abc123"
            # Name starts with remote_preprocess (may have random suffix appended)
            assert resource.name.startswith("remote_preprocess")

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

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-env-id"}):
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

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-env-id"}):
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

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "endpoint-env-id"}):
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


class TestGetRoutingInfo:
    """Tests for ServiceRegistry.get_routing_info()."""

    @pytest.fixture
    def qb_manifest_dict(self):
        """Manifest with QB-only resources."""
        return {
            "version": "1.0",
            "project_name": "test_app",
            "function_registry": {
                "gpu_task": "gpu_config",
                "preprocess": "cpu_config",
            },
            "resources": {
                "gpu_config": {
                    "resource_type": "Serverless",
                    "is_load_balanced": False,
                    "functions": [
                        {"name": "gpu_task", "module": "workers.gpu", "is_async": True},
                    ],
                },
                "cpu_config": {
                    "resource_type": "Serverless",
                    "is_load_balanced": False,
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
    def lb_manifest_dict(self):
        """Manifest with a load-balanced resource."""
        return {
            "version": "1.0",
            "project_name": "test_app",
            "function_registry": {
                "gpu_task": "gpu_config",
                "api_handler": "lb_config",
            },
            "resources": {
                "gpu_config": {
                    "resource_type": "Serverless",
                    "is_load_balanced": False,
                    "functions": [
                        {"name": "gpu_task", "module": "workers.gpu", "is_async": True},
                    ],
                },
                "lb_config": {
                    "resource_type": "LoadBalancerSlsResource",
                    "is_load_balanced": True,
                    "functions": [
                        {
                            "name": "api_handler",
                            "module": "workers.api",
                            "is_async": True,
                            "http_method": "POST",
                            "http_path": "/api/process",
                        },
                    ],
                },
            },
        }

    @pytest.fixture
    def qb_manifest_file(self, qb_manifest_dict):
        """Create temporary QB manifest file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(qb_manifest_dict, f)
            path = f.name
        yield Path(path)
        Path(path).unlink()

    @pytest.fixture
    def lb_manifest_file(self, lb_manifest_dict):
        """Create temporary LB manifest file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(lb_manifest_dict, f)
            path = f.name
        yield Path(path)
        Path(path).unlink()

    @pytest.mark.asyncio
    async def test_local_function_returns_none(self, qb_manifest_file):
        """get_routing_info returns None for local functions."""
        with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "gpu_config"}):
            registry = ServiceRegistry(manifest_path=qb_manifest_file)
            result = await registry.get_routing_info("gpu_task")
            assert result is None

    @pytest.mark.asyncio
    async def test_remote_qb_function(self, qb_manifest_file):
        """get_routing_info returns QB routing metadata for remote function."""
        with patch.dict(
            os.environ,
            {"FLASH_RESOURCE_NAME": "gpu_config", "RUNPOD_ENDPOINT_ID": "ep-123"},
        ):
            registry = ServiceRegistry(manifest_path=qb_manifest_file)

            mock_client = AsyncMock()
            mock_client.get_persisted_manifest.return_value = {
                "resources_endpoints": {
                    "cpu_config": "https://api.runpod.ai/v2/cpu-ep-456"
                }
            }
            registry._manifest_client = mock_client

            result = await registry.get_routing_info("preprocess")

        assert result is not None
        assert result["resource_name"] == "cpu_config"
        assert result["endpoint_url"] == "https://api.runpod.ai/v2/cpu-ep-456"
        assert result["is_load_balanced"] is False
        assert result["http_method"] is None
        assert result["http_path"] is None

    @pytest.mark.asyncio
    async def test_remote_lb_function(self, lb_manifest_file):
        """get_routing_info returns LB routing metadata with http_method and http_path."""
        with patch.dict(
            os.environ,
            {"FLASH_RESOURCE_NAME": "gpu_config", "RUNPOD_ENDPOINT_ID": "ep-123"},
        ):
            registry = ServiceRegistry(manifest_path=lb_manifest_file)

            mock_client = AsyncMock()
            mock_client.get_persisted_manifest.return_value = {
                "resources_endpoints": {"lb_config": "https://lb.example.com"}
            }
            registry._manifest_client = mock_client

            result = await registry.get_routing_info("api_handler")

        assert result is not None
        assert result["resource_name"] == "lb_config"
        assert result["endpoint_url"] == "https://lb.example.com"
        assert result["is_load_balanced"] is True
        assert result["http_method"] == "POST"
        assert result["http_path"] == "/api/process"

    @pytest.mark.asyncio
    async def test_unknown_function_raises(self, qb_manifest_file):
        """get_routing_info raises ValueError for unknown function."""
        registry = ServiceRegistry(manifest_path=qb_manifest_file)
        with pytest.raises(ValueError, match="not found in manifest"):
            await registry.get_routing_info("nonexistent_func")

    @pytest.mark.asyncio
    async def test_remote_function_no_endpoint_url(self, qb_manifest_file):
        """get_routing_info returns None endpoint_url when registry has no URL."""
        with patch.dict(os.environ, {"FLASH_RESOURCE_NAME": "gpu_config"}):
            registry = ServiceRegistry(manifest_path=qb_manifest_file)

            result = await registry.get_routing_info("preprocess")

        assert result is not None
        assert result["resource_name"] == "cpu_config"
        assert result["endpoint_url"] is None
