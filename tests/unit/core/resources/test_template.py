"""Tests for template module (PodTemplate and KeyValuePair)."""

import pytest

from runpod_flash.core.resources.template import KeyValuePair, PodTemplate


class TestKeyValuePair:
    """Test KeyValuePair functionality."""

    def test_basic_creation(self):
        """Test basic KeyValuePair creation."""
        pair = KeyValuePair(key="MY_KEY", value="my_value")

        assert pair.key == "MY_KEY"
        assert pair.value == "my_value"

    def test_from_dict_single_pair(self):
        """Test creating KeyValuePair from dictionary with single entry."""
        data = {"API_KEY": "secret123"}

        pairs = KeyValuePair.from_dict(data)

        assert len(pairs) == 1
        assert pairs[0].key == "API_KEY"
        assert pairs[0].value == "secret123"

    def test_from_dict_multiple_pairs(self):
        """Test creating multiple KeyValuePairs from dictionary."""
        data = {
            "DATABASE_URL": "postgresql://localhost/db",
            "API_KEY": "secret123",
            "DEBUG": "true",
        }

        pairs = KeyValuePair.from_dict(data)

        assert len(pairs) == 3
        keys = {pair.key for pair in pairs}
        assert "DATABASE_URL" in keys
        assert "API_KEY" in keys
        assert "DEBUG" in keys

    def test_from_dict_empty(self):
        """Test creating KeyValuePairs from empty dictionary."""
        data = {}

        pairs = KeyValuePair.from_dict(data)

        assert len(pairs) == 0

    def test_from_dict_invalid_input(self):
        """Test that from_dict raises error for non-dictionary input."""
        with pytest.raises(ValueError, match="Input must be a dictionary"):
            KeyValuePair.from_dict("not a dict")

        with pytest.raises(ValueError, match="Input must be a dictionary"):
            KeyValuePair.from_dict([("key", "value")])

    def test_pydantic_validation(self):
        """Test Pydantic validation for KeyValuePair."""
        # Valid creation
        pair = KeyValuePair(key="KEY", value="value")
        assert pair.key == "KEY"

        # Invalid - missing required field
        with pytest.raises(Exception):  # Pydantic ValidationError
            KeyValuePair(key="KEY")

    def test_model_dump(self):
        """Test converting KeyValuePair to dictionary."""
        pair = KeyValuePair(key="MY_KEY", value="my_value")

        dumped = pair.model_dump()

        assert dumped["key"] == "MY_KEY"
        assert dumped["value"] == "my_value"

    def test_special_characters_in_values(self):
        """Test KeyValuePair with special characters."""
        pair = KeyValuePair(
            key="DATABASE_URL",
            value="postgresql://user:p@ss!word@localhost:5432/db?sslmode=require",
        )

        assert "p@ss!word" in pair.value
        assert "?" in pair.value

    def test_from_dict_preserves_order(self):
        """Test that from_dict preserves dictionary order."""
        data = {"FIRST": "1", "SECOND": "2", "THIRD": "3"}

        pairs = KeyValuePair.from_dict(data)

        # In Python 3.7+, dict order is preserved
        assert pairs[0].key == "FIRST"
        assert pairs[1].key == "SECOND"
        assert pairs[2].key == "THIRD"


