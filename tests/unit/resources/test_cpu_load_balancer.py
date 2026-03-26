"""
Tests for CpuLoadBalancerSlsResource CPU-specific functionality.

Ensures CPU load balancers exclude GPU-specific fields from RunPod API payloads
and override GPU defaults to CPU-appropriate values.
"""

import os

from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.load_balancer_sls_resource import (
    CpuLoadBalancerSlsResource,
)
from runpod_flash.core.resources.serverless import ServerlessType, ServerlessScalerType
from runpod_flash.core.resources.serverless_cpu import CpuServerlessEndpoint

# Set a dummy API key for tests that create ResourceManager instances
os.environ.setdefault("RUNPOD_API_KEY", "test-key-for-unit-tests")


class TestCpuLoadBalancerDefaults:
    """Test CpuLoadBalancerSlsResource default configuration."""

    def test_cpu_load_balancer_creation_with_defaults(self):
        """Test creating CpuLoadBalancerSlsResource with minimal config."""
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
        )

        assert lb.name == "test-cpu-lb-fb"
        assert lb.imageName == "test/image:latest"
        assert lb.type == ServerlessType.LB
        assert lb.scalerType == ServerlessScalerType.REQUEST_COUNT

    def test_cpu_load_balancer_with_custom_instances(self):
        """Test explicit CPU instance type configuration."""
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4, CpuInstanceType.CPU3G_2_8],
        )

        assert lb.instanceIds == [CpuInstanceType.CPU3G_1_4, CpuInstanceType.CPU3G_2_8]

    def test_cpu_load_balancer_default_instances(self):
        """Test default CPU instance type."""
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
        )

        # Should default to CPU3G_2_8
        assert lb.instanceIds == [CpuInstanceType.CPU3G_2_8]


class TestCpuLoadBalancerGpuFieldOverride:
    """Test that GPU fields are correctly overridden to CPU defaults."""

    def test_sync_cpu_fields_overrides_gpu_defaults(self):
        """Test _sync_cpu_fields overrides GPU defaults to CPU values."""
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # GPU fields should be overridden to CPU defaults
        assert lb.gpuCount == 0, "gpuCount should be 0 for CPU endpoints"
        assert lb.allowedCudaVersions == "", "allowedCudaVersions should be empty"
        assert lb.minCudaVersion is None, "minCudaVersion should be None for CPU"
        assert lb.gpuIds == "", "gpuIds should be empty"

    def test_gpu_fields_not_hardcoded_in_constructor(self):
        """Test that GPU fields are overridden even if passed to constructor."""
        # Attempting to set GPU-specific fields should be overridden
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
            gpuCount=4,  # Should be overridden
            allowedCudaVersions="12.0",  # Should be overridden
        )

        assert lb.gpuCount == 0
        assert lb.allowedCudaVersions == ""


class TestCpuLoadBalancerInputOnlyExclusion:
    """Test that _input_only set contains all GPU-specific fields."""

    def test_input_only_contains_gpu_fields(self):
        """Test _input_only set contains all GPU-specific fields."""
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
        )

        # Critical fields that must be excluded
        required_excludes = {
            "gpuCount",
            "allowedCudaVersions",
            "minCudaVersion",
            "gpuIds",
            "cudaVersions",
            "gpus",
        }
        for field in required_excludes:
            assert field in lb._input_only, f"{field} must be in _input_only"

    def test_input_only_includes_common_fields(self):
        """Test _input_only includes expected common fields."""
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
        )

        expected_fields = {
            "id",
            "datacenter",
            "env",
            "flashboot",
            "imageName",
            "networkVolume",
        }
        for field in expected_fields:
            assert field in lb._input_only


class TestCpuLoadBalancerPayloadExclusion:
    """Test that GPU fields are excluded from model_dump payload."""

    def test_model_dump_excludes_gpu_fields_from_payload(self):
        """Test model_dump payload excludes GPU fields from API."""
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # GPU fields must NOT be in payload
        assert "gpuCount" not in payload, "gpuCount should be excluded from payload"
        assert "allowedCudaVersions" not in payload, (
            "allowedCudaVersions should be excluded"
        )
        assert "minCudaVersion" not in payload, "minCudaVersion should be excluded"
        assert "gpuIds" not in payload, "gpuIds should be excluded"
        assert "cudaVersions" not in payload, "cudaVersions should be excluded"
        assert "gpus" not in payload, "gpus should be excluded"

    def test_model_dump_includes_cpu_fields_in_payload(self):
        """Test model_dump payload includes CPU-specific fields."""
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # CPU fields must be in payload
        assert "instanceIds" in payload
        assert payload["instanceIds"] == ["cpu3g-1-4"]

    def test_model_dump_contains_required_lb_fields(self):
        """Test model_dump includes required load balancer fields."""
        lb = CpuLoadBalancerSlsResource(
            name="prod-api",
            imageName="myapp/api:v1",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
            workersMin=1,
            workersMax=5,
        )

        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # Required LB fields
        assert payload["name"] == "prod-api-fb"
        assert payload["type"] == "LB"
        assert payload["scalerType"] == "REQUEST_COUNT"
        assert payload["workersMin"] == 1
        assert payload["workersMax"] == 5

    def test_model_dump_excludes_template_image_name(self):
        """Test imageName is excluded (sent via template object)."""
        lb = CpuLoadBalancerSlsResource(
            name="test",
            imageName="test/image:latest",
        )

        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # imageName should be excluded (it's template-specific)
        assert "imageName" not in payload

    def test_model_dump_includes_template_object(self):
        """Test template object is included in payload."""
        lb = CpuLoadBalancerSlsResource(
            name="test",
            imageName="test/image:latest",
        )

        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # Template object should be present
        assert "template" in payload
        assert isinstance(payload["template"], dict)
        assert "imageName" in payload["template"]


