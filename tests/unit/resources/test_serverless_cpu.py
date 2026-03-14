"""
Unit tests for CpuServerlessEndpoint class.
"""

import pickle
import pytest
from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.serverless_cpu import CpuServerlessEndpoint
from runpod_flash.core.resources.template import PodTemplate


class TestCpuServerlessEndpoint:
    """Test CpuServerlessEndpoint class behavior."""

    def test_cpu_serverless_endpoint_defaults(self):
        """Test CpuServerlessEndpoint has correct defaults."""
        endpoint = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
        )

        # Should default to CPU3G_2_8
        assert endpoint.instanceIds == [CpuInstanceType.CPU3G_2_8]
        assert endpoint.template is not None
        assert endpoint.template.containerDiskInGb == 20  # Max disk for CPU3G_2_8

    def test_cpu_serverless_endpoint_custom_instances(self):
        """Test CpuServerlessEndpoint with custom instance types."""
        endpoint = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        assert endpoint.instanceIds == [CpuInstanceType.CPU3G_1_4]
        assert endpoint.template is not None
        assert endpoint.template.containerDiskInGb == 10

    def test_cpu_serverless_endpoint_with_existing_template(self):
        """Test CpuServerlessEndpoint with existing template."""
        template = PodTemplate(name="existing", imageName="test/image:v1")

        endpoint = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            template=template,
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        assert endpoint.template.containerDiskInGb == 10  # Should be auto-sized

    def test_cpu_serverless_endpoint_preserves_custom_disk_size(self):
        """Test CpuServerlessEndpoint preserves custom disk size in template."""
        template = PodTemplate(
            name="existing",
            imageName="test/image:v1",
            containerDiskInGb=5,
        )

        endpoint = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            template=template,
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        assert endpoint.template.containerDiskInGb == 5  # Should preserve custom size

    def test_cpu_serverless_endpoint_with_template_id(self):
        """Test CpuServerlessEndpoint with templateId."""
        endpoint = CpuServerlessEndpoint(
            name="test-endpoint",
            templateId="template-123",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        assert endpoint.template is None
        assert endpoint.templateId == "template-123"


class TestCpuServerlessEndpointValidation:
    """Test CpuServerlessEndpoint disk size validation."""

    def test_validation_passes_within_limits(self):
        """Test validation passes when disk size is within limits."""
        template = PodTemplate(
            name="test",
            imageName="test/image:v1",
            containerDiskInGb=5,
        )

        # Should not raise any exception
        endpoint = CpuServerlessEndpoint(
            name="test-endpoint",
            template=template,
            instanceIds=[CpuInstanceType.CPU3G_1_4],  # 10GB limit
        )

        assert endpoint.template.containerDiskInGb == 5

    def test_validation_passes_at_exact_limit(self):
        """Test validation passes at exact disk size limit."""
        template = PodTemplate(
            name="test",
            imageName="test/image:v1",
            containerDiskInGb=10,  # Exactly at limit
        )

        # Should not raise any exception
        endpoint = CpuServerlessEndpoint(
            name="test-endpoint",
            template=template,
            instanceIds=[CpuInstanceType.CPU3G_1_4],  # 10GB limit
        )

        assert endpoint.template.containerDiskInGb == 10

    def test_validation_fails_exceeds_limits(self):
        """Test validation fails when disk size exceeds limits."""
        template = PodTemplate(
            name="test",
            imageName="test/image:v1",
            containerDiskInGb=15,  # Exceeds 10GB limit
        )

        with pytest.raises(ValueError, match="Container disk size 15GB exceeds"):
            CpuServerlessEndpoint(
                name="test-endpoint",
                template=template,
                instanceIds=[CpuInstanceType.CPU3G_1_4],  # 10GB limit
            )

    def test_validation_fails_one_gb_over_limit(self):
        """Test validation fails when one GB over limit."""
        template = PodTemplate(
            name="test",
            imageName="test/image:v1",
            containerDiskInGb=11,  # One GB over limit
        )

        with pytest.raises(ValueError, match="Container disk size 11GB exceeds"):
            CpuServerlessEndpoint(
                name="test-endpoint",
                template=template,
                instanceIds=[CpuInstanceType.CPU3G_1_4],  # 10GB limit
            )

    def test_validation_error_message_multiple_instances(self):
        """Test validation error message includes all instance limits."""
        template = PodTemplate(
            name="test",
            imageName="test/image:v1",
            containerDiskInGb=25,
        )

        with pytest.raises(ValueError) as exc_info:
            CpuServerlessEndpoint(
                name="test-endpoint",
                template=template,
                instanceIds=[CpuInstanceType.CPU3G_1_4, CpuInstanceType.CPU3G_2_8],
            )

        error_msg = str(exc_info.value)
        assert "Container disk size 25GB exceeds" in error_msg
        assert "cpu3g-1-4: max 10GB" in error_msg
        assert "cpu3g-2-8: max 20GB" in error_msg
        assert "Maximum allowed: 10GB" in error_msg

    def test_no_validation_without_template(self):
        """Test no validation when using templateId instead of template."""
        # Should not raise any exception
        endpoint = CpuServerlessEndpoint(
            name="test-endpoint",
            templateId="template-123",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        assert endpoint.templateId == "template-123"

    def test_validation_mixed_instance_types_different_generations(self):
        """Test validation with mixed instance types from different generations."""
        endpoint = CpuServerlessEndpoint(
            name="test-endpoint",
            imageName="test/image:latest",
            instanceIds=[
                CpuInstanceType.CPU3G_1_4,  # 10GB
                CpuInstanceType.CPU3C_2_4,  # 20GB
                CpuInstanceType.CPU5C_1_2,  # 15GB
            ],
        )

        assert endpoint.template is not None
        assert endpoint.template.containerDiskInGb == 10  # Minimum across all types


class TestCpuValidation:
    """Test CPU instance type validation."""

    def test_validate_cpus_preserves_explicit_list(self):
        """Test that validate_cpus preserves explicit instance type lists."""
        explicit_types = [CpuInstanceType.CPU3G_1_4, CpuInstanceType.CPU5C_2_4]

        endpoint = CpuServerlessEndpoint(
            name="test-endpoint",
            imageName="test/image:latest",
            instanceIds=explicit_types,
        )

        # Should preserve the explicit list
        assert endpoint.instanceIds == explicit_types

    def test_validate_cpus_preserves_single_instance(self):
        """Test that validate_cpus preserves single explicit instance type."""
        endpoint = CpuServerlessEndpoint(
            name="test-endpoint",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3C_4_8],
        )

        # Should preserve the single instance type
        assert endpoint.instanceIds == [CpuInstanceType.CPU3C_4_8]


class TestCpuEndpointMixin:
    """Test CpuEndpointMixin functionality."""

    def test_is_cpu_endpoint_detection(self):
        """Test _is_cpu_endpoint correctly identifies CPU endpoints."""
        cpu_endpoint = CpuServerlessEndpoint(
            name="cpu-endpoint",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        assert cpu_endpoint._is_cpu_endpoint() is True

    def test_is_cpu_endpoint_empty_instance_ids(self):
        """Test _is_cpu_endpoint with empty instanceIds."""
        cpu_endpoint = CpuServerlessEndpoint(
            name="cpu-endpoint",
            imageName="test/image:latest",
            instanceIds=[],
        )

        assert cpu_endpoint._is_cpu_endpoint() is False

    def test_get_cpu_container_disk_size(self):
        """Test _get_cpu_container_disk_size calculation."""
        cpu_endpoint = CpuServerlessEndpoint(
            name="cpu-endpoint",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4, CpuInstanceType.CPU3G_2_8],
        )

        assert cpu_endpoint._get_cpu_container_disk_size() == 10  # Minimum

    def test_sync_cpu_fields(self):
        """Test _sync_cpu_fields overrides GPU defaults."""
        cpu_endpoint = CpuServerlessEndpoint(
            name="cpu-endpoint",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # GPU fields should be cleared/set to default CPU values
        assert cpu_endpoint.gpuCount == 0
        assert cpu_endpoint.allowedCudaVersions == ""
        assert cpu_endpoint.minCudaVersion is None
        assert cpu_endpoint.gpuIds == ""


class TestCpuConfigHash:
    """Test CPU endpoint config_hash consistency and drift detection."""

    def test_config_hash_consistent_across_pickle_load(self):
        """Test that config_hash is consistent after pickle/unpickle cycle."""
        # Create original endpoint
        original = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )
        original_hash = original.config_hash

        # Pickle and unpickle
        pickled = pickle.dumps(original)
        loaded = pickle.loads(pickled)
        loaded_hash = loaded.config_hash

        # Hashes should match
        assert loaded_hash == original_hash, (
            f"Config hash changed after pickle/unpickle: "
            f"{original_hash} != {loaded_hash}"
        )

    def test_config_hash_consistent_across_recreation(self):
        """Test that config_hash is consistent when recreating the same endpoint."""
        endpoint1 = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        endpoint2 = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # Both should have identical hashes since they're the same config
        assert endpoint1.config_hash == endpoint2.config_hash

    def test_config_hash_changes_with_meaningful_changes(self):
        """Test that config_hash changes when actual config changes."""
        endpoint1 = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        endpoint2 = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:v2",  # Changed image
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # Hashes should differ since image changed
        assert endpoint1.config_hash != endpoint2.config_hash

    def test_cpu_structural_changes_false_positives(self):
        """Test that CPU endpoints don't have false positive structural changes.

        This reproduces the issue where reloading from pickle causes
        structural changes to be detected even though nothing changed.
        """
        # Create original CPU endpoint
        original = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # Pickle and unpickle to simulate saved state
        pickled = pickle.dumps(original)
        loaded = pickle.loads(pickled)

        # Create a new config with the same parameters
        new_config = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # Check structural fields don't differ
        structural_fields = [
            "gpus",
            "gpuIds",
            "template",
            "templateId",
            "imageName",
            "flashboot",
            "allowedCudaVersions",
            "cudaVersions",
            "minCudaVersion",
            "instanceIds",
        ]

        for field in structural_fields:
            old_val = getattr(loaded, field, None)
            new_val = getattr(new_config, field, None)

            # Handle list comparison
            if isinstance(old_val, list) and isinstance(new_val, list):
                old_sorted = sorted(str(v) for v in old_val)
                new_sorted = sorted(str(v) for v in new_val)
                assert old_sorted == new_sorted, (
                    f"Structural change in '{field}': loaded={old_val} vs new={new_val}"
                )
            else:
                # For Pydantic models, compare their data representation to avoid
                # internal state differences after pickle/unpickle (e.g., __pydantic_fields_set__)
                if hasattr(old_val, "model_dump") and hasattr(new_val, "model_dump"):
                    assert old_val.model_dump() == new_val.model_dump(), (
                        f"Structural change in '{field}': loaded={old_val} vs new={new_val}"
                    )
                else:
                    assert old_val == new_val, (
                        f"Structural change in '{field}': loaded={old_val} vs new={new_val}"
                    )

    def test_config_hash_excludes_gpu_fields(self):
        """Test that config_hash for CPU endpoints excludes GPU-specific fields.

        This test verifies that:
        1. GPU-specific fields ARE in _input_only (for API payload exclusion)
        2. GPU-specific fields are NOT included in config_hash (to avoid false drift detection)
        """
        endpoint = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # GPU-specific fields should be in _input_only for API payload exclusion
        assert "cudaVersions" in endpoint._input_only
        assert "gpuIds" in endpoint._input_only
        assert "gpuCount" in endpoint._input_only
        assert "allowedCudaVersions" in endpoint._input_only
        assert "minCudaVersion" in endpoint._input_only

        # Create two endpoints with different GPU field values
        endpoint1 = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )
        endpoint1.gpuCount = 0
        endpoint1.allowedCudaVersions = ""

        endpoint2 = CpuServerlessEndpoint(
            name="test-cpu-endpoint",
            imageName="test/cpu-image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )
        endpoint2.gpuCount = 1  # Different value
        endpoint2.allowedCudaVersions = "11.8"  # Different value

        # Config hashes should be identical since GPU fields are excluded
        assert endpoint1.config_hash == endpoint2.config_hash

    def test_template_object_comparison_issue(self):
        """Test that demonstrates the template object identity issue in _has_structural_changes.

        When comparing templates using !=, different instances are never equal
        even if they have the same content, causing false structural changes.
        """
        from runpod_flash.core.resources.template import PodTemplate

        template1 = PodTemplate(
            name="test-template",
            imageName="test/image:latest",
        )

        template2 = PodTemplate(
            name="test-template",
            imageName="test/image:latest",
        )

        # Even though they're identical, they're different objects
        assert template1 == template2  # Value equality works
        assert template1 is not template2  # But they're different instances

        # The bug: _has_structural_changes uses !=  which works with Pydantic models
        # Actually, Pydantic models override __eq__ so != should work correctly
        # Let me verify this works as expected
        assert not (template1 != template2)
