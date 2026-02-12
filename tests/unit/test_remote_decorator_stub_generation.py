"""Integration tests for @remote decorator stub generation behavior."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRemoteDecoratorStubBehavior:
    """Test that @remote decorator correctly chooses between local and stub execution."""

    @pytest.fixture
    def sample_resource(self):
        """Sample ServerlessResource for testing."""
        from runpod_flash.core.resources import ServerlessResource

        return ServerlessResource(
            name="test_worker",
            gpu="A100",
            workers=1,
        )

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=True)
    @patch("runpod_flash.client.ResourceManager")
    async def test_local_dev_invokes_resource_manager(
        self, mock_rm_class, sample_resource
    ):
        """In local dev, calling decorated function uses ResourceManager."""
        from runpod_flash.client import remote

        # Mock ResourceManager and its methods
        mock_rm_instance = AsyncMock()
        mock_remote_resource = MagicMock()
        mock_rm_instance.get_or_deploy_resource = AsyncMock(
            return_value=mock_remote_resource
        )
        mock_rm_class.return_value = mock_rm_instance

        # Mock stub_resource to return a callable
        with patch("runpod_flash.client.stub_resource") as mock_stub:
            mock_stub_callable = AsyncMock(return_value={"result": 42})
            mock_stub.return_value = mock_stub_callable

            @remote(sample_resource)
            async def process_data(x: int) -> dict:
                return {"result": x * 2}

            # Verify function is decorated and callable
            assert callable(process_data)
            assert hasattr(process_data, "__remote_config__")

            # Actually call the function to verify stub behavior
            result = await process_data(21)
            assert result == {"result": 42}
            mock_rm_instance.get_or_deploy_resource.assert_called_once_with(
                sample_resource
            )
            mock_stub.assert_called_once()
            # stub is called with (func, dependencies, system_dependencies, accelerate_downloads, *args)
            call_args = mock_stub_callable.call_args[0]
            assert callable(call_args[0])  # function
            assert call_args[1] is None  # dependencies
            assert call_args[2] is None  # system_dependencies
            assert call_args[3] is True  # accelerate_downloads
            assert call_args[4] == 21  # actual argument

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @patch("runpod_flash.runtime._flash_resource_config.is_local_function")
    async def test_deployed_local_execution_calls_original(
        self, mock_is_local, sample_resource
    ):
        """In deployed env, local functions execute original implementation."""
        from runpod_flash.client import remote

        # Configure as local function
        mock_is_local.return_value = True

        @remote(sample_resource)
        async def compute(x: int) -> int:
            return x * 2

        # Should be the original async function
        result = await compute(21)
        assert result == 42

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @patch("runpod_flash.runtime._flash_resource_config.is_local_function")
    @patch("runpod_flash.client.ResourceManager")
    async def test_deployed_remote_function_uses_stub(
        self, mock_rm_class, mock_is_local, sample_resource
    ):
        """In deployed env, remote functions create stubs."""
        from runpod_flash.client import remote

        # Configure as remote function (not local)
        mock_is_local.return_value = False

        # Mock ResourceManager
        mock_rm_instance = AsyncMock()
        mock_remote_resource = MagicMock()
        mock_rm_instance.get_or_deploy_resource = AsyncMock(
            return_value=mock_remote_resource
        )
        mock_rm_class.return_value = mock_rm_instance

        with patch("runpod_flash.client.stub_resource") as mock_stub:
            mock_stub_callable = AsyncMock(return_value={"result": 84})
            mock_stub.return_value = mock_stub_callable

            @remote(sample_resource)
            async def remote_compute(x: int) -> dict:
                # This implementation should NOT be called
                return {"result": x * 2}

            # Function should be wrapped for remote execution
            assert callable(remote_compute)
            assert hasattr(remote_compute, "__remote_config__")

            # Actually call the function to verify stub is used
            result = await remote_compute(42)
            assert result == {"result": 84}  # Stub result, not original implementation
            # stub is called with (func, dependencies, system_dependencies, accelerate_downloads, *args)
            call_args = mock_stub_callable.call_args[0]
            assert callable(call_args[0])  # function
            assert call_args[1] is None  # dependencies
            assert call_args[2] is None  # system_dependencies
            assert call_args[3] is True  # accelerate_downloads
            assert call_args[4] == 42  # actual argument
            # Verify original implementation was NOT called (result would be 84, not 42*2)

    def test_config_stored_in_function(self, sample_resource):
        """Decorator stores config in __remote_config__ attribute."""
        from runpod_flash.client import remote

        @remote(
            sample_resource,
            dependencies=["numpy", "pandas"],
            system_dependencies=["git"],
        )
        async def my_func():
            pass

        assert hasattr(my_func, "__remote_config__")
        config = my_func.__remote_config__

        assert config["resource_config"] == sample_resource
        assert config["dependencies"] == ["numpy", "pandas"]
        assert config["system_dependencies"] == ["git"]
