"""Unit tests for mothership provisioner module."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.runtime.mothership_provisioner import (
    ManifestDiff,
    compute_resource_hash,
    create_resource_from_manifest,
    get_mothership_url,
    is_mothership,
    load_manifest,
    reconcile_manifests,
)


class TestGetMothershipUrl:
    """Tests for get_mothership_url function."""

    def test_get_mothership_url_from_env_var(self):
        """Test constructing mothership URL from RUNPOD_ENDPOINT_ID."""
        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "test-endpoint-123"}):
            url = get_mothership_url()
            assert url == "https://test-endpoint-123.api.runpod.ai"

    def test_get_mothership_url_missing_env_var(self):
        """Test that RuntimeError is raised when RUNPOD_ENDPOINT_ID is not set."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="RUNPOD_ENDPOINT_ID"):
                get_mothership_url()

    def test_get_mothership_url_with_empty_env_var(self):
        """Test that RuntimeError is raised when RUNPOD_ENDPOINT_ID is empty."""
        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": ""}):
            with pytest.raises(RuntimeError, match="RUNPOD_ENDPOINT_ID"):
                get_mothership_url()


class TestIsMothership:
    """Tests for is_mothership function."""

    def test_is_mothership_true(self):
        """Test that is_mothership returns True when env var is 'true'."""
        with patch.dict(os.environ, {"FLASH_IS_MOTHERSHIP": "true"}):
            assert is_mothership() is True

    def test_is_mothership_true_uppercase(self):
        """Test that is_mothership returns True for 'TRUE'."""
        with patch.dict(os.environ, {"FLASH_IS_MOTHERSHIP": "TRUE"}):
            assert is_mothership() is True

    def test_is_mothership_true_mixed_case(self):
        """Test that is_mothership returns True for 'True'."""
        with patch.dict(os.environ, {"FLASH_IS_MOTHERSHIP": "True"}):
            assert is_mothership() is True

    def test_is_mothership_false(self):
        """Test that is_mothership returns False when env var is 'false'."""
        with patch.dict(os.environ, {"FLASH_IS_MOTHERSHIP": "false"}):
            assert is_mothership() is False

    def test_is_mothership_missing_env_var(self):
        """Test that is_mothership returns False when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_mothership() is False

    def test_is_mothership_empty_string(self):
        """Test that is_mothership returns False for empty string."""
        with patch.dict(os.environ, {"FLASH_IS_MOTHERSHIP": ""}):
            assert is_mothership() is False

    def test_is_mothership_invalid_value(self):
        """Test that is_mothership returns False for invalid values."""
        with patch.dict(os.environ, {"FLASH_IS_MOTHERSHIP": "yes"}):
            assert is_mothership() is False


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


class TestReconcileManifests:
    """Tests for reconcile_manifests function."""

    def test_reconcile_manifests_empty_both(self):
        """Test reconciliation with empty manifests."""
        local = {"resources": {}}
        persisted = {"resources": {}}

        result = reconcile_manifests(local, persisted)

        assert isinstance(result, ManifestDiff)
        assert result.new == []
        assert result.changed == []
        assert result.removed == []
        assert result.unchanged == []

    def test_reconcile_manifests_new_resources(self):
        """Test detection of new resources."""
        local = {
            "resources": {
                "worker1": {"resource_type": "ServerlessResource", "data": "v1"}
            }
        }
        persisted = {"resources": {}}

        result = reconcile_manifests(local, persisted)

        assert result.new == ["worker1"]
        assert result.changed == []
        assert result.removed == []
        assert result.unchanged == []

    def test_reconcile_manifests_removed_resources(self):
        """Test detection of removed resources."""
        local = {"resources": {}}
        persisted = {
            "resources": {
                "worker1": {
                    "resource_type": "ServerlessResource",
                    "config_hash": "abc123",
                }
            }
        }

        result = reconcile_manifests(local, persisted)

        assert result.new == []
        assert result.changed == []
        assert result.removed == ["worker1"]
        assert result.unchanged == []

    def test_reconcile_manifests_changed_resources(self):
        """Test detection of changed resources."""
        local_data = {"resource_type": "ServerlessResource", "config": "v2"}

        persisted_data = {"resource_type": "ServerlessResource", "config": "v1"}
        persisted_hash = compute_resource_hash(persisted_data)

        local = {"resources": {"worker1": local_data}}
        persisted = {
            "resources": {"worker1": {**persisted_data, "config_hash": persisted_hash}}
        }

        result = reconcile_manifests(local, persisted)

        assert result.new == []
        assert result.changed == ["worker1"]
        assert result.removed == []
        assert result.unchanged == []

    def test_reconcile_manifests_unchanged_resources(self):
        """Test detection of unchanged resources."""
        resource_data = {"resource_type": "ServerlessResource", "config": "v1"}
        resource_hash = compute_resource_hash(resource_data)

        local = {"resources": {"worker1": resource_data}}
        persisted = {
            "resources": {"worker1": {**resource_data, "config_hash": resource_hash}}
        }

        result = reconcile_manifests(local, persisted)

        assert result.new == []
        assert result.changed == []
        assert result.removed == []
        assert result.unchanged == ["worker1"]

    def test_reconcile_manifests_includes_load_balancer_resources(self):
        """Test that LoadBalancer resources are included in provisioning."""
        local = {
            "resources": {
                "mothership": {
                    "resource_type": "LoadBalancerSlsResource",
                    "data": "v1",
                },
                "worker1": {"resource_type": "ServerlessResource", "data": "v1"},
            }
        }
        persisted = {"resources": {}}

        result = reconcile_manifests(local, persisted)

        # LoadBalancer should be in new resources alongside Serverless
        assert "mothership" in result.new
        assert "worker1" in result.new

    def test_reconcile_manifests_includes_live_load_balancer(self):
        """Test that LiveLoadBalancer resources are included in provisioning."""
        local = {
            "resources": {
                "live_mothership": {
                    "resource_type": "LiveLoadBalancer",
                    "data": "v1",
                },
                "worker1": {"resource_type": "ServerlessResource", "data": "v1"},
            }
        }
        persisted = {"resources": {}}

        result = reconcile_manifests(local, persisted)

        # LiveLoadBalancer should be in new resources alongside Serverless
        assert "live_mothership" in result.new
        assert "worker1" in result.new

    def test_reconcile_manifests_persisted_none(self):
        """Test reconciliation when persisted manifest is None (first boot)."""
        local = {
            "resources": {
                "worker1": {"resource_type": "ServerlessResource", "data": "v1"}
            }
        }

        result = reconcile_manifests(local, None)

        assert result.new == ["worker1"]
        assert result.changed == []
        assert result.removed == []

    def test_reconcile_manifests_mixed_scenario(self):
        """Test reconciliation with mixed new, changed, and removed resources."""
        resource_data_1 = {"resource_type": "ServerlessResource", "config": "v1"}
        resource_hash_1 = compute_resource_hash(resource_data_1)

        resource_data_2_old = {"resource_type": "ServerlessResource", "config": "v1"}
        resource_hash_2_old = compute_resource_hash(resource_data_2_old)

        resource_data_2_new = {"resource_type": "ServerlessResource", "config": "v2"}

        local = {
            "resources": {
                "new_worker": resource_data_1,
                "changed_worker": resource_data_2_new,
                "unchanged_worker": resource_data_1,
            }
        }

        persisted = {
            "resources": {
                "changed_worker": {
                    **resource_data_2_old,
                    "config_hash": resource_hash_2_old,
                },
                "unchanged_worker": {
                    **resource_data_1,
                    "config_hash": resource_hash_1,
                },
                "removed_worker": {
                    "resource_type": "ServerlessResource",
                    "config_hash": "old_hash",
                },
            }
        }

        result = reconcile_manifests(local, persisted)

        assert result.new == ["new_worker"]
        assert result.changed == ["changed_worker"]
        assert result.removed == ["removed_worker"]
        assert "unchanged_worker" in result.unchanged


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

    def test_create_resource_lb_via_is_mothership_sets_endpoint_type(self):
        """Test that is_mothership=True sets both FLASH_ENDPOINT_TYPE and legacy var."""
        resource_name = "lb_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "is_mothership": True,
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, "https://test.api.runpod.ai"
            )

            assert resource.env["FLASH_ENDPOINT_TYPE"] == "lb"
            assert resource.env["FLASH_IS_MOTHERSHIP"] == "true"

    def test_create_resource_lb_via_is_load_balanced_sets_endpoint_type(self):
        """Test that is_load_balanced=True sets FLASH_ENDPOINT_TYPE=lb."""
        resource_name = "lb_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "is_load_balanced": True,
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, "https://test.api.runpod.ai"
            )

            assert resource.env["FLASH_ENDPOINT_TYPE"] == "lb"
            # Legacy var also set for backward compat
            assert resource.env["FLASH_IS_MOTHERSHIP"] == "true"

    def test_create_resource_non_lb_does_not_set_endpoint_type(self):
        """Test that non-LB resources do NOT get FLASH_ENDPOINT_TYPE."""
        resource_name = "plain_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, "https://test.api.runpod.ai"
            )

            assert "FLASH_ENDPOINT_TYPE" not in resource.env
            assert "FLASH_IS_MOTHERSHIP" not in resource.env

    def test_create_resource_lb_sets_main_file_and_app_variable(self):
        """Test that FLASH_MAIN_FILE and FLASH_APP_VARIABLE still work for LB resources."""
        resource_name = "lb_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "is_mothership": True,
            "main_file": "app.py",
            "app_variable": "my_app",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, "https://test.api.runpod.ai"
            )

            assert resource.env["FLASH_ENDPOINT_TYPE"] == "lb"
            assert resource.env["FLASH_IS_MOTHERSHIP"] == "true"
            assert resource.env["FLASH_MAIN_FILE"] == "app.py"
            assert resource.env["FLASH_APP_VARIABLE"] == "my_app"

    def test_create_resource_lb_via_is_load_balanced_with_main_file(self):
        """Test main_file and app_variable work with is_load_balanced flag too."""
        resource_name = "lb_worker"
        resource_data = {
            "resource_type": "ServerlessResource",
            "imageName": "runpod/flash:latest",
            "is_load_balanced": True,
            "main_file": "server.py",
            "app_variable": "server_app",
        }

        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "mothership-123"}):
            resource = create_resource_from_manifest(
                resource_name, resource_data, "https://test.api.runpod.ai"
            )

            assert resource.env["FLASH_ENDPOINT_TYPE"] == "lb"
            assert resource.env["FLASH_MAIN_FILE"] == "server.py"
            assert resource.env["FLASH_APP_VARIABLE"] == "server_app"
