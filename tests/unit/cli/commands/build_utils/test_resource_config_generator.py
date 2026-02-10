"""Unit tests for resource configuration generator."""

import pytest

from runpod_flash.cli.commands.build_utils.resource_config_generator import (
    _format_set,
    generate_all_resource_configs,
)


class TestFormatSet:
    """Tests for _format_set helper function."""

    def test_format_empty_set(self):
        """Empty set returns empty string."""
        result = _format_set(set())
        assert result == ""

    def test_format_single_item(self):
        """Single item formatted correctly."""
        result = _format_set({"func_a"})
        assert result == '"func_a"'

    def test_format_multiple_items(self):
        """Multiple items formatted and sorted."""
        result = _format_set({"func_c", "func_a", "func_b"})
        assert result == '"func_a", "func_b", "func_c"'

    def test_format_maintains_sort_order(self):
        """Verify items are sorted alphabetically."""
        result = _format_set({"zebra", "apple", "monkey"})
        assert result == '"apple", "monkey", "zebra"'


class TestGenerateAllResourceConfigs:
    """Tests for generate_all_resource_configs function."""

    @pytest.fixture
    def sample_manifest(self):
        """Sample manifest with resources and function registry."""
        return {
            "function_registry": {
                "preprocess": "cpu_worker",
                "gpu_inference": "gpu_worker",
                "postprocess": "cpu_worker",
                "classify": "mothership",
            },
            "resources": {
                "cpu_worker": {"type": "queue"},
                "gpu_worker": {"type": "queue"},
                "mothership": {"type": "load_balancer"},
            },
        }

    @pytest.fixture
    def build_dir(self, tmp_path):
        """Temporary build directory."""
        return tmp_path / "build"

    def test_creates_config_file(self, sample_manifest, build_dir):
        """Config file is created at expected path."""
        generate_all_resource_configs(sample_manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        assert config_file.exists()

    def test_config_contains_resource_mappings(self, sample_manifest, build_dir):
        """Config file contains mappings for all resources."""
        generate_all_resource_configs(sample_manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        content = config_file.read_text()

        # Check resource names are present
        assert '"cpu_worker"' in content
        assert '"gpu_worker"' in content
        assert '"mothership"' in content

    def test_config_maps_functions_correctly(self, sample_manifest, build_dir):
        """Functions are mapped to correct resources."""
        generate_all_resource_configs(sample_manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        content = config_file.read_text()

        # CPU worker should have preprocess and postprocess
        assert '"preprocess"' in content
        assert '"postprocess"' in content

        # GPU worker should have gpu_inference
        assert '"gpu_inference"' in content

        # Mothership should have classify
        assert '"classify"' in content

    def test_config_is_valid_python(self, sample_manifest, build_dir):
        """Generated config is valid Python code."""
        generate_all_resource_configs(sample_manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        content = config_file.read_text()

        # Should compile without errors
        compile(content, str(config_file), "exec")

    def test_config_contains_is_local_function(self, sample_manifest, build_dir):
        """Config contains is_local_function implementation."""
        generate_all_resource_configs(sample_manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        content = config_file.read_text()

        assert "def is_local_function(func_name: str) -> bool:" in content
        assert "FLASH_RESOURCE_NAME" in content
        assert "os.getenv" in content

    def test_handles_empty_function_registry(self, build_dir):
        """Handles manifest with no functions."""
        manifest = {"function_registry": {}, "resources": {"worker": {}}}

        generate_all_resource_configs(manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        assert config_file.exists()

        content = config_file.read_text()
        assert "RESOURCE_LOCAL_FUNCTIONS = {" in content

    def test_handles_resource_with_no_functions(self, build_dir):
        """Handles resource that has no assigned functions."""
        manifest = {
            "function_registry": {"func_a": "worker_a"},
            "resources": {
                "worker_a": {},
                "worker_b": {},  # No functions assigned
            },
        }

        generate_all_resource_configs(manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        content = config_file.read_text()

        # worker_b should have empty set
        assert '"worker_b": {}' in content

    def test_creates_parent_directories(self, sample_manifest, build_dir):
        """Creates runtime directory if it doesn't exist."""
        assert not (build_dir / "runpod_flash" / "runtime").exists()

        generate_all_resource_configs(sample_manifest, build_dir)

        assert (build_dir / "runpod_flash" / "runtime").exists()

    def test_config_handles_special_characters_in_function_names(self, build_dir):
        """Handles function names with underscores and numbers."""
        manifest = {
            "function_registry": {
                "func_with_underscore": "worker",
                "func123": "worker",
                "_private_func": "worker",
            },
            "resources": {"worker": {}},
        }

        generate_all_resource_configs(manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        content = config_file.read_text()

        assert '"func_with_underscore"' in content
        assert '"func123"' in content
        assert '"_private_func"' in content

    def test_logs_generation_summary(self, sample_manifest, build_dir, caplog):
        """Logs summary of generated configuration."""
        import logging

        caplog.set_level(logging.INFO)

        generate_all_resource_configs(sample_manifest, build_dir)

        # Check log message contains resource count and function count
        assert any(
            "3 resources" in record.message
            and "4 total function mappings" in record.message
            for record in caplog.records
        )

    def test_functions_sorted_alphabetically(self, build_dir):
        """Functions within each resource are sorted alphabetically."""
        manifest = {
            "function_registry": {
                "zebra": "worker",
                "apple": "worker",
                "monkey": "worker",
            },
            "resources": {"worker": {}},
        }

        generate_all_resource_configs(manifest, build_dir)

        config_file = (
            build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
        )
        content = config_file.read_text()

        # Find the worker line and check order
        assert '"apple", "monkey", "zebra"' in content
