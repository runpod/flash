"""Unit tests for LiveServerless, CpuLiveServerless, and LiveServerlessMixin."""

import pytest
from runpod_flash.core.resources.constants import (
    FLASH_CPU_BASE_IMAGE,
    FLASH_GPU_BASE_IMAGE,
)
from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.live_serverless import (
    CpuLiveLoadBalancer,
    CpuLiveServerless,
    LiveLoadBalancer,
    LiveServerless,
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
        """Test LiveServerless uses GPU base image and defaults."""
        live_serverless = LiveServerless(name="example_gpu_live_serverless")

        assert live_serverless.instanceIds is None
        assert live_serverless.template is not None
        assert live_serverless.template.containerDiskInGb == 64
        assert live_serverless.imageName == FLASH_GPU_BASE_IMAGE

    def test_live_serverless_default_base_image(self):
        """Test default image is the GPU base image (not flash-worker image)."""
        live_serverless = LiveServerless(name="test")
        assert live_serverless.imageName == FLASH_GPU_BASE_IMAGE
        assert "pytorch" in live_serverless.imageName

    def test_live_serverless_user_can_override_image(self):
        """Test user can set custom imageName (BYOI)."""
        live_serverless = LiveServerless(
            name="test", imageName="nvidia/cuda:12.8.0-runtime-ubuntu22.04"
        )
        assert live_serverless.imageName == "nvidia/cuda:12.8.0-runtime-ubuntu22.04"

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
        assert live_serverless.template.containerDiskInGb == 100

    def test_live_serverless_template_has_docker_args(self):
        """Test that the template includes dockerArgs for process injection."""
        live_serverless = LiveServerless(name="test")
        assert live_serverless.template is not None
        assert live_serverless.template.dockerArgs
        assert "bootstrap.sh" in live_serverless.template.dockerArgs


class TestCpuLiveServerless:
    """Test CpuLiveServerless class behavior."""

    def test_cpu_live_serverless_defaults(self):
        """Test CpuLiveServerless uses CPU base image and auto-sizing."""
        live_serverless = CpuLiveServerless(name="example_cpu_live_serverless")

        assert live_serverless.instanceIds == [CpuInstanceType.CPU3G_2_8]
        assert live_serverless.template is not None
        assert live_serverless.template.containerDiskInGb == 20
        assert live_serverless.imageName == FLASH_CPU_BASE_IMAGE

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
        assert live_serverless.template.containerDiskInGb == 10

    def test_cpu_live_serverless_user_can_override_image(self):
        """Test CpuLiveServerless allows user to set custom image."""
        live_serverless = CpuLiveServerless(name="test", imageName="python:3.11-slim")
        assert live_serverless.imageName == "python:3.11-slim"

    def test_cpu_live_serverless_validation_failure(self):
        """Test CpuLiveServerless validation fails with excessive disk size."""
        template = PodTemplate(
            name="custom",
            imageName="test/image:v1",
            containerDiskInGb=50,
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
        live_serverless = CpuLiveServerless(
            name="example_cpu_live_serverless",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
            template=template,
        )
        assert live_serverless.template.containerDiskInGb == 10

    def test_cpu_live_serverless_preserves_custom_disk_size(self):
        """Test CpuLiveServerless preserves custom disk size in template."""
        template = PodTemplate(
            name="existing",
            imageName="test/image:v1",
            containerDiskInGb=5,
        )
        live_serverless = CpuLiveServerless(
            name="example_cpu_live_serverless",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
            template=template,
        )
        assert live_serverless.template.containerDiskInGb == 5

    def test_cpu_live_serverless_template_has_docker_args(self):
        """Test CpuLiveServerless template includes dockerArgs."""
        live_serverless = CpuLiveServerless(name="test")
        assert live_serverless.template is not None
        assert live_serverless.template.dockerArgs
        assert "bootstrap.sh" in live_serverless.template.dockerArgs


class TestLiveServerlessMixin:
    """Test LiveServerlessMixin functionality."""

    def test_default_base_image_gpu(self):
        """Test LiveServerless _default_base_image property."""
        live_serverless = LiveServerless(name="test")
        assert live_serverless._default_base_image == FLASH_GPU_BASE_IMAGE

    def test_default_base_image_cpu(self):
        """Test CpuLiveServerless _default_base_image property."""
        live_serverless = CpuLiveServerless(name="test")
        assert live_serverless._default_base_image == FLASH_CPU_BASE_IMAGE

    def test_docker_args_set_on_new_template(self):
        """Test dockerArgs is set when creating a new template."""
        live_serverless = LiveServerless(name="test")
        assert live_serverless.template.dockerArgs
        assert "bash -c" in live_serverless.template.dockerArgs

    def test_docker_args_set_on_existing_template(self):
        """Test dockerArgs is set when configuring an existing template."""
        template = PodTemplate(
            name="existing",
            imageName="test/image:v1",
        )
        live_serverless = LiveServerless(name="test", template=template)
        assert live_serverless.template.dockerArgs
        assert "bootstrap.sh" in live_serverless.template.dockerArgs

    def test_all_live_classes_have_docker_args(self):
        """Test all Live* classes set dockerArgs on their templates."""
        classes_and_kwargs = [
            (LiveServerless, {}),
            (CpuLiveServerless, {}),
            (LiveLoadBalancer, {}),
            (CpuLiveLoadBalancer, {}),
        ]
        for cls, extra_kwargs in classes_and_kwargs:
            resource = cls(name=f"test-{cls.__name__}", **extra_kwargs)
            assert resource.template is not None, f"{cls.__name__} has no template"
            assert resource.template.dockerArgs, f"{cls.__name__} has no dockerArgs"
            assert "bootstrap.sh" in resource.template.dockerArgs, (
                f"{cls.__name__} missing bootstrap.sh in dockerArgs"
            )

    def test_live_load_balancer_defaults(self):
        """Test LiveLoadBalancer uses GPU base image."""
        lb = LiveLoadBalancer(name="test-lb")
        assert lb.imageName == FLASH_GPU_BASE_IMAGE
        assert lb.template is not None
        assert lb.template.dockerArgs

    def test_cpu_live_load_balancer_defaults(self):
        """Test CpuLiveLoadBalancer uses CPU base image."""
        lb = CpuLiveLoadBalancer(name="test-lb-cpu")
        assert lb.imageName == FLASH_CPU_BASE_IMAGE
        assert lb.template is not None
        assert lb.template.dockerArgs
