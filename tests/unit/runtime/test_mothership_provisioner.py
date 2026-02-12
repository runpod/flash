"""Unit tests for mothership provisioner module."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.runtime.mothership_provisioner import (
    compute_resource_hash,
    create_resource_from_manifest,
    load_manifest,
)


class TestLoadManifest:
    """Tests for load_manifest function."""

    def test_load_manifest_from_explicit_path(self):
        """Test loading manifest from explicit path."""
        manifest_data = {"version": "1.0", "resources": {}}

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest_data))

            result = load_manifest(manifest_path)
            assert result == manifest_data

    def test_load_manifest_from_env_var(self):
        """Test loading manifest from environment variable."""
        manifest_data = {"version": "1.0", "resources": {}}

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "flash_manifest.json"
            manifest_path.write_text(json.dumps(manifest_data))

            with patch.dict(os.environ, {"FLASH_MANIFEST_PATH": str(manifest_path)}):
                result = load_manifest()
                assert result == manifest_data

    def test_load_manifest_not_found(self):
        """Test that FileNotFoundError is raised when manifest is not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pathlib.Path.cwd", return_value=Path(tmpdir)):
                with pytest.raises(
                    FileNotFoundError, match="flash_manifest.json not found"
                ):
                    load_manifest()

    def test_load_manifest_invalid_json(self):
        """Test that FileNotFoundError is raised for invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "flash_manifest.json"
            manifest_path.write_text("invalid json {")

            with patch.dict(os.environ, {"FLASH_MANIFEST_PATH": str(manifest_path)}):
                # Should continue searching when JSON is invalid
                with pytest.raises(FileNotFoundError):
                    load_manifest()

    def test_load_manifest_searches_multiple_paths(self):
        """Test that load_manifest searches multiple paths."""
        manifest_data = {"version": "1.0", "resources": {}}

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create manifest in cwd
            manifest_path = Path(tmpdir) / "flash_manifest.json"
            manifest_path.write_text(json.dumps(manifest_data))

            with patch("pathlib.Path.cwd", return_value=Path(tmpdir)):
                result = load_manifest()
                assert result == manifest_data


class TestComputeResourceHash:
    """Tests for compute_resource_hash function."""

    def test_compute_resource_hash_basic(self):
        """Test computing hash for basic resource data."""
        resource_data = {"name": "test", "type": "ServerlessResource"}
        hash_value = compute_resource_hash(resource_data)

        # Verify it's a hex string
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64  # SHA-256 hex is 64 chars
        assert all(c in "0123456789abcdef" for c in hash_value)

    def test_compute_resource_hash_consistent(self):
        """Test that same data produces same hash."""
        resource_data = {"name": "test", "type": "ServerlessResource"}
        hash1 = compute_resource_hash(resource_data)
        hash2 = compute_resource_hash(resource_data)

        assert hash1 == hash2

    def test_compute_resource_hash_different_data(self):
        """Test that different data produces different hashes."""
        data1 = {"name": "test1", "type": "ServerlessResource"}
        data2 = {"name": "test2", "type": "ServerlessResource"}

        hash1 = compute_resource_hash(data1)
        hash2 = compute_resource_hash(data2)

        assert hash1 != hash2

    def test_compute_resource_hash_order_independent(self):
        """Test that key order doesn't affect hash (JSON sorts keys)."""
        data1 = {"name": "test", "type": "ServerlessResource"}
        data2 = {"type": "ServerlessResource", "name": "test"}

        hash1 = compute_resource_hash(data1)
        hash2 = compute_resource_hash(data2)

        # Should be same because json.dumps with sort_keys=True
        assert hash1 == hash2

    def test_compute_resource_hash_nested_data(self):
        """Test computing hash for nested resource data."""
        resource_data = {
            "name": "test",
            "type": "ServerlessResource",
            "config": {
                "imageName": "test:latest",
                "workers": {"min": 1, "max": 5},
            },
        }
        hash_value = compute_resource_hash(resource_data)

        assert isinstance(hash_value, str)
        assert len(hash_value) == 64  # SHA-256 hex is 64 chars


