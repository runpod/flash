"""Integration tests for State Manager query optimization for local-only endpoints."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.runtime.service_registry import ServiceRegistry
from runpod_flash.runtime.state_manager_client import StateManagerClient


class TestLocalOnlyEndpointOptimization:
    """Integration tests for State Manager query skipping."""

    @pytest.mark.asyncio
    async def test_local_only_endpoint_skips_state_manager(self):
        """Endpoint with makes_remote_calls=False skips State Manager queries."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "function_registry": {"local_task": "local_worker"},
            "resources": {
                "local_worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": False,
                    "functions": [
                        {
                            "name": "local_task",
                            "module": "workers.local",
                            "is_async": True,
                        }
                    ],
                }
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            manifest_path = Path(f.name)

        try:
            with patch.dict("os.environ", {"FLASH_RESOURCE_NAME": "local_worker"}):
                registry = ServiceRegistry(manifest_path=manifest_path)

                # Mock StateManagerClient
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest = AsyncMock()
                registry._manifest_client = mock_state_manager

                # Act
                await registry._ensure_manifest_loaded()

                # Assert State Manager was NOT queried
                mock_state_manager.get_persisted_manifest.assert_not_called()
                assert len(registry._endpoint_registry) == 0

        finally:
            manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_remote_capable_endpoint_queries_state_manager(self):
        """Endpoint with makes_remote_calls=True queries State Manager."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "function_registry": {"remote_task": "remote_worker"},
            "resources": {
                "remote_worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": True,
                    "functions": [
                        {
                            "name": "remote_task",
                            "module": "workers.remote",
                            "is_async": True,
                        }
                    ],
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
                    "FLASH_RESOURCE_NAME": "remote_worker",
                    "RUNPOD_ENDPOINT_ID": "ep-123",
                },
            ):
                registry = ServiceRegistry(manifest_path=manifest_path)

                # Mock StateManagerClient
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest = AsyncMock(
                    return_value={
                        "resources_endpoints": {
                            "remote_worker": "https://remote.example.com",
                            "other_worker": "https://other.example.com",
                        }
                    }
                )
                registry._manifest_client = mock_state_manager

                # Act
                await registry._ensure_manifest_loaded()

                # Assert State Manager was queried
                mock_state_manager.get_persisted_manifest.assert_called_once_with(
                    "ep-123", api_key=None
                )
                assert len(registry._endpoint_registry) == 2
                assert (
                    registry._endpoint_registry["remote_worker"]
                    == "https://remote.example.com"
                )

        finally:
            manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_resource_not_in_manifest_uses_safe_default(self):
        """Resource not found in manifest assumes makes_remote_calls=True."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "function_registry": {"known_task": "known_worker"},
            "resources": {
                "known_worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": False,
                    "functions": [
                        {
                            "name": "known_task",
                            "module": "workers.known",
                            "is_async": True,
                        }
                    ],
                }
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            manifest_path = Path(f.name)

        try:
            # Current endpoint NOT in manifest
            with patch.dict(
                "os.environ",
                {
                    "FLASH_RESOURCE_NAME": "unknown_worker",
                    "RUNPOD_ENDPOINT_ID": "ep-999",
                },
            ):
                registry = ServiceRegistry(manifest_path=manifest_path)

                # Mock StateManagerClient
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest = AsyncMock(
                    return_value={"resources_endpoints": {}}
                )
                registry._manifest_client = mock_state_manager

                # Act
                await registry._ensure_manifest_loaded()

                # Assert safe default: State Manager WAS queried
                mock_state_manager.get_persisted_manifest.assert_called_once()

        finally:
            manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_manifest_not_found_uses_safe_default(self):
        """Missing manifest file assumes makes_remote_calls=True."""
        # No manifest file exists
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "nonexistent.json"

            with patch.dict(
                "os.environ",
                {"FLASH_RESOURCE_NAME": "any_worker", "RUNPOD_ENDPOINT_ID": "ep-555"},
            ):
                # ServiceRegistry handles missing manifest gracefully
                registry = ServiceRegistry(manifest_path=manifest_path)

                # Mock StateManagerClient
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest = AsyncMock(
                    return_value={"resources_endpoints": {}}
                )
                registry._manifest_client = mock_state_manager

                # Act
                await registry._ensure_manifest_loaded()

                # Assert safe default: State Manager WAS queried
                mock_state_manager.get_persisted_manifest.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_ttl_prevents_repeated_queries(self):
        """State Manager queried only after cache TTL expires."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "function_registry": {"cached_task": "cached_worker"},
            "resources": {
                "cached_worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": True,
                    "functions": [
                        {
                            "name": "cached_task",
                            "module": "workers.cached",
                            "is_async": True,
                        }
                    ],
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
                    "FLASH_RESOURCE_NAME": "cached_worker",
                    "RUNPOD_ENDPOINT_ID": "ep-cache",
                },
            ):
                # Short cache TTL for testing
                registry = ServiceRegistry(manifest_path=manifest_path, cache_ttl=2)

                # Mock StateManagerClient
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest = AsyncMock(
                    return_value={
                        "resources_endpoints": {
                            "cached_worker": "https://cache.example.com"
                        }
                    }
                )
                registry._manifest_client = mock_state_manager

                # First call - cache miss
                await registry._ensure_manifest_loaded()
                assert mock_state_manager.get_persisted_manifest.call_count == 1

                # Second call immediately - cache hit
                await registry._ensure_manifest_loaded()
                assert mock_state_manager.get_persisted_manifest.call_count == 1

                # Wait for TTL to expire
                time.sleep(2.1)

                # Third call - cache expired
                await registry._ensure_manifest_loaded()
                assert mock_state_manager.get_persisted_manifest.call_count == 2

        finally:
            manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_multiple_routing_calls_with_local_only(self):
        """Multiple routing calls don't trigger State Manager for local-only endpoint."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "function_registry": {
                "task1": "local_multi",
                "task2": "local_multi",
                "task3": "local_multi",
            },
            "resources": {
                "local_multi": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": False,
                    "functions": [
                        {"name": "task1", "module": "workers.multi", "is_async": True},
                        {"name": "task2", "module": "workers.multi", "is_async": True},
                        {"name": "task3", "module": "workers.multi", "is_async": True},
                    ],
                }
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            manifest_path = Path(f.name)

        try:
            with patch.dict("os.environ", {"FLASH_RESOURCE_NAME": "local_multi"}):
                registry = ServiceRegistry(manifest_path=manifest_path)

                # Mock StateManagerClient
                mock_state_manager = AsyncMock(spec=StateManagerClient)
                mock_state_manager.get_persisted_manifest = AsyncMock()
                registry._manifest_client = mock_state_manager

                # Multiple routing decisions
                await registry.get_endpoint_for_function("task1")
                await registry.get_endpoint_for_function("task2")
                await registry.get_endpoint_for_function("task3")

                # Assert State Manager never queried
                mock_state_manager.get_persisted_manifest.assert_not_called()

                # Assert registry stays empty
                assert len(registry._endpoint_registry) == 0

        finally:
            manifest_path.unlink()
