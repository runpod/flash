"""
Unit tests for LiveServerless and CpuLiveServerless classes.
"""

import pytest
from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.live_serverless import (
    LiveServerless,
    CpuLiveServerless,
)
from runpod_flash.core.resources.template import PodTemplate


class TestLiveServerless:
    """Test LiveServerless (GPU) class behavior."""

    def test_live_serverless_workers_min_cannot_exceed_workers_max(self):
        with pytest.raises(
            ValueError,
            match=r"workersMin \(5\) cannot be greater than workersMax \(1\)",
        ):
            LiveServerless(name="broken", workersMin=5, workersMax=1)

    def test_live_serverless_gpu_defaults(self):
        """Test LiveServerless uses GPU image and defaults."""
        live_serverless = LiveServerless(
            name="example_gpu_live_serverless",
        )

        # Should not have CPU instances, uses default 64GB
        assert live_serverless.instanceIds is None
        assert live_serverless.template is not None
        assert live_serverless.template.containerDiskInGb == 64
        assert "flash:" in live_serverless.imageName  # GPU image

    def test_live_serverless_image_locked(self):
        """Test LiveServerless imageName is locked to GPU image."""
        live_serverless = LiveServerless(
            name="example_gpu_live_serverless",
        )

        original_image = live_serverless.imageName

        # Attempt to change imageName - should be ignored
        live_serverless.imageName = "custom/image:latest"

        assert live_serverless.imageName == original_image
        assert "flash:" in live_serverless.imageName  # Still GPU image

    def test_live_serverless_with_custom_template(self):
        """Test LiveServerless with custom template."""
        template = PodTemplate(
            name="custom",
            imageName="test/image:v1",
            containerDiskInGb=100,
        )

        live_serverless = LiveServerless(
            name="example_gpu_live_serverless",
            template=template,
        )

        # Should preserve custom template settings
        assert live_serverless.template.containerDiskInGb == 100


class TestCpuLiveServerless:
    """Test CpuLiveServerless class behavior."""

    def test_cpu_live_serverless_defaults(self):
        """Test CpuLiveServerless uses CPU image and auto-sizing."""
        live_serverless = CpuLiveServerless(
            name="example_cpu_live_serverless",
        )

        # Should default to CPU3G_2_8
        assert live_serverless.instanceIds == [CpuInstanceType.CPU3G_2_8]
        assert live_serverless.template is not None
        # Default disk size should be 20GB for CPU3G_2_8
        assert live_serverless.template.containerDiskInGb == 20
        assert "flash-cpu:" in live_serverless.imageName  # CPU image

    def test_cpu_live_serverless_custom_instances(self):
        """Test CpuLiveServerless with custom CPU instances."""
        live_serverless = CpuLiveServerless(
            name="example_cpu_live_serverless",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        assert live_serverless.instanceIds == [CpuInstanceType.CPU3G_1_4]
        assert live_serverless.template is not None
        assert live_serverless.template.containerDiskInGb == 10

    def test_cpu_live_serverless_multiple_instances(self):
        """Test CpuLiveServerless with multiple CPU instances."""
        live_serverless = CpuLiveServerless(
            name="example_cpu_live_serverless",
            instanceIds=[CpuInstanceType.CPU3G_1_4, CpuInstanceType.CPU5C_2_4],
        )

        assert live_serverless.template is not None
        assert live_serverless.template.containerDiskInGb == 10  # Min of 10 and 30

    def test_cpu_live_serverless_image_locked(self):
        """Test CpuLiveServerless imageName is locked to CPU image."""
        live_serverless = CpuLiveServerless(
            name="example_cpu_live_serverless",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        original_image = live_serverless.imageName

        # Attempt to change imageName - should be ignored
        live_serverless.imageName = "custom/image:latest"

        assert live_serverless.imageName == original_image
        assert "flash-cpu:" in live_serverless.imageName  # Still CPU image

    def test_cpu_live_serverless_validation_failure(self):
        """Test CpuLiveServerless validation fails with excessive disk size."""
        template = PodTemplate(
            name="custom",
            imageName="test/image:v1",
            containerDiskInGb=50,  # Exceeds 10GB limit
        )

        with pytest.raises(ValueError, match="Container disk size 50GB exceeds"):
            CpuLiveServerless(
                name="example_cpu_live_serverless",
                instanceIds=[CpuInstanceType.CPU3G_1_4],
                template=template,
            )

    def test_cpu_live_serverless_with_existing_template_default_size(self):
        """Test CpuLiveServerless auto-sizes existing template with default disk size."""
        template = PodTemplate(name="existing", imageName="test/image:v1")
        # Template uses default size

        live_serverless = CpuLiveServerless(
            name="example_cpu_live_serverless",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
            template=template,
        )

        assert live_serverless.template.containerDiskInGb == 10  # Should be auto-sized

    def test_cpu_live_serverless_preserves_custom_disk_size(self):
        """Test CpuLiveServerless preserves custom disk size in template."""
        template = PodTemplate(
            name="existing",
            imageName="test/image:v1",
            containerDiskInGb=5,  # Custom size within limits
        )

        live_serverless = CpuLiveServerless(
            name="example_cpu_live_serverless",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
            template=template,
        )

        assert (
            live_serverless.template.containerDiskInGb == 5
        )  # Should preserve custom size


class TestLiveServerlessMixin:
    """Test LiveServerlessMixin functionality."""

    def test_live_image_property_gpu(self):
        """Test LiveServerless _live_image property."""
        live_serverless = LiveServerless(name="test")
        assert "flash:" in live_serverless._live_image
        assert "cpu" not in live_serverless._live_image

    def test_live_image_property_cpu(self):
        """Test CpuLiveServerless _live_image property."""
        live_serverless = CpuLiveServerless(name="test")
        assert "flash-cpu:" in live_serverless._live_image

    def test_image_name_property_gpu(self):
        """Test LiveServerless imageName property returns locked image."""
        live_serverless = LiveServerless(name="test")
        assert live_serverless.imageName == live_serverless._live_image

    def test_image_name_property_cpu(self):
        """Test CpuLiveServerless imageName property returns locked image."""
        live_serverless = CpuLiveServerless(name="test")
        assert live_serverless.imageName == live_serverless._live_image

    def test_image_name_setter_ignored_gpu(self):
        """Test LiveServerless imageName setter is ignored."""
        live_serverless = LiveServerless(name="test")
        original_image = live_serverless.imageName

        live_serverless.imageName = "should-be-ignored"

        assert live_serverless.imageName == original_image

    def test_image_name_setter_ignored_cpu(self):
        """Test CpuLiveServerless imageName setter is ignored."""
        live_serverless = CpuLiveServerless(name="test")
        original_image = live_serverless.imageName

        live_serverless.imageName = "should-be-ignored"

        assert live_serverless.imageName == original_image