class TestCreateResourceFromManifest:
    """Tests for create_resource_from_manifest function."""

    def test_create_resource_from_manifest_serverless(self):
        """Test creating ServerlessResource from manifest."""
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
        }
        mothership_url = "https://test.api.runpod.ai"

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, mothership_url
            )

            assert isinstance(resource, ServerlessResource)
            # ServerlessResource may append "-fb" suffix during initialization
            assert resource_name in resource.name
            assert resource.env["FLASH_RESOURCE_NAME"] == resource_name

    def test_create_resource_from_manifest_live_serverless(self):
        """Test that LiveServerless type is accepted but creates ServerlessResource.

        Note: Current implementation creates ServerlessResource regardless of type.
        This is a known limitation - manifest needs to include full deployment config
        to properly construct different resource types.
        """
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "resource_type": "LiveServerless",
            "imageName": "runpod/flash:latest",
        }
        mothership_url = "https://test.api.runpod.ai"

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            # Should not raise - LiveServerless is in supported types
            resource = create_resource_from_manifest(
                resource_name, resource_data, mothership_url
            )

            # Returns ServerlessResource (current limitation)
            assert isinstance(resource, ServerlessResource)
            assert resource_name in resource.name

    def test_create_resource_from_manifest_unsupported_type(self):
        """Test that ValueError is raised for unsupported resource types."""
        resource_name = "worker1"
        resource_data = {"resource_type": "UnsupportedResourceType"}
        mothership_url = "https://test.api.runpod.ai"

        with pytest.raises(ValueError, match="Unsupported resource type"):
            create_resource_from_manifest(resource_name, resource_data, mothership_url)

    def test_create_resource_from_manifest_default_type(self):
        """Test that default type is ServerlessResource when not specified."""
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "imageName": "runpod/flash:latest"
        }  # No resource_type specified
        mothership_url = "https://test.api.runpod.ai"

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, mothership_url
            )

            assert isinstance(resource, ServerlessResource)
            assert resource_name in resource.name

    def test_create_resource_from_manifest_cli_context_no_runpod_endpoint_id(self):
        """Test resource creation in CLI context without RUNPOD_ENDPOINT_ID.

        During CLI provisioning, RUNPOD_ENDPOINT_ID is not available.
        FLASH_MOTHERSHIP_ID should not be included in env to avoid
        Pydantic validation errors (None values are not allowed).
        """
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
        }
        mothership_url = ""  # Empty URL indicates CLI context

        # Clear RUNPOD_ENDPOINT_ID to simulate CLI environment
        with patch.dict(os.environ, {}, clear=True):
            resource = create_resource_from_manifest(
                resource_name, resource_data, mothership_url
            )

            assert isinstance(resource, ServerlessResource)
            assert resource_name in resource.name
            # FLASH_MOTHERSHIP_ID should NOT be present when RUNPOD_ENDPOINT_ID is not set
            assert "FLASH_MOTHERSHIP_ID" not in resource.env
            assert resource.env["FLASH_RESOURCE_NAME"] == resource_name

    def test_create_resource_from_manifest_mothership_context_with_endpoint_id(self):
        """Test resource creation in mothership runtime context.

        When running inside a mothership endpoint, RUNPOD_ENDPOINT_ID is available.
        FLASH_MOTHERSHIP_ID should be included in env so children can query
        the State Manager using the mothership's ID.
        """
        from runpod_flash.core.resources.serverless import ServerlessResource

        resource_name = "worker1"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
        }
        mothership_url = "https://mothership.api.runpod.ai"

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-endpoint-456"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, mothership_url
            )

            assert isinstance(resource, ServerlessResource)
            assert resource_name in resource.name
            # FLASH_MOTHERSHIP_ID should be present when RUNPOD_ENDPOINT_ID is set
            assert resource.env["FLASH_MOTHERSHIP_ID"] == "mothership-endpoint-456"
            assert resource.env["FLASH_RESOURCE_NAME"] == resource_name

    def test_create_resource_from_manifest_cpu_live_serverless(self):
        """Test creating CpuLiveServerless from manifest."""
        from runpod_flash.core.resources.live_serverless import CpuLiveServerless

        resource_name = "cpu_worker"
        resource_data = {"resource_type": "CpuLiveServerless"}
        mothership_url = "https://test.api.runpod.ai"

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, mothership_url
            )

            assert isinstance(resource, CpuLiveServerless)
            assert resource_name in resource.name
            assert resource.env["FLASH_MOTHERSHIP_ID"] == "mothership-123"
            assert resource.env["FLASH_RESOURCE_NAME"] == resource_name
