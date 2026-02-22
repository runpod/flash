"""Integration tests for cross-endpoint routing."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.runtime.production_wrapper import (
    ProductionWrapper,
    create_production_wrapper,
    reset_wrapper,
)
from runpod_flash.runtime.service_registry import ServiceRegistry
from runpod_flash.runtime.state_manager_client import StateManagerClient


class TestCrossEndpointRoutingIntegration:
    """Integration tests for full cross-endpoint routing flow."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up wrapper singleton between tests."""
        yield
        reset_wrapper()

    @pytest.fixture
    def manifest(self):
        """Sample manifest with multiple endpoints."""
        return {
            "version": "1.0",
            "project_name": "integration_test",
            "function_registry": {
                "gpu_task": "gpu_config",
                "cpu_task": "cpu_config",
                "preprocess": "cpu_config",
            },
            "resources": {
                "gpu_config": {
                    "resource_type": "LiveServerless",
                    "functions": [
                        {"name": "gpu_task", "module": "workers.gpu", "is_async": True}
                    ],
                },
                "cpu_config": {
                    "resource_type": "LiveServerless",
                    "functions": [
                        {
                            "name": "cpu_task",
                            "module": "workers.cpu",
                            "is_async": False,
                        },
                        {
                            "name": "preprocess",
                            "module": "workers.cpu",
                            "is_async": False,
                        },
                    ],
                },
            },
        }

    @pytest.mark.asyncio
    async def test_local_function_execution(self, manifest):
        """Test that local function executes without remote call."""
        # Current endpoint is GPU
        with patch.dict(
            "os.environ",
            {
                "FLASH_RESOURCE_NAME": "gpu_config",
            },
        ):
            endpoint_registry = {
                "gpu_config": "https://gpu.example.com",
                "cpu_config": "https://cpu.example.com",
            }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(manifest, f)
                manifest_path = Path(f.name)

            try:
                registry = ServiceRegistry(manifest_path=manifest_path)

                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest.return_value = {
                    "resources_endpoints": endpoint_registry
                }

                registry._manifest_client = mock_state_manager
                registry._endpoint_registry = endpoint_registry
                registry._endpoint_registry_loaded_at = float("inf")

                wrapper = ProductionWrapper(registry)

                async def gpu_task(x):
                    return x * 2

                original_stub = AsyncMock()
                original_stub.return_value = 42

                await wrapper.wrap_function_execution(
                    original_stub,
                    gpu_task,
                    None,
                    None,
                    True,
                    5,
                )

                original_stub.assert_called_once()

            finally:
                manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_remote_function_execution_routing(self, manifest):
        """Test that remote function is routed via ServerlessResource."""
        # Current endpoint is GPU, calling CPU function
        with patch.dict(
            "os.environ",
            {
                "FLASH_RESOURCE_NAME": "gpu_config",
            },
        ):
            endpoint_registry = {
                "gpu_config": "https://gpu.example.com",
                "cpu_config": "https://cpu.example.com",
            }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(manifest, f)
                manifest_path = Path(f.name)

            try:
                registry = ServiceRegistry(manifest_path=manifest_path)
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest.return_value = {
                    "resources_endpoints": endpoint_registry
                }
                registry._manifest_client = mock_state_manager
                registry._endpoint_registry = endpoint_registry
                registry._endpoint_registry_loaded_at = float("inf")

                # Mock ServerlessResource
                mock_resource = AsyncMock()
                mock_resource.runsync = AsyncMock()
                mock_resource.runsync.return_value = MagicMock(
                    error="", output="processed"
                )

                wrapper = ProductionWrapper(registry)

                # Mock get_resource_for_function to return our mock resource
                with patch.object(
                    registry, "get_resource_for_function", return_value=mock_resource
                ):

                    async def cpu_task(x):
                        return x * 3

                    original_stub = AsyncMock()

                    result = await wrapper.wrap_function_execution(
                        original_stub,
                        cpu_task,
                        None,
                        None,
                        True,
                        10,
                    )

                    original_stub.assert_not_called()
                    mock_resource.runsync.assert_called_once()
                    assert result == "processed"

            finally:
                manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_manifest_loading_on_demand(self, manifest):
        """Test that manifest is loaded on-demand before routing decision."""
        with patch.dict(
            "os.environ",
            {
                "FLASH_RESOURCE_NAME": "gpu_config",
                "RUNPOD_ENDPOINT_ID": "endpoint-env-id",
            },
        ):
            endpoint_registry = {
                "gpu_config": "https://gpu.example.com",
                "cpu_config": "https://cpu.example.com",
            }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(manifest, f)
                manifest_path = Path(f.name)

            try:
                registry = ServiceRegistry(manifest_path=manifest_path)
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest.return_value = {
                    "resources_endpoints": endpoint_registry
                }
                registry._manifest_client = mock_state_manager

                assert registry._endpoint_registry == {}

                wrapper = ProductionWrapper(registry)

                async def cpu_task(x):
                    return x

                original_stub = AsyncMock()

                # Mock get_resource_for_function to return a mock resource
                mock_resource = AsyncMock()
                mock_resource.runsync = AsyncMock()
                mock_resource.runsync.return_value = MagicMock(error="", output=None)

                with patch.object(
                    registry, "get_resource_for_function", return_value=mock_resource
                ):
                    await wrapper.wrap_function_execution(
                        original_stub, cpu_task, None, None, True
                    )

                assert len(registry._endpoint_registry) > 0
                assert (
                    registry._endpoint_registry["gpu_config"]
                    == "https://gpu.example.com"
                )

            finally:
                manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_error_handling_in_remote_execution(self, manifest):
        """Test that errors from remote execution are properly propagated."""
        with patch.dict(
            "os.environ",
            {
                "FLASH_RESOURCE_NAME": "gpu_config",
            },
        ):
            endpoint_registry = {
                "gpu_config": "https://gpu.example.com",
                "cpu_config": "https://cpu.example.com",
            }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(manifest, f)
                manifest_path = Path(f.name)

            try:
                registry = ServiceRegistry(manifest_path=manifest_path)
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest.return_value = {
                    "resources_endpoints": endpoint_registry
                }
                registry._manifest_client = mock_state_manager
                registry._endpoint_registry = endpoint_registry
                registry._endpoint_registry_loaded_at = float("inf")

                # Mock ServerlessResource that returns error
                mock_resource = AsyncMock()
                mock_resource.runsync = AsyncMock()
                mock_resource.runsync.return_value = MagicMock(
                    success=False, error="Remote function failed: ValueError"
                )

                wrapper = ProductionWrapper(registry)

                with patch.object(
                    registry, "get_resource_for_function", return_value=mock_resource
                ):

                    async def cpu_task():
                        pass

                    original_stub = AsyncMock()

                    with pytest.raises(Exception, match="Remote execution.*failed"):
                        await wrapper.wrap_function_execution(
                            original_stub, cpu_task, None, None, True
                        )

            finally:
                manifest_path.unlink()

    def test_factory_creates_complete_system(self):
        """Test that factory creates fully integrated system."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "function_registry": {"task": "resource1"},
            "resources": {
                "resource1": {
                    "functions": [{"name": "task", "module": "m", "is_async": True}]
                }
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            manifest_path = Path(f.name)

        try:
            with patch.dict(
                "os.environ",
                {
                    "RUNPOD_ENDPOINT_ID": "resource1",
                },
            ):
                wrapper = create_production_wrapper()

                assert wrapper.service_registry is not None
                assert isinstance(wrapper.service_registry, ServiceRegistry)

        finally:
            manifest_path.unlink()
            reset_wrapper()