class TestCpuLoadBalancerComparison:
    """Compare CpuLoadBalancerSlsResource with CpuServerlessEndpoint for consistency."""

    def test_input_only_alignment_with_cpu_serverless(self):
        """Test _input_only aligns with CpuServerlessEndpoint for GPU fields."""
        lb = CpuLoadBalancerSlsResource(
            name="lb",
            imageName="test:latest",
        )

        serverless = CpuServerlessEndpoint(
            name="serverless",
            imageName="test:latest",
        )

        # Critical GPU fields should be in both _input_only sets
        gpu_fields = {
            "gpuCount",
            "allowedCudaVersions",
            "minCudaVersion",
            "gpuIds",
            "cudaVersions",
            "gpus",
        }

        for field in gpu_fields:
            assert field in lb._input_only, f"{field} should be in LB _input_only"
            assert field in serverless._input_only, (
                f"{field} should be in Serverless _input_only"
            )

    def test_gpu_field_sync_consistency(self):
        """Test GPU field values match between LB and Serverless."""
        lb = CpuLoadBalancerSlsResource(
            name="lb",
            imageName="test:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        serverless = CpuServerlessEndpoint(
            name="serverless",
            imageName="test:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # Both should have identical GPU field values
        assert lb.gpuCount == serverless.gpuCount == 0
        assert lb.allowedCudaVersions == serverless.allowedCudaVersions == ""
        assert lb.minCudaVersion is None
        assert serverless.minCudaVersion is None
        assert lb.gpuIds == serverless.gpuIds == ""


class TestCpuLoadBalancerDiskSizing:
    """Test CPU load balancer disk auto-sizing functionality."""

    def test_cpu_load_balancer_auto_sizes_disk_default_instance(self):
        """Test that CPU load balancer auto-sizes disk for default CPU3G_2_8."""
        lb = CpuLoadBalancerSlsResource(
            name="test-lb",
            imageName="test/image:latest",
        )

        # CPU3G_2_8 should auto-size to 20GB
        assert lb.template.containerDiskInGb == 20

    def test_cpu_load_balancer_auto_sizes_disk_cpu3g_1_4(self):
        """Test that CPU load balancer auto-sizes disk for CPU3G_1_4 to 10GB."""
        lb = CpuLoadBalancerSlsResource(
            name="test-lb",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # CPU3G_1_4 should auto-size to 10GB
        assert lb.template.containerDiskInGb == 10

    def test_cpu_load_balancer_auto_sizes_disk_multiple_instances(self):
        """Test that CPU load balancer uses minimum disk size for multiple instances."""
        lb = CpuLoadBalancerSlsResource(
            name="test-lb",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4, CpuInstanceType.CPU3G_2_8],
        )

        # Multiple instances should use minimum (CPU3G_1_4 has 10GB, CPU3G_2_8 has 20GB)
        assert lb.template.containerDiskInGb == 10

    def test_cpu_load_balancer_preserves_custom_disk_size(self):
        """Test that explicit disk sizes are preserved during auto-sizing."""
        from runpod_flash.core.resources.template import PodTemplate

        template = PodTemplate(
            name="custom",
            imageName="test/image:latest",
            containerDiskInGb=15,
        )

        lb = CpuLoadBalancerSlsResource(
            name="test-lb",
            template=template,
            instanceIds=[CpuInstanceType.CPU3G_2_8],
        )

        # Custom disk size should be preserved
        assert lb.template.containerDiskInGb == 15


class TestCpuLoadBalancerIntegration:
    """Integration tests for CPU load balancer deployment payloads."""

    def test_deployment_payload_structure_is_valid(self):
        """Test deployment payload has correct structure for RunPod API."""
        lb = CpuLoadBalancerSlsResource(
            name="prod-api",
            imageName="myapp/api:v1",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
            workersMin=1,
            workersMax=5,
            scalerValue=10,
        )

        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # Verify payload structure
        required_fields = {"name", "type", "scalerType", "workersMin", "workersMax"}
        for field in required_fields:
            assert field in payload, f"Required field {field} not in payload"

        # Verify no GPU fields
        gpu_fields = {"gpuCount", "allowedCudaVersions", "minCudaVersion", "gpuIds"}
        for field in gpu_fields:
            assert field not in payload, f"GPU field {field} should not be in payload"

    def test_cpu_disk_sizing_respects_limits(self):
        """Test that CPU load balancer doesn't raise disk sizing errors on creation."""
        # This test verifies that we can create a CPU LB without disk sizing errors
        # The actual disk sizing is applied when needed via _apply_cpu_disk_sizing
        lb = CpuLoadBalancerSlsResource(
            name="test-cpu-lb",
            imageName="test/image:latest",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        # Should have a template
        assert lb.template is not None
        assert lb.template.imageName == "test/image:latest"

    def test_cpu_load_balancer_with_env_vars(self):
        """Test CPU load balancer with environment variables."""
        env = {
            "FLASH_APP": "my_app",
            "LOG_LEVEL": "DEBUG",
        }

        lb = CpuLoadBalancerSlsResource(
            name="test",
            imageName="test/image:latest",
            env=env,
        )

        assert lb.env == env

    def test_cpu_load_balancer_with_worker_config(self):
        """Test CPU load balancer with worker scaling configuration."""
        lb = CpuLoadBalancerSlsResource(
            name="test",
            imageName="test/image:latest",
            workersMin=1,
            workersMax=5,
            scalerValue=10,
        )

        assert lb.workersMin == 1
        assert lb.workersMax == 5
        assert lb.scalerValue == 10
