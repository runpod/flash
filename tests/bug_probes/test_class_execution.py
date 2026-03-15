"""Bug probe tests for execute_class.py race conditions."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestNEW1_EnsureInitializedRace:
    """AE-2370: _ensure_initialized has no async lock — concurrent calls cause double deploy.

    Without a lock, two concurrent calls to _ensure_initialized both pass
    the `if not self._initialized` check and both call get_or_deploy_resource,
    causing a double deploy and orphaning one stub.
    """

    @pytest.fixture
    def wrapper_instance(self):
        """Create a RemoteClassWrapper instance with mocked dependencies."""

        class FakeModel:
            __name__ = "FakeModel"

            def predict(self, x):
                return x

        resource_config = MagicMock()

        with (
            patch("runpod_flash.execute_class.get_class_cache_key", return_value="key"),
            patch(
                "runpod_flash.execute_class.get_or_cache_class_data",
                return_value="code",
            ),
        ):
            from runpod_flash.execute_class import create_remote_class

            wrapper_cls = create_remote_class(
                cls=FakeModel,
                resource_config=resource_config,
                dependencies=None,
                system_dependencies=None,
                accelerate_downloads=False,
                extra={},
            )
            instance = wrapper_cls()

        return instance

    @pytest.mark.asyncio
    async def test_concurrent_calls_deploy_only_once(self, wrapper_instance):
        """Two concurrent _ensure_initialized calls must call get_or_deploy_resource exactly once."""
        deploy_call_count = 0
        gate = asyncio.Event()

        async def slow_deploy(config):
            nonlocal deploy_call_count
            deploy_call_count += 1
            await gate.wait()
            return MagicMock()

        with (
            patch("runpod_flash.execute_class.ResourceManager") as mock_rm_cls,
            patch("runpod_flash.execute_class.stub_resource", return_value=MagicMock()),
        ):
            mock_rm = MagicMock()
            mock_rm.get_or_deploy_resource = slow_deploy
            mock_rm_cls.return_value = mock_rm

            task1 = asyncio.create_task(wrapper_instance._ensure_initialized())
            task2 = asyncio.create_task(wrapper_instance._ensure_initialized())

            await asyncio.sleep(0.05)
            gate.set()

            await asyncio.gather(task1, task2)

        assert deploy_call_count == 1, (
            f"get_or_deploy_resource called {deploy_call_count} times, expected 1. "
            "Race condition: concurrent calls both passed the initialized check."
        )

    @pytest.mark.asyncio
    async def test_initialized_flag_set_after_deploy(self, wrapper_instance):
        """After _ensure_initialized completes, _initialized must be True."""
        with (
            patch("runpod_flash.execute_class.ResourceManager") as mock_rm_cls,
            patch("runpod_flash.execute_class.stub_resource", return_value=MagicMock()),
        ):
            mock_rm = MagicMock()
            mock_rm.get_or_deploy_resource = AsyncMock(return_value=MagicMock())
            mock_rm_cls.return_value = mock_rm

            await wrapper_instance._ensure_initialized()

        assert wrapper_instance._initialized is True

    @pytest.mark.asyncio
    async def test_second_call_skips_deploy(self, wrapper_instance):
        """Once initialized, subsequent calls must not call get_or_deploy_resource."""
        with (
            patch("runpod_flash.execute_class.ResourceManager") as mock_rm_cls,
            patch("runpod_flash.execute_class.stub_resource", return_value=MagicMock()),
        ):
            mock_rm = MagicMock()
            mock_rm.get_or_deploy_resource = AsyncMock(return_value=MagicMock())
            mock_rm_cls.return_value = mock_rm

            await wrapper_instance._ensure_initialized()
            mock_rm.get_or_deploy_resource.assert_awaited_once()

            await wrapper_instance._ensure_initialized()
            mock_rm.get_or_deploy_resource.assert_awaited_once()
