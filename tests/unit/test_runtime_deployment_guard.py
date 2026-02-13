"""
Tests for runtime deployment guard in @remote decorator and remote classes.

Ensures that resources are not deployed at runtime in deployed containers,
and that clear errors guide users to run 'flash deploy' first.
"""

import sys
import types
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from runpod_flash.client import remote
from runpod_flash.core.resources import ServerlessResource


def create_mock_resource_config_module(is_local_function_mock):
    """Create a mock runtime._flash_resource_config module."""
    mock_module = types.ModuleType("_flash_resource_config")
    mock_module.is_local_function = is_local_function_mock
    return mock_module


class TestRemoteDecoratorDeploymentGuard:
    """Test deployment guard in @remote decorator for functions."""

    @pytest.mark.asyncio
    async def test_remote_decorator_uses_service_registry_in_deployed_env(
        self, monkeypatch
    ):
        """
        Verify @remote decorator uses ServiceRegistry when available in deployed env.

        In deployed environments, if ServiceRegistry has the endpoint, use it
        without attempting deployment.
        """
        # Mock deployed environment
        monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "test-endpoint-id")

        # Create mock service registry that returns a resource
        mock_resource = Mock()
        mock_resource.name = "test_resource"
        mock_service_registry_class = MagicMock()
        mock_service_registry_instance = AsyncMock()
        mock_service_registry_instance.get_resource_for_function = AsyncMock(
            return_value=mock_resource
        )
        mock_service_registry_class.return_value = mock_service_registry_instance

        # Create mock stub
        mock_stub = AsyncMock(return_value="result")

        # Mock is_local_function to return False (so wrapper is created)
        mock_is_local_function = MagicMock(return_value=False)
        mock_config_module = create_mock_resource_config_module(mock_is_local_function)

        with (
            patch(
                "runpod_flash.runtime.service_registry.ServiceRegistry",
                mock_service_registry_class,
            ),
            patch("runpod_flash.client.stub_resource", return_value=mock_stub),
            patch.dict(
                sys.modules,
                {"runpod_flash.runtime._flash_resource_config": mock_config_module},
            ),
        ):
            # Define and decorate a function
            config = Mock(spec=ServerlessResource)
            config.name = "test_config"
            config.config_hash = "0123456789abcdef" * 4  # 64 char hash
            config.get_resource_key = Mock(
                return_value="ServerlessResource:test_config"
            )

            @remote(config)
            async def test_func():
                return "test_result"

            # Call the function
            await test_func()

            # Verify ServiceRegistry was called
            mock_service_registry_instance.get_resource_for_function.assert_called_once_with(
                "test_func"
            )

            # Verify stub was created with the resource from ServiceRegistry
            mock_stub.assert_called_once()

    @pytest.mark.asyncio
    async def test_remote_decorator_raises_error_when_endpoint_missing_in_deployed_env(
        self, monkeypatch
    ):
        """
        Verify @remote decorator raises error when endpoint missing in deployed env.

        In deployed environments, if ServiceRegistry returns None (endpoint not in
        manifest), should raise descriptive error instead of trying to deploy.
        """
        # Mock deployed environment
        monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "test-endpoint-id")

        # Create mock service registry that returns None
        mock_service_registry_class = MagicMock()
        mock_service_registry_instance = AsyncMock()
        mock_service_registry_instance.get_resource_for_function = AsyncMock(
            return_value=None
        )
        mock_service_registry_class.return_value = mock_service_registry_instance

        # Mock is_local_function to return False (so wrapper is created)
        mock_is_local_function = MagicMock(return_value=False)
        mock_config_module = create_mock_resource_config_module(mock_is_local_function)

        with (
            patch(
                "runpod_flash.runtime.service_registry.ServiceRegistry",
                mock_service_registry_class,
            ),
            patch.dict(
                sys.modules,
                {"runpod_flash.runtime._flash_resource_config": mock_config_module},
            ),
        ):
            config = Mock(spec=ServerlessResource)
            config.name = "test_config"
            config.config_hash = "0123456789abcdef" * 4  # 64 char hash
            config.get_resource_key = Mock(
                return_value="ServerlessResource:test_config"
            )

            @remote(config)
            async def test_func():
                return "test_result"

            # Call should raise RuntimeError
            with pytest.raises(RuntimeError) as exc_info:
                await test_func()

            # Verify error message mentions manifest and flash deploy
            error_msg = str(exc_info.value)
            assert "endpoint not found in manifest" in error_msg
            assert "flash deploy" in error_msg

    @pytest.mark.asyncio
    async def test_remote_decorator_raises_error_when_service_registry_fails_in_deployed_env(
        self, monkeypatch
    ):
        """
        Verify @remote decorator raises error when ServiceRegistry fails in deployed env.

        In deployed environments, if ServiceRegistry raises an exception (e.g.,
        State Manager unavailable), should raise descriptive error instead of
        falling back to ResourceManager.
        """
        # Mock deployed environment
        monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "test-endpoint-id")

        # Create mock service registry that raises an exception
        mock_service_registry_class = MagicMock()
        mock_service_registry_instance = AsyncMock()
        mock_service_registry_instance.get_resource_for_function = AsyncMock(
            side_effect=ValueError("State Manager unavailable")
        )
        mock_service_registry_class.return_value = mock_service_registry_instance

        # Mock is_local_function to return False (so wrapper is created)
        mock_is_local_function = MagicMock(return_value=False)
        mock_config_module = create_mock_resource_config_module(mock_is_local_function)

        with (
            patch(
                "runpod_flash.runtime.service_registry.ServiceRegistry",
                mock_service_registry_class,
            ),
            patch.dict(
                sys.modules,
                {"runpod_flash.runtime._flash_resource_config": mock_config_module},
            ),
        ):
            config = Mock(spec=ServerlessResource)
            config.name = "test_config"
            config.config_hash = "0123456789abcdef" * 4  # 64 char hash
            config.get_resource_key = Mock(
                return_value="ServerlessResource:test_config"
            )

            @remote(config)
            async def test_func():
                return "test_result"

            # Call should raise RuntimeError with deployment context error
            with pytest.raises(RuntimeError) as exc_info:
                await test_func()

            # Verify error message mentions deployed environment
            error_msg = str(exc_info.value)
            assert "deployed environment" in error_msg
            assert "State Manager" in error_msg

    @pytest.mark.asyncio
    async def test_remote_decorator_guards_deployment_in_deployed_env(
        self, monkeypatch
    ):
        """
        Verify @remote decorator prevents ResourceManager fallback in deployed env.

        When ServiceRegistry returns None in a deployed environment, the wrapper
        should NOT fall back to ResourceManager.get_or_deploy_resource().
        """
        # Mock deployed environment
        monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "test-endpoint-id")

        # Create mock service registry that returns None
        mock_service_registry_class = MagicMock()
        mock_service_registry_instance = AsyncMock()
        mock_service_registry_instance.get_resource_for_function = AsyncMock(
            return_value=None
        )
        mock_service_registry_class.return_value = mock_service_registry_instance

        # Create a mock ResourceManager that tracks if it's called
        resource_manager_called = False

        def mock_resource_manager_init(*args, **kwargs):
            nonlocal resource_manager_called
            resource_manager_called = True
            raise AssertionError(
                "ResourceManager should NOT be instantiated in deployed environment"
            )

        # Mock is_local_function to return False (so wrapper is created)
        mock_is_local_function = MagicMock(return_value=False)
        mock_config_module = create_mock_resource_config_module(mock_is_local_function)

        with (
            patch(
                "runpod_flash.runtime.service_registry.ServiceRegistry",
                mock_service_registry_class,
            ),
            patch(
                "runpod_flash.core.resources.ResourceManager",
                side_effect=mock_resource_manager_init,
            ),
            patch.dict(
                sys.modules,
                {"runpod_flash.runtime._flash_resource_config": mock_config_module},
            ),
        ):
            config = Mock(spec=ServerlessResource)
            config.name = "test_config"
            config.config_hash = "0123456789abcdef" * 4  # 64 char hash
            config.get_resource_key = Mock(
                return_value="ServerlessResource:test_config"
            )

            @remote(config)
            async def test_func():
                return "test_result"

            # Call should raise RuntimeError and NOT instantiate ResourceManager
            with pytest.raises(RuntimeError) as exc_info:
                await test_func()

            # Verify ResourceManager was NOT called (deployment guard worked)
            assert not resource_manager_called
            error_msg = str(exc_info.value)
            assert "endpoint not found in manifest" in error_msg


