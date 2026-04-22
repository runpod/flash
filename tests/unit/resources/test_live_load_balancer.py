"""
Unit tests for LiveLoadBalancer class and template serialization.
"""

import os

import pytest

from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.live_serverless import (
    CpuLiveLoadBalancer,
    LiveLoadBalancer,
)
from runpod_flash.core.resources.load_balancer_sls_resource import (
    LoadBalancerSlsResource,
)


class TestLiveLoadBalancer:
    """Test LiveLoadBalancer class behavior."""

    def test_live_load_balancer_creation_with_local_tag(self, monkeypatch):
        """Test LiveLoadBalancer creates with local image tag."""
        monkeypatch.setenv("FLASH_IMAGE_TAG", "local")
        # Need to reload modules to pick up new env var
        import importlib
        import runpod_flash.core.constants as const_module
        import runpod_flash.core.resources.live_serverless as ls_module

        importlib.reload(const_module)
        importlib.reload(ls_module)

        lb = ls_module.LiveLoadBalancer(name="test-lb")
        expected_image = "runpod/flash-lb:py3.12-local"
        assert lb.imageName == expected_image
        assert lb.template is not None
        assert lb.template.imageName == expected_image

    def test_live_load_balancer_default_image_tag(self):
        """Test LiveLoadBalancer uses default image tag."""
        # Clear any custom tag
        os.environ.pop("FLASH_IMAGE_TAG", None)

        lb = LiveLoadBalancer(name="test-lb")

        assert "runpod/flash-lb:" in lb.imageName
        assert lb.template is not None
        assert lb.template.imageName == lb.imageName

    def test_live_load_balancer_template_creation(self):
        """Test LiveLoadBalancer creates proper template from imageName."""
        lb = LiveLoadBalancer(name="cpu_processor")

        # Should have a template created from imageName
        assert lb.template is not None
        assert lb.template.imageName == lb.imageName
        # Template name uses resource IDs, not the original name
        assert "LiveLoadBalancer" in lb.template.name
        assert "PodTemplate" in lb.template.name

    def test_live_load_balancer_template_env_variables(self):
        """Test LiveLoadBalancer template includes environment variables."""
        lb = LiveLoadBalancer(
            name="test-lb",
            env={"CUSTOM_VAR": "custom_value"},
        )

        assert lb.template is not None
        assert lb.template.env is not None
        assert len(lb.template.env) > 0

        # Check for custom env var
        custom_vars = [kv for kv in lb.template.env if kv.key == "CUSTOM_VAR"]
        assert len(custom_vars) == 1
        assert custom_vars[0].value == "custom_value"

    def test_live_load_balancer_payload_serialization(self):
        """Test LiveLoadBalancer serializes correctly for GraphQL deployment."""
        lb = LiveLoadBalancer(name="data_processor")

        # Generate payload as would be sent to RunPod
        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # Template must be in payload (not imageName since that's in _input_only)
        assert "template" in payload
        assert "imageName" not in payload

        # Template must have all required fields
        template = payload["template"]
        assert "imageName" in template
        assert "name" in template
        assert template["imageName"] == lb.imageName

    def test_live_load_balancer_type_is_lb(self):
        """Test LiveLoadBalancer has type=LB."""
        lb = LiveLoadBalancer(name="test-lb")

        assert lb.type.value == "LB"
        assert str(lb.type) == "ServerlessType.LB"

    def test_live_load_balancer_scaler_is_request_count(self):
        """Test LiveLoadBalancer uses REQUEST_COUNT scaler."""
        lb = LiveLoadBalancer(name="test-lb")

        assert lb.scalerType.value == "REQUEST_COUNT"


class TestLoadBalancerSlsResourceTemplate:
    """Test LoadBalancerSlsResource template handling."""

    def test_load_balancer_sls_with_image_name(self):
        """Test LoadBalancerSlsResource creates template from imageName."""
        lb = LoadBalancerSlsResource(
            name="test-lb",
            imageName="runpod/flash-lb:latest",
        )

        assert lb.template is not None
        assert lb.template.imageName == "runpod/flash-lb:latest"

    def test_load_balancer_sls_requires_image_template_or_id(self):
        """Test LoadBalancerSlsResource requires one of: imageName, template, templateId."""
        with pytest.raises(
            ValueError,
            match="Either imageName, template, or templateId must be provided",
        ):
            LoadBalancerSlsResource(name="test-lb")

    def test_load_balancer_sls_with_template_id(self):
        """Test LoadBalancerSlsResource works with templateId."""
        lb = LoadBalancerSlsResource(
            name="test-lb",
            templateId="template-123",
        )

        assert lb.templateId == "template-123"
        assert lb.template is None


