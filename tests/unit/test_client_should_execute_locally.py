"""Unit tests for _should_execute_locally and _resolve_deployed_endpoint_id in client.py."""

import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
            mock_is_local_function.assert_called_once_with("func")


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


class TestResolveDeployedEndpointId:
    """Tests for _resolve_deployed_endpoint_id manifest lookup."""

    def setup_method(self):
        """Reset module-level _service_registry between tests."""
        import runpod_flash.client as client_module

        client_module._service_registry = None

    @patch.dict(os.environ, {}, clear=True)
    @pytest.mark.asyncio
    async def test_returns_none_in_local_dev(self):
        """No RunPod env vars returns None (local dev)."""
        from runpod_flash.client import _resolve_deployed_endpoint_id

        result = await _resolve_deployed_endpoint_id("my_func")
        assert result is None

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @pytest.mark.asyncio
    async def test_returns_endpoint_id_in_deployed_env(self):
        """Deployed env with valid manifest returns endpoint ID."""
        from runpod_flash.client import _resolve_deployed_endpoint_id

        mock_registry = AsyncMock()
        mock_registry.get_endpoint_for_function.return_value = (
            "https://api.runpod.ai/v2/abc123"
        )

        import runpod_flash.client as client_module

        client_module._service_registry = mock_registry

        result = await _resolve_deployed_endpoint_id("classify")

        assert result == "abc123"
        mock_registry.get_endpoint_for_function.assert_awaited_once_with("classify")

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @pytest.mark.asyncio
    async def test_returns_none_on_import_error(self):
        """ServiceRegistry unavailable returns None gracefully."""
        from runpod_flash.client import _resolve_deployed_endpoint_id

        with patch.dict("sys.modules", {"runpod_flash.runtime.service_registry": None}):
            import runpod_flash.client as client_module

            client_module._service_registry = None

            result = await _resolve_deployed_endpoint_id("my_func")

        assert result is None

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @pytest.mark.asyncio
    async def test_returns_none_when_function_not_in_manifest(self):
        """Function not in manifest raises ValueError, returns None."""
        from runpod_flash.client import _resolve_deployed_endpoint_id

        mock_registry = AsyncMock()
        mock_registry.get_endpoint_for_function.side_effect = ValueError(
            "Function 'unknown_func' not found in manifest."
        )

        import runpod_flash.client as client_module

        client_module._service_registry = mock_registry

        result = await _resolve_deployed_endpoint_id("unknown_func")
        assert result is None

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @pytest.mark.asyncio
    async def test_returns_none_when_no_endpoint_url(self):
        """get_endpoint_for_function returns None (local function) returns None."""
        from runpod_flash.client import _resolve_deployed_endpoint_id

        mock_registry = AsyncMock()
        mock_registry.get_endpoint_for_function.return_value = None

        import runpod_flash.client as client_module

        client_module._service_registry = mock_registry

        result = await _resolve_deployed_endpoint_id("local_func")
        assert result is None

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @pytest.mark.asyncio
    async def test_returns_none_on_malformed_url(self):
        """Malformed URL with no path returns None."""
        from runpod_flash.client import _resolve_deployed_endpoint_id

        mock_registry = AsyncMock()
        mock_registry.get_endpoint_for_function.return_value = "https://example.com/"

        import runpod_flash.client as client_module

        client_module._service_registry = mock_registry

        result = await _resolve_deployed_endpoint_id("my_func")
        # URL path "/" after rstrip("/") is "", split gives [""] → last is ""
        assert result is None

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @pytest.mark.asyncio
    async def test_caches_service_registry_instance(self):
        """Second call reuses cached ServiceRegistry singleton."""
        import runpod_flash.client as client_module

        mock_registry = AsyncMock()
        mock_registry.get_endpoint_for_function.return_value = (
            "https://api.runpod.ai/v2/ep_abc"
        )

        # Pre-set the registry to simulate first call already cached it
        client_module._service_registry = mock_registry

        from runpod_flash.client import _resolve_deployed_endpoint_id

        result1 = await _resolve_deployed_endpoint_id("func_a")
        result2 = await _resolve_deployed_endpoint_id("func_b")

        assert result1 == "ep_abc"
        assert result2 == "ep_abc"
        # Same instance reused — no reconstruction
        assert client_module._service_registry is mock_registry


class TestWrapperManifestLookup:
    """Tests for wrapper() manifest lookup before ResourceManager fallback."""

    def setup_method(self):
        """Reset module-level _service_registry between tests."""
        import runpod_flash.client as client_module

        client_module._service_registry = None

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @patch("runpod_flash.client._should_execute_locally", return_value=False)
    @pytest.mark.asyncio
    async def test_deployed_env_skips_resource_manager(self, _):
        """When manifest resolves endpoint, ResourceManager is not called."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(name="test_resource", gpu="A100", workers=1)
        mock_stub = AsyncMock(return_value={"result": 42})

        with (
            patch(
                "runpod_flash.client._resolve_deployed_endpoint_id",
                return_value="ep_deployed_abc",
            ) as mock_resolve,
            patch(
                "runpod_flash.client.stub_resource", return_value=mock_stub
            ) as mock_stub_resource,
            patch("runpod_flash.client.ResourceManager") as mock_rm_cls,
        ):

            @remote(resource)
            async def my_func(x: int) -> int:
                return x * 2

            await my_func(5)

        mock_resolve.assert_awaited_once_with("my_func")
        mock_stub_resource.assert_called_once()
        # ResourceManager should NOT have been instantiated
        mock_rm_cls.assert_not_called()
        # stub_resource receives a copy with the resolved id, original is unmutated
        passed_resource = mock_stub_resource.call_args[0][0]
        assert passed_resource.id == "ep_deployed_abc"
        assert resource.id is None  # original not mutated

    @patch.dict(os.environ, {}, clear=True)
    @pytest.mark.asyncio
    async def test_local_dev_uses_resource_manager(self):
        """In local dev, manifest returns None and ResourceManager is used."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(name="test_resource", gpu="A100", workers=1)
        mock_deployed = MagicMock()
        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource.return_value = mock_deployed
        mock_stub = AsyncMock(return_value={"result": 42})

        with (
            patch(
                "runpod_flash.client._resolve_deployed_endpoint_id",
                return_value=None,
            ) as mock_resolve,
            patch("runpod_flash.client.stub_resource", return_value=mock_stub),
            patch(
                "runpod_flash.client.ResourceManager", return_value=mock_rm
            ) as mock_rm_cls,
        ):

            @remote(resource)
            async def my_func(x: int) -> int:
                return x * 2

            await my_func(5)

        mock_resolve.assert_awaited_once_with("my_func")
        mock_rm_cls.assert_called_once()
        mock_rm.get_or_deploy_resource.assert_awaited_once_with(resource)

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep_123"})
    @patch("runpod_flash.client._should_execute_locally", return_value=False)
    @pytest.mark.asyncio
    async def test_fallback_to_resource_manager_on_failure(self, _):
        """When manifest lookup returns None, falls back to ResourceManager."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import ServerlessResource

        resource = ServerlessResource(name="test_resource", gpu="A100", workers=1)
        mock_deployed = MagicMock()
        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource.return_value = mock_deployed
        mock_stub = AsyncMock(return_value={"result": 42})

        with (
            patch(
                "runpod_flash.client._resolve_deployed_endpoint_id",
                return_value=None,
            ),
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
