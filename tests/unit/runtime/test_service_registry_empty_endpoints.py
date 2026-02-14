"""Tests for ServiceRegistry empty endpoints fallback behavior.

Tests that when State Manager returns empty resources_endpoints,
ServiceRegistry correctly falls back to local manifest endpoints.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.runtime.service_registry import ServiceRegistry


def create_test_manifest(resources_endpoints=None):
    """Create a test manifest with optional resources_endpoints."""
    manifest_data = {
        "version": "1.0",
        "generated_at": "2026-02-13T00:00:00Z",
        "project_name": "test_project",
        "function_registry": {
            "gpu_info": "test_resource",
        },
        "resources": {
            "test_resource": {
                "resource_type": "serverless",
                "functions": [
                    {
                        "name": "gpu_info",
                        "module": "main",
                        "is_async": False,
                        "is_class": False,
                    }
                ],
                "makes_remote_calls": True,
            }
        },
    }

    if resources_endpoints is not None:
        manifest_data["resources_endpoints"] = resources_endpoints

    return manifest_data


@pytest.fixture
def temp_manifest_with_endpoints():
    """Create a temporary manifest file with populated resources_endpoints."""
    manifest_data = create_test_manifest(
        resources_endpoints={
            "test_resource": "https://local-endpoint.example.com",
            "resource_a": "https://endpoint-a.example.com",
            "resource_b": "https://endpoint-b.example.com",
        }
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(manifest_data, f)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def temp_manifest_without_endpoints():
    """Create a temporary manifest file with empty resources_endpoints."""
    manifest_data = create_test_manifest(resources_endpoints={})

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(manifest_data, f)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    temp_path.unlink(missing_ok=True)


class TestServiceRegistryEmptyEndpoints:
    """Test ServiceRegistry behavior when State Manager returns empty endpoints."""

    @pytest.mark.asyncio
    async def test_state_manager_empty_endpoints_falls_back_to_local_manifest(
        self, temp_manifest_with_endpoints
    ):
        """Test that empty State Manager response falls back to local manifest."""
        # Create registry with manifest that has endpoints
        registry = ServiceRegistry(manifest_path=temp_manifest_with_endpoints)

        # Mock State Manager to return empty resources_endpoints
        registry._manifest_client = AsyncMock()
        registry._manifest_client.get_persisted_manifest = AsyncMock(
            return_value={
                "resources_endpoints": {},  # Empty!
                "other_key": "value",
            }
        )

        # Force cache expiration to trigger refresh
        registry._endpoint_registry_loaded_at = 0

        with patch.dict(
            os.environ,
            {
                "FLASH_ENVIRONMENT_ID": "test-env-id",
                "RUNPOD_API_KEY": "test-key",
            },
        ):
            with patch(
                "runpod_flash.runtime.api_key_context.get_api_key",
                return_value="test-key",
            ):
                # Trigger cache refresh
                await registry._ensure_manifest_loaded()

        # Verify fallback to local manifest
        assert registry._endpoint_registry == {
            "test_resource": "https://local-endpoint.example.com",
            "resource_a": "https://endpoint-a.example.com",
            "resource_b": "https://endpoint-b.example.com",
        }
        assert registry._endpoint_registry_loaded_at > 0

    @pytest.mark.asyncio
    async def test_state_manager_empty_endpoints_no_local_fallback(
        self, temp_manifest_without_endpoints
    ):
        """Test behavior when State Manager returns empty and no local fallback available."""
        # Create registry with manifest that has no endpoints
        registry = ServiceRegistry(manifest_path=temp_manifest_without_endpoints)

        # Mock State Manager to return empty resources_endpoints
        registry._manifest_client = AsyncMock()
        registry._manifest_client.get_persisted_manifest = AsyncMock(
            return_value={
                "resources_endpoints": {},  # Empty!
                "other_key": "value",
            }
        )

        # Force cache expiration to trigger refresh
        registry._endpoint_registry_loaded_at = 0

        with patch.dict(
            os.environ,
            {
                "FLASH_ENVIRONMENT_ID": "test-env-id",
                "RUNPOD_API_KEY": "test-key",
            },
        ):
            with patch(
                "runpod_flash.runtime.api_key_context.get_api_key",
                return_value="test-key",
            ):
                # Trigger cache refresh
                await registry._ensure_manifest_loaded()

        # Verify endpoint registry is empty
        assert registry._endpoint_registry == {}

    @pytest.mark.asyncio
    async def test_state_manager_valid_endpoints_used(
        self, temp_manifest_with_endpoints
    ):
        """Test that valid State Manager response is used (not overridden by local)."""
        # Create registry with manifest that has local endpoints
        registry = ServiceRegistry(manifest_path=temp_manifest_with_endpoints)

        state_manager_endpoints = {
            "resource_c": "https://endpoint-c.example.com",
            "resource_d": "https://endpoint-d.example.com",
        }

        # Mock State Manager to return different endpoints
        registry._manifest_client = AsyncMock()
        registry._manifest_client.get_persisted_manifest = AsyncMock(
            return_value={
                "resources_endpoints": state_manager_endpoints,
                "other_key": "value",
            }
        )

        # Force cache expiration to trigger refresh
        registry._endpoint_registry_loaded_at = 0

        with patch.dict(
            os.environ,
            {
                "FLASH_ENVIRONMENT_ID": "test-env-id",
                "RUNPOD_API_KEY": "test-key",
            },
        ):
            with patch(
                "runpod_flash.runtime.api_key_context.get_api_key",
                return_value="test-key",
            ):
                # Trigger cache refresh
                await registry._ensure_manifest_loaded()

        # Verify State Manager endpoints are used (not local manifest)
        assert registry._endpoint_registry == state_manager_endpoints

    @pytest.mark.asyncio
    async def test_state_manager_exception_uses_local_fallback(
        self, temp_manifest_with_endpoints
    ):
        """Test that State Manager exceptions still use local manifest fallback."""
        from runpod_flash.runtime.service_registry import (
            ManifestServiceUnavailableError,
        )

        # Create registry with manifest that has local endpoints
        registry = ServiceRegistry(manifest_path=temp_manifest_with_endpoints)

        # Mock State Manager to raise exception
        registry._manifest_client = AsyncMock()
        registry._manifest_client.get_persisted_manifest = AsyncMock(
            side_effect=ManifestServiceUnavailableError("Service unavailable")
        )

        # Force cache expiration to trigger refresh
        registry._endpoint_registry_loaded_at = 0

        with patch.dict(
            os.environ,
            {
                "FLASH_ENVIRONMENT_ID": "test-env-id",
                "RUNPOD_API_KEY": "test-key",
            },
        ):
            with patch(
                "runpod_flash.runtime.api_key_context.get_api_key",
                return_value="test-key",
            ):
                # Trigger cache refresh (should not raise)
                await registry._ensure_manifest_loaded()

        # Verify fallback to local manifest on exception
        assert registry._endpoint_registry == {
            "test_resource": "https://local-endpoint.example.com",
            "resource_a": "https://endpoint-a.example.com",
            "resource_b": "https://endpoint-b.example.com",
        }

    @pytest.mark.asyncio
    async def test_cache_not_refreshed_before_ttl_expires(
        self, temp_manifest_with_endpoints
    ):
        """Test that cache is not refreshed before TTL expires."""
        registry = ServiceRegistry(manifest_path=temp_manifest_with_endpoints)

        registry._manifest_client = AsyncMock()
        registry._manifest_client.get_persisted_manifest = AsyncMock()

        with patch.dict(
            os.environ,
            {
                "FLASH_ENVIRONMENT_ID": "test-env-id",
                "RUNPOD_API_KEY": "test-key",
            },
        ):
            with patch(
                "runpod_flash.runtime.api_key_context.get_api_key",
                return_value="test-key",
            ):
                # Set cache as fresh (loaded just now)
                registry._endpoint_registry_loaded_at = time.time()

                # Trigger cache check (should not refresh)
                await registry._ensure_manifest_loaded()

        # Verify manifest client was not called
        registry._manifest_client.get_persisted_manifest.assert_not_called()

    @pytest.mark.asyncio
    async def test_environment_id_not_set(self, temp_manifest_with_endpoints):
        """Test behavior when FLASH_ENVIRONMENT_ID is not set."""
        registry = ServiceRegistry(manifest_path=temp_manifest_with_endpoints)

        registry._manifest_client = AsyncMock()
        registry._manifest_client.get_persisted_manifest = AsyncMock()

        # Force cache expiration
        registry._endpoint_registry_loaded_at = 0

        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "runpod_flash.runtime.api_key_context.get_api_key",
                return_value="test-key",
            ):
                # Trigger cache refresh
                await registry._ensure_manifest_loaded()

        # Verify manifest client was not called (no environment ID)
        registry._manifest_client.get_persisted_manifest.assert_not_called()

    @pytest.mark.asyncio
    async def test_manifest_client_none(self, temp_manifest_with_endpoints):
        """Test behavior when manifest client is None."""
        registry = ServiceRegistry(manifest_path=temp_manifest_with_endpoints)
        registry._manifest_client = None

        # Force cache expiration
        registry._endpoint_registry_loaded_at = 0

        with patch.dict(
            os.environ,
            {
                "FLASH_ENVIRONMENT_ID": "test-env-id",
                "RUNPOD_API_KEY": "test-key",
            },
        ):
            # Trigger cache refresh (should not raise)
            await registry._ensure_manifest_loaded()

        # Verify endpoint registry remains as initialized
        assert registry._endpoint_registry == {}