class TestTemplateSerializationRoundtrip:
    """Test that template serialization works correctly for GraphQL."""

    def test_live_load_balancer_serialization_roundtrip(self):
        """Test that LiveLoadBalancer can be serialized and contains template."""
        lb = LiveLoadBalancer(
            name="test-service",
            env={"API_KEY": "secret123"},
        )

        # Simulate what gets sent to RunPod
        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # Verify GraphQL payload has template
        assert "template" in payload, "Template must be in GraphQL payload"
        assert payload["template"]["imageName"] is not None
        assert payload["template"]["name"] is not None

        # Verify imageName is NOT in payload (it's in _input_only)
        assert "imageName" not in payload

        # Verify the template has the correct image
        assert "flash-lb:" in payload["template"]["imageName"], (
            "Must have load-balancer image"
        )

    def test_template_env_serialization(self):
        """Test template environment variables serialize correctly."""
        lb = LiveLoadBalancer(
            name="test-lb",
            env={"VAR1": "value1", "VAR2": "value2"},
        )

        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        template_env = payload["template"]["env"]
        assert isinstance(template_env, list)
        assert len(template_env) >= 2

        # Check env vars are serialized as {key, value} objects
        var_keys = {kv["key"] for kv in template_env}
        assert "VAR1" in var_keys
        assert "VAR2" in var_keys


class TestCpuLiveLoadBalancer:
    """Test CpuLiveLoadBalancer class behavior."""

    def test_cpu_live_load_balancer_creation_with_local_tag(self, monkeypatch):
        """Test CpuLiveLoadBalancer creates with local image tag."""
        monkeypatch.setenv("FLASH_IMAGE_TAG", "local")
        # Need to reload modules to pick up new env var
        import importlib
        import runpod_flash.core.constants as const_module
        import runpod_flash.core.resources.live_serverless as ls_module

        importlib.reload(const_module)
        importlib.reload(ls_module)

        lb = ls_module.CpuLiveLoadBalancer(name="test-lb")
        expected_image = "runpod/flash-lb-cpu:py3.12-local"
        assert lb.imageName == expected_image
        assert lb.template is not None
        assert lb.template.imageName == expected_image

    def test_cpu_live_load_balancer_default_image_tag(self):
        """Test CpuLiveLoadBalancer uses default CPU LB image tag."""
        # Clear any custom tag
        os.environ.pop("FLASH_IMAGE_TAG", None)

        lb = CpuLiveLoadBalancer(name="test-lb")

        assert "runpod/flash-lb-cpu:" in lb.imageName
        assert lb.template is not None
        assert lb.template.imageName == lb.imageName

    def test_cpu_live_load_balancer_defaults(self):
        """Test CpuLiveLoadBalancer defaults to CPU3G_2_8."""
        lb = CpuLiveLoadBalancer(name="test-lb")

        # Should default to CPU3G_2_8
        assert lb.instanceIds == [CpuInstanceType.CPU3G_2_8]

    def test_cpu_live_load_balancer_with_specific_cpu_instances(self):
        """Test CpuLiveLoadBalancer with explicit CPU instances."""
        lb = CpuLiveLoadBalancer(
            name="test-lb",
            instanceIds=[CpuInstanceType.CPU3G_1_4],
        )

        assert lb.instanceIds == [CpuInstanceType.CPU3G_1_4]

    def test_cpu_live_load_balancer_type_is_lb(self):
        """Test CpuLiveLoadBalancer has type=LB."""
        lb = CpuLiveLoadBalancer(name="test-lb")

        assert lb.type.value == "LB"
        assert str(lb.type) == "ServerlessType.LB"

    def test_cpu_live_load_balancer_scaler_is_request_count(self):
        """Test CpuLiveLoadBalancer uses REQUEST_COUNT scaler."""
        lb = CpuLiveLoadBalancer(name="test-lb")

        assert lb.scalerType.value == "REQUEST_COUNT"

    def test_cpu_live_load_balancer_payload_serialization(self):
        """Test CpuLiveLoadBalancer serializes correctly for GraphQL deployment."""
        lb = CpuLiveLoadBalancer(name="data_processor")

        # Generate payload as would be sent to RunPod
        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # Template must be in payload (not imageName since that's in _input_only)
        assert "template" in payload
        assert "imageName" not in payload

        # Template must have all required fields
        template = payload["template"]
        assert "imageName" in template
        assert "name" in template
        assert template["imageName"] == lb.imageName

    def test_cpu_live_load_balancer_excludes_gpu_fields(self):
        """Test CpuLiveLoadBalancer excludes GPU fields from payload."""
        lb = CpuLiveLoadBalancer(name="test-lb")

        payload = lb.model_dump(exclude=lb._input_only, exclude_none=True, mode="json")

        # GPU-specific fields should not be in payload
        assert "gpus" not in payload
        assert "gpuIds" not in payload
        assert "cudaVersions" not in payload
