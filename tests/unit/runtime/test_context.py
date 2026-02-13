"""Tests for runtime context detection utilities."""

import os
from unittest.mock import patch

from runpod_flash.runtime.context import is_deployed_container, is_local_development


class TestIsDeployedContainer:
    """Tests for is_deployed_container function."""

    def test_deployed_with_endpoint_id(self):
        """Should return True when RUNPOD_ENDPOINT_ID is set."""
        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "test-endpoint-123"}):
            assert is_deployed_container() is True

    def test_deployed_with_pod_id(self):
        """Should return True when RUNPOD_POD_ID is set."""
        with patch.dict(os.environ, {"RUNPOD_POD_ID": "test-pod-456"}, clear=True):
            assert is_deployed_container() is True

    def test_deployed_with_both_ids(self):
        """Should return True when both IDs are set."""
        with patch.dict(
            os.environ,
            {
                "RUNPOD_ENDPOINT_ID": "test-endpoint-123",
                "RUNPOD_POD_ID": "test-pod-456",
            },
        ):
            assert is_deployed_container() is True

    def test_local_development_no_env_vars(self):
        """Should return False when no RunPod env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_deployed_container() is False

    def test_local_development_empty_env_vars(self):
        """Should return False when RunPod env vars are empty."""
        with patch.dict(
            os.environ, {"RUNPOD_ENDPOINT_ID": "", "RUNPOD_POD_ID": ""}, clear=True
        ):
            assert is_deployed_container() is False


class TestIsLocalDevelopment:
    """Tests for is_local_development function."""

    def test_local_no_env_vars(self):
        """Should return True when no RunPod env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_local_development() is True

    def test_not_local_with_endpoint_id(self):
        """Should return False when RUNPOD_ENDPOINT_ID is set."""
        with patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "test-endpoint-123"}):
            assert is_local_development() is False

    def test_not_local_with_pod_id(self):
        """Should return False when RUNPOD_POD_ID is set."""
        with patch.dict(os.environ, {"RUNPOD_POD_ID": "test-pod-456"}, clear=True):
            assert is_local_development() is False

    def test_inverse_of_is_deployed(self):
        """Should always be inverse of is_deployed_container."""
        test_cases = [
            {},
            {"RUNPOD_ENDPOINT_ID": "test-123"},
            {"RUNPOD_POD_ID": "test-456"},
            {"RUNPOD_ENDPOINT_ID": "test-123", "RUNPOD_POD_ID": "test-456"},
        ]

        for env_vars in test_cases:
            with patch.dict(os.environ, env_vars, clear=True):
                assert is_local_development() == (not is_deployed_container())
