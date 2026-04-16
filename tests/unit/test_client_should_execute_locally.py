"""tests for _should_execute_locally and the @remote wrapper dispatch logic."""

import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestShouldExecuteLocally:
    """tests for _should_execute_locally resource name comparison."""

    @patch.dict(os.environ, {}, clear=True)
    def test_local_development_returns_false(self):
        from runpod_flash.client import _should_execute_locally

        resource = MagicMock()
        resource.name = "gpu-worker"
        assert _should_execute_locally(resource) is False

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    def test_deployed_no_resource_name_defaults_true(self):
        """deployed worker without FLASH_RESOURCE_NAME defaults to local."""
        from runpod_flash.client import _should_execute_locally

        resource = MagicMock()
        resource.name = "gpu-worker"
        assert _should_execute_locally(resource) is True

    @patch.dict(
        os.environ,
        {"RUNPOD_ENDPOINT_ID": "ep_123", "FLASH_RESOURCE_NAME": "gpu-worker"},
    )
    def test_deployed_matching_name_returns_true(self):
        from runpod_flash.client import _should_execute_locally

        resource = MagicMock()
        resource.name = "gpu-worker"
        assert _should_execute_locally(resource) is True

    @patch.dict(
        os.environ,
        {"RUNPOD_ENDPOINT_ID": "ep_123", "FLASH_RESOURCE_NAME": "cpu-worker"},
    )
    def test_deployed_different_name_returns_false(self):
        from runpod_flash.client import _should_execute_locally

        resource = MagicMock()
        resource.name = "gpu-worker"
        assert _should_execute_locally(resource) is False

    @patch.dict(
        os.environ,
        {"RUNPOD_POD_ID": "pod_456", "FLASH_RESOURCE_NAME": "gpu-worker"},
    )
    def test_pod_id_also_triggers_check(self):
        from runpod_flash.client import _should_execute_locally

        resource = MagicMock()
        resource.name = "gpu-worker"
        assert _should_execute_locally(resource) is True


class TestNormalizeResourceName:
    def test_strips_live_prefix(self):
        from runpod_flash.client import _normalize_resource_name

        assert _normalize_resource_name("live-gpu-worker") == "gpu-worker"

    def test_strips_fb_suffix(self):
        from runpod_flash.client import _normalize_resource_name

        assert _normalize_resource_name("gpu-worker-fb") == "gpu-worker"

    def test_strips_both(self):
        from runpod_flash.client import _normalize_resource_name

        assert _normalize_resource_name("live-gpu-worker-fb") == "gpu-worker"

    def test_no_op_for_clean_name(self):
        from runpod_flash.client import _normalize_resource_name

        assert _normalize_resource_name("gpu-worker") == "gpu-worker"


class TestShouldExecuteLocallyNormalization:
    """name normalization in _should_execute_locally."""

    @patch.dict(
        os.environ,
        {"RUNPOD_ENDPOINT_ID": "ep_123", "FLASH_RESOURCE_NAME": "gpu-worker-fb"},
    )
    def test_matches_with_fb_suffix_on_env(self):
        from runpod_flash.client import _should_execute_locally

        resource = MagicMock()
        resource.name = "gpu-worker"
        assert _should_execute_locally(resource) is True

    @patch.dict(
        os.environ,
        {"RUNPOD_ENDPOINT_ID": "ep_123", "FLASH_RESOURCE_NAME": "gpu-worker"},
    )
    def test_matches_with_live_prefix_on_config(self):
        from runpod_flash.client import _should_execute_locally

        resource = MagicMock()
        resource.name = "live-gpu-worker"
        assert _should_execute_locally(resource) is True


class TestRemoteDecoratorIntegration:
    @patch.dict(os.environ, {}, clear=True)
    def test_local_dev_creates_wrapper(self):
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource
        import inspect

        resource = ServerlessResource(name="test_resource", gpu="A100", workers=1)

        @remote(resource)
        async def my_function(x: int) -> int:
            return x * 2

        assert hasattr(my_function, "__remote_config__")
        assert callable(my_function)
        assert inspect.iscoroutinefunction(my_function)

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    def test_deployed_local_function_returns_unwrapped(self):
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(name="test_resource", gpu="A100", workers=1)

        with patch("runpod_flash.client._should_execute_locally", return_value=True):

            @remote(resource)
            async def my_function(x: int) -> int:
                return x * 2

            assert my_function.__name__ == "my_function"
            assert hasattr(my_function, "__remote_config__")

    def test_local_true_returns_unwrapped(self):
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(name="test_resource", gpu="A100", workers=1)

        @remote(resource, local=True)
        async def my_function(x: int) -> int:
            return x * 2

        assert my_function.__name__ == "my_function"
        assert hasattr(my_function, "__remote_config__")
        assert my_function.__remote_config__["resource_config"] == resource

    @patch.dict(os.environ, {}, clear=True)
    @patch("runpod_flash.client.create_remote_class")
    def test_class_decoration_creates_remote_class(self, mock_create_remote_class):
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(name="test_resource", gpu="A100", workers=1)

        mock_wrapped_class = MagicMock()
        mock_create_remote_class.return_value = mock_wrapped_class

        @remote(resource)
        class MyClass:
            def method(self):
                pass

        mock_create_remote_class.assert_called_once()
        assert MyClass == mock_wrapped_class


class TestWrapperDispatch:
    """tests for the wrapper's sentinel vs live flow dispatch."""

    @patch.dict(os.environ, {}, clear=True)
    @pytest.mark.asyncio
    async def test_sentinel_path_when_flash_context_exists(self):
        """when get_flash_context returns a context, uses sentinel."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(name="gpu-worker", gpu="A100", workers=1)

        with (
            patch(
                "runpod_flash.client.get_flash_context",
                return_value=("myapp", "prod"),
            ),
            patch(
                "runpod_flash.client.sentinel_qb_execute",
                new_callable=AsyncMock,
                return_value={"result": 42},
            ) as mock_sentinel,
            patch("runpod_flash.client.ResourceManager") as mock_rm_cls,
        ):

            @remote(resource)
            async def my_func(x: int) -> int:
                return x * 2

            result = await my_func(5)

        assert result == {"result": 42}
        mock_sentinel.assert_awaited_once()
        # sentinel should receive the normalized resource name
        call_args = mock_sentinel.call_args
        assert call_args[0][0] == "myapp"
        assert call_args[0][1] == "prod"
        assert call_args[0][2] == "gpu-worker"
        # ResourceManager should NOT have been called
        mock_rm_cls.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @pytest.mark.asyncio
    async def test_live_path_when_no_flash_context(self):
        """when get_flash_context returns None, uses ResourceManager."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(name="gpu-worker", gpu="A100", workers=1)
        mock_deployed = MagicMock()
        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource.return_value = mock_deployed
        mock_stub = AsyncMock(return_value={"result": 42})

        with (
            patch("runpod_flash.client.get_flash_context", return_value=None),
            patch("runpod_flash.client.stub_resource", return_value=mock_stub),
            patch(
                "runpod_flash.client.ResourceManager", return_value=mock_rm
            ) as mock_rm_cls,
        ):

            @remote(resource)
            async def my_func(x: int) -> int:
                return x * 2

            await my_func(5)

        mock_rm_cls.assert_called_once()
        mock_rm.get_or_deploy_resource.assert_awaited_once_with(resource)
