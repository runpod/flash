"""Tests for versioned Docker image name resolution."""

import os
from unittest.mock import patch

import pytest

from runpod_flash.core.resources.constants import (
    CPU_PYTHON_VERSIONS,
    DEFAULT_PYTHON_VERSION,
    GPU_PYTHON_VERSIONS,
    SUPPORTED_PYTHON_VERSIONS,
    get_image_name,
    validate_python_version,
)


class TestSupportedPythonVersions:
    def test_supported_versions(self):
        assert SUPPORTED_PYTHON_VERSIONS == ("3.10", "3.11", "3.12", "3.13")

    def test_gpu_python_versions(self):
        assert GPU_PYTHON_VERSIONS == ("3.10", "3.11", "3.12", "3.13")

    def test_cpu_python_versions(self):
        assert CPU_PYTHON_VERSIONS == ("3.10", "3.11", "3.12", "3.13")

    def test_default_python_version_is_3_12(self):
        assert DEFAULT_PYTHON_VERSION == "3.12"

    def test_supported_python_versions_contains_310_through_313(self):
        from runpod_flash.core.resources.constants import SUPPORTED_PYTHON_VERSIONS

        assert SUPPORTED_PYTHON_VERSIONS == ("3.10", "3.11", "3.12", "3.13")

    def test_default_python_version_unchanged_for_latest_alias(self):
        """DEFAULT_PYTHON_VERSION drives the :latest tag alias, not SDK fallback."""
        from runpod_flash.core.resources.constants import DEFAULT_PYTHON_VERSION

        assert DEFAULT_PYTHON_VERSION == "3.12"


class TestGetImageName:
    def test_gpu_3_12(self):
        assert (
            get_image_name("gpu", "3.12", tag="latest") == "runpod/flash:py3.12-latest"
        )

    def test_gpu_3_13(self):
        assert (
            get_image_name("gpu", "3.13", tag="latest") == "runpod/flash:py3.13-latest"
        )

    @pytest.mark.parametrize("version", ["3.10", "3.11", "3.12", "3.13"])
    def test_gpu_all_supported_versions(self, version):
        assert (
            get_image_name("gpu", version, tag="latest")
            == f"runpod/flash:py{version}-latest"
        )

    @pytest.mark.parametrize("version", ["3.10", "3.11", "3.12", "3.13"])
    def test_cpu_all_supported_versions(self, version):
        assert (
            get_image_name("cpu", version, tag="latest")
            == f"runpod/flash-cpu:py{version}-latest"
        )

    @pytest.mark.parametrize("version", ["3.10", "3.11", "3.12", "3.13"])
    def test_lb_all_supported_versions(self, version):
        assert (
            get_image_name("lb", version, tag="latest")
            == f"runpod/flash-lb:py{version}-latest"
        )

    @pytest.mark.parametrize("version", ["3.10", "3.11", "3.12", "3.13"])
    def test_lb_cpu_all_supported_versions(self, version):
        assert (
            get_image_name("lb-cpu", version, tag="latest")
            == f"runpod/flash-lb-cpu:py{version}-latest"
        )

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
            get_image_name("gpu", "3.99")
            get_image_name("gpu", "3.14")

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


class TestValidatePythonVersion:
    def test_valid_versions(self):
        for v in SUPPORTED_PYTHON_VERSIONS:
            assert validate_python_version(v) == v

    def test_invalid_version_raises(self):
        with pytest.raises(ValueError, match="not supported"):
            validate_python_version("3.99")
            validate_python_version("3.14")

    def test_old_version_raises(self):
        with pytest.raises(ValueError, match="not supported"):
            validate_python_version("3.9")