class TestRemoteClassDeploymentGuard:
    """Test deployment guard in remote class initialization."""

    @pytest.mark.asyncio
    async def test_remote_class_raises_error_when_endpoint_missing_in_deployed_env(
        self, monkeypatch
    ):
        """
        Verify remote class raises error when endpoint missing in deployed env.

        When initializing a remote class in deployed environment and ServiceRegistry
        returns None, should raise error instead of attempting deployment.
        """
        # Mock deployed environment
        monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "test-endpoint-id")

        # Create mock service registry that returns None
        mock_service_registry_class = MagicMock()
        mock_service_registry_instance = AsyncMock()
        mock_service_registry_instance.get_resource_for_function = AsyncMock(
            return_value=None
        )
        mock_service_registry_class.return_value = mock_service_registry_instance

        with patch(
            "runpod_flash.runtime.service_registry.ServiceRegistry",
            mock_service_registry_class,
        ):
            from runpod_flash.execute_class import create_remote_class

            class TestClass:
                def method(self):
                    return "test"

            config = Mock(spec=ServerlessResource)
            config.name = "test_config"
            config.config_hash = "0123456789abcdef" * 4  # 64 char hash
            config.get_resource_key = Mock(
                return_value="ServerlessResource:test_config"
            )

            RemoteClass = create_remote_class(TestClass, config, None, None, False, {})
            instance = RemoteClass()

            # Should raise RuntimeError when accessing method
            with pytest.raises(RuntimeError) as exc_info:
                await instance._ensure_initialized()

            error_msg = str(exc_info.value)
            assert "endpoint not found in manifest" in error_msg
            assert "flash deploy" in error_msg

    @pytest.mark.asyncio
    async def test_remote_class_guards_deployment_in_deployed_env(self, monkeypatch):
        """
        Verify remote class prevents ResourceManager fallback in deployed env.

        When ServiceRegistry returns None in a deployed environment during remote
        class initialization, ResourceManager should NOT be called.
        """
        # Mock deployed environment
        monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "test-endpoint-id")

        # Create mock service registry that returns None
        mock_service_registry_class = MagicMock()
        mock_service_registry_instance = AsyncMock()
        mock_service_registry_instance.get_resource_for_function = AsyncMock(
            return_value=None
        )
        mock_service_registry_class.return_value = mock_service_registry_instance

        # Create a mock ResourceManager that tracks if it's called
        def mock_resource_manager_init(*args, **kwargs):
            raise AssertionError(
                "ResourceManager should NOT be instantiated in deployed environment"
            )

        with (
            patch(
                "runpod_flash.runtime.service_registry.ServiceRegistry",
                mock_service_registry_class,
            ),
            patch(
                "runpod_flash.core.resources.ResourceManager",
                side_effect=mock_resource_manager_init,
            ),
        ):
            from runpod_flash.execute_class import create_remote_class

            class TestClass:
                def method(self):
                    return "test"

            config = Mock(spec=ServerlessResource)
            config.name = "test_config"
            config.config_hash = "0123456789abcdef" * 4  # 64 char hash
            config.get_resource_key = Mock(
                return_value="ServerlessResource:test_config"
            )

            RemoteClass = create_remote_class(TestClass, config, None, None, False, {})
            instance = RemoteClass()

            # Should raise RuntimeError and NOT instantiate ResourceManager
            with pytest.raises(RuntimeError) as exc_info:
                await instance._ensure_initialized()

            # Verify it's our deployment guard error, not the ResourceManager error
            error_msg = str(exc_info.value)
            assert "endpoint not found in manifest" in error_msg
