"""tests for live provisioning gating in the @remote decorator.

verifies that:
- standalone python execution (no FLASH_IS_LIVE_PROVISIONING) routes
  through sentinel resolution, which requires a deployed endpoint
- FLASH_IS_LIVE_PROVISIONING=true uses ResourceManager (flash dev)
- flash context tuple triggers sentinel path in deployed environments
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.client import remote
from runpod_flash.core.resources import ServerlessResource


@pytest.fixture
def gpu_resource():
    return ServerlessResource(name="my_worker", gpu="A100", workers=1)


class TestStandalonePythonExecution:
    """standalone `python worker.py` goes through the sentinel path
    because get_flash_context() returns a context tuple when
    FLASH_IS_LIVE_PROVISIONING is not set."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=True)
    @patch("runpod_flash.flash_sentinel.sentinel_qb_execute", new_callable=AsyncMock)
    @patch(
        "runpod_flash.flash_context.get_flash_context",
        return_value=("my_project", "production"),
    )
    async def test_routes_through_sentinel(self, mock_ctx, mock_sentinel, gpu_resource):
        mock_sentinel.return_value = {"result": 1}

        @remote(gpu_resource)
        async def my_func(x: int) -> int:
            return x * 2

        result = await my_func(1)
        assert result == {"result": 1}
        mock_sentinel.assert_awaited_once()
        args = mock_sentinel.call_args[0]
        assert args[0] == "my_project"
        assert args[1] == "production"
        assert args[2] == "my_worker"

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=True)
    @patch(
        "runpod_flash.flash_context.get_flash_context",
        return_value=("01_hello_world", "production"),
    )
    @patch("runpod_flash.flash_sentinel.sentinel_qb_execute", new_callable=AsyncMock)
    async def test_sentinel_404_raises_deploy_first_error(
        self, mock_sentinel, mock_ctx, gpu_resource
    ):
        """simulates the exact error a user sees when running python worker.py
        against a non-deployed endpoint."""
        mock_sentinel.side_effect = RuntimeError(
            "endpoint 'my_worker' not found in app '01_hello_world' "
            "environment 'production'. deploy it first with 'flash deploy'."
        )

        @remote(gpu_resource)
        async def my_func(x: int) -> int:
            return x * 2

        with pytest.raises(RuntimeError, match="deploy it first"):
            await my_func(1)

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"}, clear=True)
    @patch(
        "runpod_flash.flash_context.get_flash_context",
        return_value=("myapp", "production"),
    )
    @patch("runpod_flash.flash_sentinel.sentinel_qb_execute", new_callable=AsyncMock)
    async def test_sentinel_path_when_live_provisioning_false(
        self, mock_sentinel, mock_ctx, gpu_resource
    ):
        mock_sentinel.return_value = "ok"

        @remote(gpu_resource)
        async def my_func() -> str:
            return "local"

        result = await my_func()
        assert result == "ok"
        mock_sentinel.assert_awaited_once()


class TestFlashDevExecution:
    """flash dev sets FLASH_IS_LIVE_PROVISIONING=true, enabling the
    ResourceManager live provisioning path."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"}, clear=True)
    @patch("runpod_flash.client.ResourceManager")
    @patch("runpod_flash.client.stub_resource")
    async def test_uses_resource_manager(
        self, mock_stub_resource, mock_rm_class, gpu_resource
    ):
        mock_rm = AsyncMock()
        mock_deployed = MagicMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_deployed)
        mock_rm_class.return_value = mock_rm

        mock_stub = AsyncMock(return_value={"result": 42})
        mock_stub_resource.return_value = mock_stub

        @remote(gpu_resource)
        async def my_func(x: int) -> dict:
            return {"result": x * 2}

        result = await my_func(21)

        assert result == {"result": 42}
        mock_rm.get_or_deploy_resource.assert_called_once_with(gpu_resource)

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "TRUE"}, clear=True)
    @patch("runpod_flash.client.ResourceManager")
    @patch("runpod_flash.client.stub_resource")
    async def test_case_insensitive_true(
        self, mock_stub_resource, mock_rm_class, gpu_resource
    ):
        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=MagicMock())
        mock_rm_class.return_value = mock_rm

        mock_stub_resource.return_value = AsyncMock(return_value="ok")

        @remote(gpu_resource)
        async def my_func() -> str:
            return "local"

        result = await my_func()
        assert result == "ok"
        mock_rm.get_or_deploy_resource.assert_called_once()


class TestLiveProvisioningGuardRail:
    """the RuntimeError guard in client.py is a defensive check for when
    get_flash_context returns None but FLASH_IS_LIVE_PROVISIONING is
    not set to true."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=True)
    @patch("runpod_flash.flash_context.get_flash_context", return_value=None)
    async def test_raises_when_context_none_and_not_live(self, mock_ctx, gpu_resource):
        @remote(gpu_resource)
        async def my_func(x: int) -> int:
            return x * 2

        with pytest.raises(RuntimeError, match="cannot be called"):
            await my_func(1)

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=True)
    @patch("runpod_flash.flash_context.get_flash_context", return_value=None)
    async def test_error_message_includes_resource_name(self, mock_ctx, gpu_resource):
        @remote(gpu_resource)
        async def my_func(x: int) -> int:
            return x * 2

        with pytest.raises(RuntimeError, match="my_worker"):
            await my_func(1)


class TestSentinelResolution:
    """when get_flash_context() returns a context tuple, the wrapper
    uses sentinel resolution instead of live provisioning."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=True)
    @patch(
        "runpod_flash.flash_context.get_flash_context",
        return_value=("myapp", "production"),
    )
    @patch("runpod_flash.flash_sentinel.sentinel_qb_execute", new_callable=AsyncMock)
    async def test_sentinel_path_when_context_present(
        self, mock_sentinel, mock_ctx, gpu_resource
    ):
        mock_sentinel.return_value = {"result": 99}

        @remote(gpu_resource)
        async def my_func(x: int) -> dict:
            return {"result": x}

        result = await my_func(42)

        assert result == {"result": 99}
        mock_sentinel.assert_awaited_once()
        args = mock_sentinel.call_args[0]
        assert args[0] == "myapp"
        assert args[1] == "production"
        assert args[2] == "my_worker"

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"}, clear=True)
    @patch("runpod_flash.client.ResourceManager")
    @patch("runpod_flash.client.stub_resource")
    async def test_live_path_when_context_none(
        self, mock_stub_resource, mock_rm_class, gpu_resource
    ):
        """FLASH_IS_LIVE_PROVISIONING=true makes get_flash_context return None,
        so the wrapper falls through to the live provisioning path."""
        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=MagicMock())
        mock_rm_class.return_value = mock_rm
        mock_stub_resource.return_value = AsyncMock(return_value="live")

        @remote(gpu_resource)
        async def my_func() -> str:
            return "original"

        result = await my_func()
        assert result == "live"
        mock_rm.get_or_deploy_resource.assert_called_once()
