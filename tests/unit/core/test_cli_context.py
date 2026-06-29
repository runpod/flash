"""Tests for the CLI-invocation guard on lifecycle operations.

These tests run with the flash CLI context DISABLED (@pytest.mark.no_cli_context)
so that guarded methods raise FlashUsageError, mirroring direct SDK use outside
the CLI. The autouse fixture in conftest enables the context for all other tests.
"""

import pytest

from runpod_flash.core.cli_context import (
    allow_lifecycle_operations,
    cli_only,
    is_cli_invocation,
    mark_cli_invocation,
)
from runpod_flash.core.exceptions import FlashError, FlashUsageError

# The conftest ``_flash_cli_context`` fixture forces the CLI context to False for
# every no_cli_context test and restores it afterwards, so these tests start from
# a clean default regardless of order.
pytestmark = pytest.mark.no_cli_context


@cli_only("flash deploy")
async def _guarded(value: int) -> int:
    return value * 2


class TestCliOnlyDecorator:
    async def test_raises_outside_cli_context(self):
        with pytest.raises(FlashUsageError):
            await _guarded(21)

    async def test_runs_inside_allow_block(self):
        with allow_lifecycle_operations():
            assert await _guarded(21) == 42

    async def test_runs_after_mark_cli_invocation(self):
        mark_cli_invocation()
        assert await _guarded(21) == 42

    async def test_message_names_method_and_cli_command(self):
        with pytest.raises(FlashUsageError) as exc:
            await _guarded(1)
        message = str(exc.value)
        assert "_guarded" in message
        assert "flash deploy" in message

    async def test_flash_usage_error_is_flash_error(self):
        assert issubclass(FlashUsageError, FlashError)


class TestRealMethodsGuarded:
    """The guard runs before the method body, so a dummy ``self`` is enough to
    prove each real lifecycle method is decorated without constructing resources.
    """

    async def test_serverless_lifecycle_methods_guarded(self):
        from runpod_flash.core.resources.serverless import ServerlessResource

        with pytest.raises(FlashUsageError):
            await ServerlessResource.deploy(object())
        with pytest.raises(FlashUsageError):
            await ServerlessResource.undeploy(object())
        with pytest.raises(FlashUsageError):
            await ServerlessResource.update(object(), object())

    async def test_network_volume_deploy_guarded(self):
        from runpod_flash.core.resources.network_volume import NetworkVolume

        with pytest.raises(FlashUsageError):
            await NetworkVolume.deploy(object())

    async def test_flash_app_classmethods_guarded(self):
        from runpod_flash.core.resources.app import FlashApp

        with pytest.raises(FlashUsageError):
            await FlashApp.create("app")
        with pytest.raises(FlashUsageError):
            await FlashApp.get_or_create("app")
        with pytest.raises(FlashUsageError):
            await FlashApp.create_environment_and_app("app", "env")
        with pytest.raises(FlashUsageError):
            await FlashApp.delete(app_name="app")

    async def test_flash_app_instance_methods_guarded(self):
        from runpod_flash.core.resources.app import FlashApp

        with pytest.raises(FlashUsageError):
            await FlashApp.create_environment(object(), "env")
        with pytest.raises(FlashUsageError):
            await FlashApp.delete_environment(object(), "env")
        with pytest.raises(FlashUsageError):
            await FlashApp.deploy_build_to_environment(object(), "build-id")


class TestContextHelpers:
    def test_default_is_not_cli(self):
        assert is_cli_invocation() is False

    def test_allow_block_toggles_and_restores(self):
        assert is_cli_invocation() is False
        with allow_lifecycle_operations():
            assert is_cli_invocation() is True
        assert is_cli_invocation() is False

    def test_nested_allow_blocks_restore_correctly(self):
        with allow_lifecycle_operations():
            with allow_lifecycle_operations():
                assert is_cli_invocation() is True
            assert is_cli_invocation() is True
        assert is_cli_invocation() is False