class TestPodTemplate:
    """Test PodTemplate functionality."""

    def test_default_values(self):
        """Test PodTemplate with default values."""
        template = PodTemplate()

        assert template.advancedStart is False
        assert template.config == {}
        assert template.containerDiskInGb == 64
        assert template.containerRegistryAuthId == ""
        assert template.dockerArgs == ""
        assert template.env == []
        assert template.imageName == ""
        assert template.ports == ""
        assert template.startScript == ""

    def test_basic_template_creation(self):
        """Test creating a basic template."""
        template = PodTemplate(
            name="my_template",
            imageName="myregistry/myimage:v1.0",
            containerDiskInGb=100,
        )

        assert "my_template" in template.name
        assert template.imageName == "myregistry/myimage:v1.0"
        assert template.containerDiskInGb == 100

    def test_template_with_environment_variables(self):
        """Test template with environment variables."""
        env_vars = [
            KeyValuePair(key="API_KEY", value="secret"),
            KeyValuePair(key="DEBUG", value="true"),
        ]

        template = PodTemplate(
            name="env_template",
            imageName="test/image:latest",
            env=env_vars,
        )

        assert len(template.env) == 2
        assert template.env[0].key == "API_KEY"
        assert template.env[1].key == "DEBUG"

    def test_template_with_ports(self):
        """Test template with port configuration."""
        template = PodTemplate(
            name="port_template",
            imageName="nginx:latest",
            ports="8080/http,8443/https",
        )

        assert template.ports == "8080/http,8443/https"

    def test_template_with_start_script(self):
        """Test template with start script."""
        start_script = "#!/bin/bash\necho 'Starting service'\npython app.py"

        template = PodTemplate(
            name="script_template",
            imageName="python:3.11",
            startScript=start_script,
        )

        assert template.startScript == start_script
        assert "python app.py" in template.startScript

    def test_template_with_docker_args(self):
        """Test template with Docker arguments."""
        docker_args = "--network=host --privileged"

        template = PodTemplate(
            name="docker_template",
            imageName="ubuntu:22.04",
            dockerArgs=docker_args,
        )

        assert template.dockerArgs == docker_args

    def test_template_advanced_start(self):
        """Test template with advanced start enabled."""
        template = PodTemplate(
            name="advanced_template",
            imageName="test/image:latest",
            advancedStart=True,
        )

        assert template.advancedStart is True

    def test_template_with_registry_auth(self):
        """Test template with container registry authentication."""
        template = PodTemplate(
            name="private_template",
            imageName="private-registry.com/myimage:latest",
            containerRegistryAuthId="auth_id_123",
        )

        assert template.containerRegistryAuthId == "auth_id_123"

    def test_template_with_custom_config(self):
        """Test template with custom configuration."""
        custom_config = {
            "gpu_count": 2,
            "memory_gb": 32,
            "custom_field": "value",
        }

        template = PodTemplate(
            name="config_template",
            imageName="test/image:latest",
            config=custom_config,
        )

        assert template.config["gpu_count"] == 2
        assert template.config["memory_gb"] == 32

    def test_name_includes_resource_id(self):
        """Test that template name includes resource_id after validation."""
        template = PodTemplate(
            name="base_name",
            imageName="test/image:latest",
        )

        # After validation, name should include resource_id
        assert "base_name__" in template.name
        assert len(template.name) > len("base_name")

    def test_template_resource_id_generation(self):
        """Test that PodTemplate generates stable resource_id."""
        template1 = PodTemplate(
            name="test_template",
            imageName="test/image:v1",
            containerDiskInGb=100,
        )

        template2 = PodTemplate(
            name="test_template",
            imageName="test/image:v1",
            containerDiskInGb=100,
        )

        # Should have same base configuration hash
        # (name will differ due to resource_id suffix, but resource_id should be stable)
        assert template1.resource_id == template2.resource_id

    def test_template_different_config_different_id(self):
        """Test that different configurations produce different resource_ids."""
        template1 = PodTemplate(
            name="test_template",
            imageName="test/image:v1",
            containerDiskInGb=100,
        )

        template2 = PodTemplate(
            name="test_template",
            imageName="test/image:v2",  # Different image
            containerDiskInGb=100,
        )

        assert template1.resource_id != template2.resource_id

    def test_template_model_dump(self):
        """Test dumping template to dictionary."""
        template = PodTemplate(
            name="dump_template",
            imageName="test/image:latest",
            containerDiskInGb=50,
            env=[KeyValuePair(key="KEY", value="value")],
        )

        dumped = template.model_dump()

        assert "name" in dumped
        assert dumped["imageName"] == "test/image:latest"
        assert dumped["containerDiskInGb"] == 50
        assert len(dumped["env"]) == 1

    def test_template_optional_fields_none(self):
        """Test template with optional fields set to None."""
        template = PodTemplate(
            name="minimal_template",
            imageName="test/image:latest",
            ports=None,
            startScript=None,
            dockerArgs=None,
        )

        # Optional fields should default to empty string or empty list
        assert template.ports in [None, ""]
        assert template.startScript in [None, ""]
        assert template.dockerArgs in [None, ""]

    def test_template_disk_size_validation(self):
        """Test various disk size configurations."""
        # Small disk
        template_small = PodTemplate(
            name="small", imageName="test/image:latest", containerDiskInGb=10
        )
        assert template_small.containerDiskInGb == 10

        # Large disk
        template_large = PodTemplate(
            name="large", imageName="test/image:latest", containerDiskInGb=500
        )
        assert template_large.containerDiskInGb == 500

    def test_template_inherits_base_resource(self):
        """Test that PodTemplate inherits BaseResource functionality."""
        template = PodTemplate(
            name="inheritance_test",
            imageName="test/image:latest",
        )

        # Should have BaseResource properties
        assert hasattr(template, "resource_id")
        assert hasattr(template, "config_hash")
        assert hasattr(template, "get_resource_key")

        # resource_id should be set
        resource_id = template.resource_id
        assert resource_id.startswith("PodTemplate_")

    def test_template_json_serialization(self):
        """Test JSON serialization of PodTemplate."""
        template = PodTemplate(
            name="json_template",
            imageName="test/image:latest",
            containerDiskInGb=75,
            env=[KeyValuePair(key="ENV_VAR", value="value")],
        )

        json_str = template.model_dump_json()

        assert "json_template" in json_str
        assert "test/image:latest" in json_str
        assert "ENV_VAR" in json_str

    def test_template_empty_name(self):
        """Test template with empty name."""
        template = PodTemplate(
            name="",
            imageName="test/image:latest",
        )

        # Name should still get resource_id appended
        assert "__PodTemplate_" in template.name

    def test_template_complex_start_script(self):
        """Test template with complex multi-line start script."""
        start_script = """#!/bin/bash
set -e

# Install dependencies
apt-get update && apt-get install -y curl

# Start application
python -m uvicorn app:main --host 0.0.0.0 --port 8000
"""

        template = PodTemplate(
            name="complex_script",
            imageName="python:3.11-slim",
            startScript=start_script,
        )

        assert "apt-get update" in template.startScript
        assert "uvicorn" in template.startScript

    def test_template_get_resource_key(self):
        """Test get_resource_key for PodTemplate."""
        template = PodTemplate(
            name="key_test",
            imageName="test/image:latest",
        )

        resource_key = template.get_resource_key()

        # Should include class name and name
        assert "PodTemplate" in resource_key
        assert "key_test" in resource_key
