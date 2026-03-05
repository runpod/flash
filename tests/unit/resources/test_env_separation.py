"""
Tests for env separation: ServerlessResource.env defaults to None,
not the contents of .env file. Only explicitly declared env vars
should be carried to deployed endpoints.
"""

from runpod_flash.core.resources.live_serverless import (
    LiveServerless,
    CpuLiveServerless,
)


class TestEnvDefaultsToNone:
    """ServerlessResource.env should default to None, not .env file contents."""

    def test_serverless_resource_env_defaults_to_none(self):
        """LiveServerless with no env kwarg should have env=None."""
        resource = LiveServerless(name="test-gpu")
        assert resource.env is None

    def test_serverless_resource_env_explicit_dict_preserved(self):
        """Explicit env={"HF_TOKEN": "x"} should be preserved as-is."""
        resource = LiveServerless(name="test-gpu", env={"HF_TOKEN": "x"})
        assert resource.env == {"HF_TOKEN": "x"}

    def test_serverless_resource_env_explicit_empty_dict_preserved(self):
        """Explicit env={} should be preserved as empty dict, not replaced with None."""
        resource = LiveServerless(name="test-gpu", env={})
        assert resource.env == {}

    def test_cpu_serverless_resource_env_defaults_to_none(self):
        """CpuLiveServerless with no env kwarg should have env=None."""
        resource = CpuLiveServerless(name="test-cpu")
        assert resource.env is None


class TestCreateNewTemplateEnv:
    """_create_new_template should use empty list when env is None."""

    def test_create_new_template_with_no_env(self):
        """When resource env is None, template.env should be empty list."""
        resource = LiveServerless(name="test-gpu")
        assert resource.env is None

        template = resource._create_new_template()
        assert template.env == []

    def test_create_new_template_with_explicit_env(self):
        """When resource env has values, template.env should contain only those."""
        resource = LiveServerless(name="test-gpu", env={"HF_TOKEN": "secret"})

        template = resource._create_new_template()
        assert len(template.env) == 1
        assert template.env[0].key == "HF_TOKEN"
        assert template.env[0].value == "secret"

    def test_cpu_create_new_template_with_no_env(self):
        """CPU: when resource env is None, template.env should be empty list."""
        resource = CpuLiveServerless(name="test-cpu")
        assert resource.env is None

        template = resource._create_new_template()
        assert template.env == []
