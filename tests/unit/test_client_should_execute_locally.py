"""Unit tests for _should_execute_locally function in client.py."""

import os
from unittest.mock import MagicMock, patch


class TestShouldExecuteLocally:
    """Tests for _should_execute_locally decision logic."""

    @patch.dict(os.environ, {}, clear=True)
    def test_local_development_returns_false(self):
        """Local development (no RunPod env vars) returns False to create stub."""
        from runpod_flash.client import _should_execute_locally

        # No RUNPOD_ENDPOINT_ID or RUNPOD_POD_ID
        result = _should_execute_locally("test_func")
        assert result is False

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @patch("runpod_flash.client.log")
    def test_deployed_env_missing_config_defaults_true(self, mock_log):
        """Deployed env without config file defaults to True (safe)."""
        from runpod_flash.client import _should_execute_locally

        # Mock ImportError when trying to import config
        with patch.dict(
            "sys.modules", {"runpod_flash.runtime._flash_resource_config": None}
        ):
            result = _should_execute_locally("test_func")

            # Should default to True for safety
            assert result is True
            # Should log warning
            mock_log.warning.assert_called_once()
            assert "Resource configuration" in str(mock_log.warning.call_args)
            assert "defaulting to local execution" in str(mock_log.warning.call_args)

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    def test_deployed_env_with_config_uses_is_local_function(self):
        """Deployed env with config uses is_local_function."""
        from runpod_flash.client import _should_execute_locally

        # Mock the config module
        mock_is_local_function = MagicMock(return_value=True)
        mock_config = MagicMock()
        mock_config.is_local_function = mock_is_local_function

        with patch(
            "runpod_flash.runtime._flash_resource_config.is_local_function",
            mock_is_local_function,
        ):
            result = _should_execute_locally("my_function")

            # Should use config
            assert result is True
            mock_is_local_function.assert_called_once_with("my_function")

    @patch.dict(os.environ, {"RUNPOD_POD_ID": "pod_456"})
    def test_pod_id_triggers_config_lookup(self):
        """RUNPOD_POD_ID (without endpoint ID) still triggers config lookup."""
        from runpod_flash.client import _should_execute_locally

        mock_is_local_function = MagicMock(return_value=False)

        with patch(
            "runpod_flash.runtime._flash_resource_config.is_local_function",
            mock_is_local_function,
        ):
            result = _should_execute_locally("remote_func")

            assert result is False
            mock_is_local_function.assert_called_once_with("remote_func")

    @patch.dict(
        os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123", "RUNPOD_POD_ID": "pod_456"}
    )
    def test_both_env_vars_uses_config(self):
        """Both endpoint and pod ID present uses config."""
        from runpod_flash.client import _should_execute_locally

        mock_is_local_function = MagicMock(return_value=True)

        with patch(
            "runpod_flash.runtime._flash_resource_config.is_local_function",
            mock_is_local_function,
        ):
            result = _should_execute_locally("func")

            assert result is True
            mock_is_local_function.assert_called_once()


class TestRemoteDecoratorIntegration:
    """Integration tests for @remote decorator with _should_execute_locally."""

    @patch.dict(os.environ, {}, clear=True)
    def test_local_dev_creates_wrapper(self):
        """In local dev, decorator creates async wrapper (stub)."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(
            name="test_resource",
            gpu="A100",
            workers=1,
        )

        @remote(resource)
        async def my_function(x: int) -> int:
            return x * 2

        # Should have remote config attached
        assert hasattr(my_function, "__remote_config__")
        # @wraps preserves original name, so check it's still callable
        assert callable(my_function)
        # Verify it's still async (wrapper is also async)
        import inspect

        assert inspect.iscoroutinefunction(my_function)

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    def test_deployed_local_function_returns_unwrapped(self):
        """In deployed env, local function returns unwrapped."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(
            name="test_resource",
            gpu="A100",
            workers=1,
        )

        # Mock is_local_function to return True
        with patch("runpod_flash.client._should_execute_locally", return_value=True):

            @remote(resource)
            async def my_function(x: int) -> int:
                return x * 2

            # Should be the original function, not wrapped
            assert my_function.__name__ == "my_function"
            assert hasattr(my_function, "__remote_config__")

    def test_local_true_returns_unwrapped(self):
        """local=True returns unwrapped function."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(
            name="test_resource",
            gpu="A100",
            workers=1,
        )

        @remote(resource, local=True)
        async def my_function(x: int) -> int:
            return x * 2

        # Should be the original function
        assert my_function.__name__ == "my_function"
        assert hasattr(my_function, "__remote_config__")

        # Verify config is attached
        assert my_function.__remote_config__["resource_config"] == resource

    @patch.dict(os.environ, {}, clear=True)
    @patch("runpod_flash.client.create_remote_class")
    def test_class_decoration_creates_remote_class(self, mock_create_remote_class):
        """Decorating a class in local dev creates remote class."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(
            name="test_resource",
            gpu="A100",
            workers=1,
        )

        # Mock create_remote_class to return a MagicMock
        mock_wrapped_class = MagicMock()
        mock_create_remote_class.return_value = mock_wrapped_class

        @remote(resource)
        class MyClass:
            def method(self):
                pass

        # Should call create_remote_class
        mock_create_remote_class.assert_called_once()

        # Should return the wrapped class
        assert MyClass == mock_wrapped_class
