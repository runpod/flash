"""Tests for versioned Docker image name resolution."""

import os
from unittest.mock import patch

import pytest

from runpod_flash.core.constants import (
    CPU_PYTHON_VERSIONS,
    DEFAULT_PYTHON_VERSION,
    GPU_BASE_IMAGE_PYTHON_VERSION,
    GPU_PYTHON_VERSIONS,
    SUPPORTED_PYTHON_VERSIONS,
    get_image_name,
    local_python_version,
    validate_python_version,
)


class TestSupportedPythonVersions:
    def test_supported_versions(self):
        assert SUPPORTED_PYTHON_VERSIONS == ("3.10", "3.11", "3.12")

    def test_gpu_python_versions(self):
        assert GPU_PYTHON_VERSIONS == ("3.12",)

    def test_cpu_python_versions(self):
        assert CPU_PYTHON_VERSIONS == ("3.12",)

    def test_default_python_version_is_3_12(self):
        assert DEFAULT_PYTHON_VERSION == "3.12"

    def test_gpu_base_image_python_version(self):
        assert GPU_BASE_IMAGE_PYTHON_VERSION == "3.12"


class TestGetImageName:
    def test_gpu_3_12(self):
        assert (
            get_image_name("gpu", "3.12", tag="latest") == "runpod/flash:py3.12-latest"
        )

    def test_gpu_3_11_raises(self):
        with pytest.raises(ValueError, match="GPU endpoints require"):
            get_image_name("gpu", "3.11", tag="latest")

    def test_gpu_3_10_raises(self):
        with pytest.raises(ValueError, match="GPU endpoints require"):
            get_image_name("gpu", "3.10", tag="latest")

    def test_cpu_3_12(self):
        assert (
            get_image_name("cpu", "3.12", tag="latest")
            == "runpod/flash-cpu:py3.12-latest"
        )

    def test_cpu_3_11_raises(self):
        with pytest.raises(ValueError, match="CPU endpoints require"):
            get_image_name("cpu", "3.11", tag="latest")

    def test_cpu_3_10_raises(self):
        with pytest.raises(ValueError, match="CPU endpoints require"):
            get_image_name("cpu", "3.10", tag="latest")

    def test_lb_3_11_raises(self):
        with pytest.raises(ValueError, match="GPU endpoints require"):
            get_image_name("lb", "3.11", tag="latest")

    def test_lb_3_10_raises(self):
        with pytest.raises(ValueError, match="GPU endpoints require"):
            get_image_name("lb", "3.10", tag="latest")

    def test_lb_3_12(self):
        assert (
            get_image_name("lb", "3.12", tag="latest")
            == "runpod/flash-lb:py3.12-latest"
        )

    def test_lb_cpu_3_12(self):
        assert (
            get_image_name("lb-cpu", "3.12", tag="latest")
            == "runpod/flash-lb-cpu:py3.12-latest"
        )

    def test_lb_cpu_3_10_raises(self):
        with pytest.raises(ValueError, match="CPU endpoints require"):
            get_image_name("lb-cpu", "3.10", tag="latest")

    def test_default_tag_reads_flash_image_tag_env(self):
        with patch.dict(os.environ, {"FLASH_IMAGE_TAG": "v1.0"}):
            assert get_image_name("gpu", "3.12") == "runpod/flash:py3.12-v1.0"

    def test_default_tag_without_env_is_latest(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_image_name("gpu", "3.12") == "runpod/flash:py3.12-latest"

    def test_invalid_image_type_raises(self):
        with pytest.raises(ValueError, match="Unknown image type"):
            get_image_name("invalid", "3.12")

    def test_invalid_python_version_raises(self):
        with pytest.raises(ValueError, match="not supported"):
            get_image_name("gpu", "3.13")

    def test_custom_tag(self):
        assert get_image_name("gpu", "3.12", tag="v2.0") == "runpod/flash:py3.12-v2.0"

    def test_env_var_override_gpu(self):
        with patch.dict(os.environ, {"FLASH_GPU_IMAGE": "custom/gpu:mine"}):
            assert get_image_name("gpu", "3.11") == "custom/gpu:mine"

    def test_env_var_override_cpu(self):
        with patch.dict(os.environ, {"FLASH_CPU_IMAGE": "custom/cpu:mine"}):
            assert get_image_name("cpu", "3.11") == "custom/cpu:mine"

    def test_env_var_override_lb(self):
        with patch.dict(os.environ, {"FLASH_LB_IMAGE": "custom/lb:mine"}):
            assert get_image_name("lb", "3.11") == "custom/lb:mine"

    def test_env_var_override_lb_cpu(self):
        with patch.dict(os.environ, {"FLASH_CPU_LB_IMAGE": "custom/lb-cpu:mine"}):
            assert get_image_name("lb-cpu", "3.11") == "custom/lb-cpu:mine"

    def test_env_var_override_bypasses_unsupported_version(self):
        with patch.dict(os.environ, {"FLASH_GPU_IMAGE": "custom/gpu:mine"}):
            assert get_image_name("gpu", "3.9") == "custom/gpu:mine"

    def test_env_var_override_bypasses_gpu_version_constraint(self):
        """env var override works even for versions not in GPU_PYTHON_VERSIONS."""
        with patch.dict(os.environ, {"FLASH_GPU_IMAGE": "custom/gpu:mine"}):
            assert get_image_name("gpu", "3.8") == "custom/gpu:mine"


class TestLocalPythonVersion:
    def test_returns_3_12(self):
        assert local_python_version() == "3.12"

    def test_returns_string_type(self):
        assert isinstance(local_python_version(), str)


class TestValidatePythonVersion:
    def test_valid_versions(self):
        for v in SUPPORTED_PYTHON_VERSIONS:
            assert validate_python_version(v) == v

    def test_invalid_version_raises(self):
        with pytest.raises(ValueError, match="not supported"):
            validate_python_version("3.13")

    def test_old_version_raises(self):
        with pytest.raises(ValueError, match="not supported"):
            validate_python_version("3.9")
